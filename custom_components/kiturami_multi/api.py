"""Cloud API client for Kiturami IoT Multi Manager."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import aiohttp

from .const import KITURAMI_API_URL
from .protocol import (
    RoomDevice,
    away_action,
    indoor_heat_action,
    mode_info_from_response,
    power_action,
    room_devices_from_response,
)

_LOGGER = logging.getLogger(__name__)


class KrbError(Exception):
    """Base exception for the Kiturami cloud API."""


class KrbAuthError(KrbError):
    """Raised when the account cannot be authenticated."""


class KrbConnectionError(KrbError):
    """Raised when the cloud API cannot be reached or decoded."""


class KrbClient:
    """Small HTTPS client matching Multi Manager 2.8.4."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.username = username
        self._password = password
        self._session = session
        self.auth_key = ""

    async def _request_once(
        self,
        session: aiohttp.ClientSession,
        path: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> tuple[int, str]:
        async with session.post(
            f"{KITURAMI_API_URL}/{path.lstrip('/')}",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            return response.status, await response.text()

    async def _async_post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        authenticated: bool = True,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json; charset=UTF-8"}
        if authenticated and self.auth_key:
            headers["AUTH-KEY"] = self.auth_key

        try:
            if self._session is not None:
                status, text = await self._request_once(
                    self._session, path, payload, headers
                )
            else:
                async with aiohttp.ClientSession() as session:
                    status, text = await self._request_once(
                        session, path, payload, headers
                    )
        except (aiohttp.ClientError, TimeoutError) as ex:
            raise KrbConnectionError(f"귀뚜라미 서버 연결 실패: {ex}") from ex

        logged_response = "<redacted>" if path == "member/login" else text
        _LOGGER.debug(
            "Kiturami %s status=%s response=%s", path, status, logged_response
        )

        if authenticated and retry_auth and status in (401, 403):
            await self.async_login()
            return await self._async_post(path, payload, retry_auth=False)
        if status != 200:
            raise KrbConnectionError(f"귀뚜라미 서버 HTTP 오류: {status}")

        try:
            result = json.loads(text)
        except (TypeError, json.JSONDecodeError) as ex:
            raise KrbConnectionError("귀뚜라미 서버 응답을 해석할 수 없습니다") from ex
        if not isinstance(result, dict):
            raise KrbConnectionError(
                "귀뚜라미 서버가 예상하지 못한 응답을 반환했습니다"
            )
        code = result.get("code")
        if code not in (None, 100, 200, "100", "200"):
            message = result.get("message") or f"API 오류 코드 {code}"
            raise KrbError(str(message))
        return result

    async def async_login(self) -> str:
        """Authenticate using the request fields used by Multi Manager."""
        password_hash = hashlib.sha256(self._password.encode("utf-8")).hexdigest()
        try:
            result = await self._async_post(
                "member/login",
                {"userIdentifier": self.username, "password": password_hash},
                authenticated=False,
                retry_auth=False,
            )
        except KrbConnectionError:
            raise
        except KrbError as ex:
            raise KrbAuthError(str(ex)) from ex
        auth_key = result.get("authenticationKey")
        if not auth_key and isinstance(result.get("data"), dict):
            auth_key = result["data"].get("authenticationKey")
        if not auth_key:
            message = result.get("message") or "아이디 또는 비밀번호를 확인하세요"
            raise KrbAuthError(str(message))
        self.auth_key = str(auth_key)
        return self.auth_key

    async def async_get_room_devices(self) -> list[RoomDevice]:
        """Return all room controllers registered to the account."""
        result = await self._async_post(
            "member/getMemberEachRoomDeviceList",
            {"parentCode": "1"},
        )
        return room_devices_from_response(result)


class KrbAPI:
    """High-level per-room API."""

    def __init__(self, client: KrbClient) -> None:
        self.client = client

    async def async_device_info(
        self, parent_id: str, node_id: str, room_id: str
    ) -> dict[str, Any]:
        return await self.client._async_post(
            "device/getDeviceInfo",
            {
                "parentId": parent_id,
                "nodeId": node_id,
                "slaveId": room_id,
                "commandId": "",
            },
        )

    async def async_device_mode_info(
        self,
        parent_id: str,
        node_id: str,
        room_id: str,
        command_id: str = "0102",
    ) -> dict[str, Any]:
        result = await self.client._async_post(
            "device/getDeviceModeInfo",
            {
                "parentId": parent_id,
                "nodeId": node_id,
                "slaveId": room_id,
                "commandId": command_id,
            },
        )
        return mode_info_from_response(result, room_id)

    async def async_device_control(
        self, node_id: str, action_id: str, action_data: str
    ) -> dict[str, Any]:
        return await self.client._async_post(
            "device/deviceControl",
            {
                "nodeIds": [node_id],
                "actionID": action_id,
                "actionData": action_data,
            },
        )

    async def async_turn_on(self, node_id: str, room_id: str) -> None:
        action_id, action_data = power_action(room_id, True)
        await self.async_device_control(node_id, action_id, action_data)

    async def async_turn_off(self, node_id: str, room_id: str) -> None:
        action_id, action_data = power_action(room_id, False)
        await self.async_device_control(node_id, action_id, action_data)

    async def async_set_temperature(
        self, node_id: str, room_id: str, temperature: float
    ) -> None:
        action_id, action_data = indoor_heat_action(room_id, temperature)
        await self.async_device_control(node_id, action_id, action_data)

    async def async_set_away(self, node_id: str, room_id: str) -> None:
        action_id, action_data = away_action(room_id)
        await self.async_device_control(node_id, action_id, action_data)
