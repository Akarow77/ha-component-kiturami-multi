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
    device_nodes_from_response,
    indoor_heat_action,
    legacy_room_devices_from_response,
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
        self.login_scheme = ""

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
        # Multi Manager's OkHttp interceptor sends this header on every request,
        # including login where its value is an empty string.
        headers["AUTH-KEY"] = self.auth_key if authenticated else ""

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
        # The API uses responseCode/responseMessage for normal responses, but
        # code/message for malformed requests and some gateway errors.
        code = result.get("responseCode", result.get("code"))
        if code not in (None, 100, 200, "100", "200"):
            message = (
                result.get("responseMessage")
                or result.get("errorMessage")
                or result.get("message")
                or f"API 오류 코드 {code}"
            )
            _LOGGER.warning(
                "Kiturami API rejected %s: code=%s message=%s",
                path,
                code,
                message,
            )
            if authenticated and retry_auth and str(code) in {"101", "102", "103"}:
                await self.async_login()
                return await self._async_post(path, payload, retry_auth=False)
            raise KrbError(str(message))
        return result

    async def async_login(self) -> str:
        """Authenticate using current and legacy Multi Manager fields."""
        password_hash = hashlib.sha256(self._password.encode("utf-8")).hexdigest()
        # GsonBuilder.serializeNulls() is used by Multi Manager 2.8.4. Keep the
        # complete MemberModel shape so the request matches the app exactly.
        current_payload = {
            "appcode": None,
            "emailAddress": None,
            "memberRole": None,
            "mobileNumber": None,
            "newPassword": None,
            "nickname": None,
            "password": password_hash,
            "pushToken": None,
            "userIdentifier": self.username,
            "userName": None,
        }
        login_attempts = (
            ("current", current_payload),
            (
                "legacy",
                {"memberId": self.username, "password": password_hash},
            ),
        )
        last_error = "아이디 또는 비밀번호를 확인하세요"

        for scheme, payload in login_attempts:
            try:
                result = await self._async_post(
                    "member/login",
                    payload,
                    authenticated=False,
                    retry_auth=False,
                )
            except KrbConnectionError:
                raise
            except KrbError as ex:
                last_error = str(ex)
                continue

            data = result.get("data")
            nested = data if isinstance(data, dict) else {}
            auth_key = (
                result.get("authenticationKey")
                or result.get("authKey")
                or nested.get("authenticationKey")
                or nested.get("authKey")
            )
            if auth_key:
                self.auth_key = str(auth_key)
                self.login_scheme = scheme
                _LOGGER.info("Kiturami login succeeded with %s API fields", scheme)
                return self.auth_key

            last_error = str(
                result.get("responseMessage")
                or result.get("errorMessage")
                or result.get("message")
                or last_error
            )

        _LOGGER.warning(
            "Kiturami login did not return an authentication key: %s",
            last_error,
        )
        raise KrbAuthError(last_error)

    async def async_get_room_devices(self) -> list[RoomDevice]:
        """Return all room controllers registered to the account."""
        if self.login_scheme != "legacy":
            result = await self._async_post(
                "member/getMemberEachRoomDeviceList",
                {"parentCode": "1"},
            )
            devices = room_devices_from_response(result)
            if devices:
                return devices

        # Legacy multi-room accounts first return controller nodes, then expose
        # the attached rooms through getDeviceInfo for each node.
        member_result = await self._async_post(
            "member/getMemberDeviceList",
            {"parentId": "1"},
        )
        nodes = device_nodes_from_response(member_result)
        legacy_devices: list[RoomDevice] = []
        for node in nodes:
            detail = await self._async_post(
                "device/getDeviceInfo",
                {"nodeId": node.node_id, "parentId": node.parent_id},
            )
            legacy_devices.extend(legacy_room_devices_from_response(detail, node))
        return legacy_devices


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
        payload = {
            "parentId": parent_id,
            "nodeId": node_id,
            "slaveId": room_id,
            "commandId": command_id,
        }
        if self.client.login_scheme == "legacy":
            payload.pop("commandId")
            payload["actionId"] = command_id
        result = await self.client._async_post(
            "device/getDeviceModeInfo",
            payload,
        )
        return mode_info_from_response(result, room_id)

    async def async_device_control(
        self, node_id: str, action_id: str, action_data: str
    ) -> dict[str, Any]:
        payload = {
            "nodeIds": [node_id],
            "actionID": action_id,
            "actionData": action_data,
        }
        if self.client.login_scheme == "legacy":
            payload.pop("actionID")
            payload.pop("actionData")
            payload["messageId"] = action_id
            payload["messageBody"] = action_data
        return await self.client._async_post(
            "device/deviceControl",
            payload,
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
