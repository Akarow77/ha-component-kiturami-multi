"""Pure helpers for the Kiturami IoT Multi Manager protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RoomDevice:
    """A room controller returned by the Multi Manager API."""

    parent_id: str
    node_id: str
    room_id: str
    name: str
    device_name: str


def _first_text(source: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _find_device_list(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []

    for key in ("deviceInfoList", "memberDeviceList", "eachRoomDeviceList"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]

    for key in ("data", "result"):
        nested = _find_device_list(payload.get(key))
        if nested:
            return nested
    return []


def normalize_room_id(value: str) -> str:
    """Normalize the two-character room/slave identifier used in messages."""
    room_id = str(value).strip().upper().zfill(2)
    if len(room_id) != 2 or any(char not in "0123456789ABCDEF" for char in room_id):
        raise ValueError(f"Invalid Kiturami room id: {value!r}")
    return room_id


def room_devices_from_response(payload: Any) -> list[RoomDevice]:
    """Convert the API's current and older field names into room devices."""
    devices: list[RoomDevice] = []
    seen: set[tuple[str, str]] = set()

    for item in _find_device_list(payload):
        node_id = _first_text(item, "deviceTopic", "nodeId", "nodeID")
        raw_room_id = _first_text(item, "eachRoomID", "eachRoomId", "slaveId")
        if not node_id or not raw_room_id:
            continue

        try:
            room_id = normalize_room_id(raw_room_id)
        except ValueError:
            continue

        identity = (node_id, room_id)
        if identity in seen:
            continue
        seen.add(identity)

        parent_id = _first_text(item, "parentId", "parentID") or "1"
        device_alias = _first_text(item, "deviceAlias")
        device_name = _first_text(item, "deviceName", "deviceAlias") or "멀티 매니저"
        room_name = _first_text(
            item,
            "roomName",
            "eachRoomName",
            "slaveAlias",
        )
        if not room_name:
            room_label = f"각방 {room_id}"
            room_name = f"{device_alias} ({room_label})" if device_alias else room_label

        devices.append(
            RoomDevice(
                parent_id=parent_id,
                node_id=node_id,
                room_id=room_id,
                name=room_name,
                device_name=device_name,
            )
        )
    return devices


def temperature_to_hex(temperature: float) -> str:
    """Encode an integer Celsius value as the two-character protocol value."""
    value = int(round(float(temperature)))
    if not 0 <= value <= 255:
        raise ValueError(f"Temperature is outside the protocol range: {temperature}")
    return f"{value:02X}"


def temperature_from_hex(value: Any) -> float:
    """Decode a temperature value supplied by the API."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        raise ValueError("Empty temperature value")
    return float(int(text, 16))


def power_action(room_id: str, enabled: bool) -> tuple[str, str]:
    """Return action id/data for per-room power."""
    state = "01" if enabled else "02"
    return "0101", f"{normalize_room_id(room_id)}00000000{state}"


def indoor_heat_action(room_id: str, temperature: float) -> tuple[str, str]:
    """Return action id/data for Celsius room heating."""
    if not 5 <= float(temperature) <= 45:
        raise ValueError(f"Room temperature must be between 5 and 45°C: {temperature}")
    action_data = (
        f"{normalize_room_id(room_id)}000000{temperature_to_hex(temperature)}00"
    )
    return "0102", action_data


def away_action(room_id: str) -> tuple[str, str]:
    """Return action id/data for per-room away mode."""
    return "0106", f"{normalize_room_id(room_id)}0200000000"


def mode_info_from_response(payload: Any, room_id: str) -> dict[str, Any]:
    """Unwrap a mode response, selecting the requested room when it is a list."""
    requested = normalize_room_id(room_id)
    if isinstance(payload, Mapping):
        if any(
            key in payload
            for key in ("deviceMode", "currentTemp", "currentValue", "value")
        ):
            return dict(payload)
        for key in ("modeInfo", "deviceInfo", "data", "result"):
            nested = mode_info_from_response(payload.get(key), requested)
            if nested:
                return nested
        for key in ("modeInfoList", "detailItemList", "deviceInfoList"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if not isinstance(item, Mapping):
                        continue
                    item_room = _first_text(item, "eachRoomID", "eachRoomId", "slaveId")
                    if item_room and normalize_room_id(item_room) == requested:
                        return dict(item)
    return {}
