"""Climate entities for Kiturami IoT Multi Manager rooms."""

from __future__ import annotations

import datetime
import logging
from datetime import timedelta
from enum import StrEnum
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, CONF_SCAN_INTERVAL, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KituramiConfigEntry
from .api import KrbAPI, KrbError
from .const import DOMAIN, MAX_TEMP, MIN_TEMP, MODEL, TITLE
from .protocol import RoomDevice, temperature_from_hex

_LOGGER = logging.getLogger(__name__)


class PresetMode(StrEnum):
    """Modes confirmed to carry a per-room identifier."""

    HEAT = "난방"
    AWAY = "외출"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KituramiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one climate entity per room controller."""
    api = entry.runtime_data
    try:
        devices = await api.client.async_get_room_devices()
    except KrbError as ex:
        raise PlatformNotReady(f"각방 목록 조회 실패: {ex}") from ex
    if not devices:
        raise PlatformNotReady("멀티 매니저 계정에서 각방 조절기를 찾지 못했습니다")

    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, 1)
    async_add_entities(
        [KituramiRoomClimate(api, device, scan_interval) for device in devices],
        True,
    )


class KituramiRoomClimate(ClimateEntity):
    """A single room attached to a Kiturami Multi Manager."""

    _attr_has_entity_name = True
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [PresetMode.HEAT, PresetMode.AWAY]
    _attr_precision = 1
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = 1
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, api: KrbAPI, device: RoomDevice, scan_interval: int) -> None:
        self._api = api
        self._room = device
        self._min_time_between_updates = timedelta(minutes=scan_interval)
        self._last_updated: datetime.datetime | None = None
        self._device_mode = ""

        safe_node = device.node_id.replace(":", "_")
        self._attr_unique_id = f"{DOMAIN}-{safe_node}-{device.room_id}"
        self._attr_name = device.name
        self._attr_available = False
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_preset_mode = PresetMode.HEAT
        self._attr_device_info = DeviceInfo(
            configuration_url="https://krb.co.kr",
            identifiers={(DOMAIN, device.node_id)},
            name=f"{TITLE} {device.device_name}",
            manufacturer="귀뚜라미",
            model=MODEL,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "parent_id": self._room.parent_id,
            "node_id": self._room.node_id,
            "room_id": self._room.room_id,
            "device_mode": self._device_mode,
            "last_updated": self._last_updated,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        if self.hvac_mode == HVACMode.OFF:
            await self._api.async_turn_on(self._room.node_id, self._room.room_id)
        await self._api.async_set_temperature(
            self._room.node_id, self._room.room_id, float(temperature)
        )
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_preset_mode = PresetMode.HEAT
        self._attr_target_temperature = float(temperature)
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == PresetMode.HEAT:
            await self._api.async_turn_on(self._room.node_id, self._room.room_id)
            self._attr_hvac_mode = HVACMode.HEAT
        elif preset_mode == PresetMode.AWAY:
            await self._api.async_set_away(self._room.node_id, self._room.room_id)
            self._attr_hvac_mode = HVACMode.HEAT
        else:
            raise ValueError(f"지원하지 않는 각방 모드: {preset_mode}")
        self._attr_preset_mode = preset_mode
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.HEAT:
            await self._api.async_turn_on(self._room.node_id, self._room.room_id)
        elif hvac_mode == HVACMode.OFF:
            await self._api.async_turn_off(self._room.node_id, self._room.room_id)
        else:
            raise ValueError(f"지원하지 않는 HVAC 모드: {hvac_mode}")
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def async_update(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        if (
            self._last_updated
            and now - self._last_updated < self._min_time_between_updates
        ):
            return

        try:
            result = await self._api.async_device_mode_info(
                self._room.parent_id,
                self._room.node_id,
                self._room.room_id,
            )
        except KrbError as ex:
            _LOGGER.warning("%s 상태 조회 실패: %s", self._room.name, ex)
            self._attr_available = False
            return

        if not result:
            self._attr_available = False
            return

        self._attr_available = True
        self._last_updated = now
        self._device_mode = str(result.get("deviceMode") or "")
        self._attr_hvac_mode = (
            HVACMode.OFF if self._device_mode == "0101" else HVACMode.HEAT
        )
        self._attr_preset_mode = (
            PresetMode.AWAY if self._device_mode == "0106" else PresetMode.HEAT
        )

        current = result.get("currentTemp")
        target = next(
            (
                result.get(key)
                for key in ("value", "currentValue", "realValue", "selectValue")
                if result.get(key) not in (None, "")
            ),
            None,
        )
        try:
            if current is not None:
                self._attr_current_temperature = temperature_from_hex(current)
            if target is not None:
                self._attr_target_temperature = temperature_from_hex(target)
        except TypeError, ValueError:
            _LOGGER.debug("온도 응답을 해석하지 못했습니다: %s", result)
