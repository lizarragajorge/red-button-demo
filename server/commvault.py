from typing import TypeVar

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from .models import ActionResult, DelayOptions, ServerId, ServerList

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class CommvaultError(Exception):
    def __init__(self, message: str, code: str = "UPSTREAM_ERROR"):
        super().__init__(message)
        self.code = code


class CommvaultClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str, auth_header: str, auth_value: str):
        self.http = http
        self.base_url = base_url.rstrip("/") + "/"
        self.auth_header = auth_header
        self.auth_value = auth_value

    async def request(
        self, path: str, method: str, schema: type[ResponseModel], query: dict[str, int] | None = None,
    ) -> ResponseModel:
        # Relative endpoint paths retain customer-managed prefixes such as /commandcenter/api/.
        url = self.base_url + path
        try:
            response = await self.http.request(
                method, url, params=query,
                headers={"Accept": "application/json", self.auth_header: self.auth_value},
                follow_redirects=False, timeout=15,
            )
        except httpx.RequestError:
            raise CommvaultError(
                "Commvault request failed or timed out. The outcome may be unknown; check before retrying.",
                "TRANSPORT_ERROR",
            ) from None
        if not response.is_success:
            raise CommvaultError(f"Commvault returned HTTP {response.status_code}.", "HTTP_ERROR")
        try:
            return schema.model_validate(response.json())
        except (ValueError, ValidationError):
            raise CommvaultError(
                "Commvault response does not match the expected JSON API contract.", "INVALID_RESPONSE",
            ) from None

    async def list_servers(self, infrastructure_only: int = 0) -> ServerList:
        return await self.request(
            "V4/Servers", "GET", ServerList,
            {"showOnlyInfrastructureMachines": infrastructure_only},
        )

    async def disable_backups(self, server_id: int, options: DelayOptions | None = None) -> ActionResult:
        valid_id = TypeAdapter(ServerId).validate_python(server_id)
        query = (options or DelayOptions()).model_dump(by_alias=True, exclude_none=True)
        result = await self.request(
            f"V4/Server/{valid_id}/Backup/Action/Disable", "PUT", ActionResult, query,
        )
        if result.errorCode != 0:
            raise CommvaultError(
                f"Commvault rejected the operation (errorCode {result.errorCode}).", str(result.errorCode),
            )
        return result
