import os
from collections.abc import Mapping
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class Settings(BaseModel):
    environment: Literal["development", "test", "production"] = Field("development", alias="APP_ENV")
    port: int = Field(8080, alias="PORT", ge=1, le=65535)
    public_origin: str = Field("http://localhost:5173", alias="PUBLIC_ORIGIN")
    display_name: str = Field("Red Button", alias="APP_DISPLAY_NAME", min_length=1, max_length=60)
    support_url: str = Field("", alias="SUPPORT_URL", max_length=2048)
    tenant_id: str = Field("", alias="ENTRA_TENANT_ID")
    multi_tenant: Literal["true", "false"] = Field("false", alias="ENTRA_MULTI_TENANT")
    allowed_tenant_ids: tuple[str, ...] = Field((), alias="ENTRA_ALLOWED_TENANT_IDS")
    api_client_id: str = Field("", alias="ENTRA_API_CLIENT_ID")
    spa_client_id: str = Field("", alias="ENTRA_SPA_CLIENT_ID")
    mode: Literal["stub", "live"] = Field("stub", alias="COMMVAULT_MODE")
    demo_operations: Literal["true", "false"] = Field("true", alias="ALLOW_SIGNED_IN_DEMO_OPERATIONS")
    live_operations: Literal["true", "false"] = Field("false", alias="ENABLE_LIVE_OPERATIONS")
    commvault_base_url: str = Field("", alias="COMMVAULT_BASE_URL")
    commvault_auth_header: Literal["Authorization", "Authtoken"] = Field("Authorization", alias="COMMVAULT_AUTH_HEADER")
    commvault_auth_value: str = Field("", alias="COMMVAULT_AUTH_VALUE", repr=False)
    execution_mode: Literal["sync", "queued"] = Field("sync", alias="EXECUTION_MODE")
    storage_account_name: str = Field("", alias="STORAGE_ACCOUNT_NAME", pattern=r"^$|^[a-z0-9]{3,24}$")
    storage_connection_string: str = Field("", alias="AZURE_STORAGE_CONNECTION_STRING", repr=False)
    inventory_max_age_seconds: int = Field(900, alias="INVENTORY_MAX_AGE_SECONDS", ge=1)
    inventory_refresh_schedule: str = Field("0 */5 * * * *", alias="INVENTORY_REFRESH_SCHEDULE")

    @field_validator("allowed_tenant_ids", mode="before")
    @classmethod
    def parse_allowed_tenants(cls, value):
        if isinstance(value, str):
            value = [] if not value.strip() else value.split(",")
        if not isinstance(value, (list, tuple)) or len(value) > 20:
            raise ValueError("Provide at most 20 additional Entra tenant GUIDs.")
        tenants = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Allowed tenants must be GUIDs.")
            normalized = str(UUID(item.strip()))
            if item.strip().lower() != normalized or normalized == "9188040d-6c67-4c5b-b112-36a304b66dad":
                raise ValueError("Only explicit organizational tenant GUIDs are allowed.")
            tenants.append(normalized)
        if len(set(tenants)) != len(tenants):
            raise ValueError("Allowed tenant GUIDs must be unique.")
        return tuple(tenants)

    @property
    def trusted_tenant_ids(self) -> frozenset[str]:
        return frozenset(
            ([self.tenant_id] if self.tenant_id else [])
            + (list(self.allowed_tenant_ids) if self.multi_tenant == "true" else [])
        )

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value or not value.isprintable():
            raise ValueError("APP_DISPLAY_NAME must be printable, nonblank text.")
        return value

    @field_validator("support_url")
    @classmethod
    def validate_support_url(cls, value: str) -> str:
        if not value:
            return value
        url = urlsplit(value)
        if (
            url.scheme != "https" or not url.hostname or url.username or url.password
            or any(character.isspace() or not character.isprintable() for character in value)
            or "\\" in value
        ):
            raise ValueError("SUPPORT_URL must be an HTTPS URL without credentials or whitespace.")
        _ = url.port
        return value

    @property
    def identity_configured(self) -> bool:
        return bool(self.tenant_id and self.api_client_id and self.spa_client_id)

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.storage_connection_string:
            if self.environment == "production":
                raise ValueError("Production storage requires managed identity.")
            # Connection strings are only for a loopback emulator, never account keys in Azure.
            if self.storage_connection_string != "UseDevelopmentStorage=true":
                parts = dict(part.split("=", 1) for part in self.storage_connection_string.split(";") if "=" in part)
                if any(
                    urlsplit(parts.get(name, "")).hostname not in ("localhost", "127.0.0.1", "::1")
                    for name in ("BlobEndpoint", "QueueEndpoint")
                ) or parts.get("DefaultEndpointsProtocol", "http") not in ("http", "https"):
                    raise ValueError("Storage connection strings are restricted to a local emulator.")
        for value in (self.tenant_id, self.api_client_id, self.spa_client_id):
            if value:
                UUID(value)
        if self.tenant_id:
            self.tenant_id = str(UUID(self.tenant_id))
            if self.tenant_id == "9188040d-6c67-4c5b-b112-36a304b66dad":
                raise ValueError("The home tenant must be an organizational tenant.")
        if self.multi_tenant == "true":
            if not self.identity_configured or not set(self.allowed_tenant_ids).difference({self.tenant_id}):
                raise ValueError("Multi-tenant access requires configured identity and an explicit additional tenant.")
        elif self.allowed_tenant_ids:
            raise ValueError("Additional tenants require ENTRA_MULTI_TENANT=true.")
        origin = urlsplit(self.public_origin)
        local_http = origin.scheme == "http" and origin.hostname == "localhost"
        if (
            not origin.hostname or origin.username or origin.password
            or origin.path or origin.query or origin.fragment
            or not (origin.scheme == "https" or local_http)
        ):
            raise ValueError("PUBLIC_ORIGIN must be an HTTPS origin or http://localhost, without a trailing slash.")
        if self.environment == "production" and not self.identity_configured:
            raise ValueError("Production requires all three ENTRA_* identity settings.")
        if self.mode == "live":
            upstream = urlsplit(self.commvault_base_url)
            if (
                upstream.scheme != "https" or not upstream.hostname
                or upstream.username or upstream.password or upstream.query or upstream.fragment
            ):
                raise ValueError("Live mode requires an HTTPS Commvault URL without credentials, query or fragment.")
            if (
                not self.identity_configured or not self.commvault_auth_value.strip()
                or "\r" in self.commvault_auth_value or "\n" in self.commvault_auth_value
                or self.commvault_auth_value.startswith("@Microsoft.KeyVault(")
            ):
                raise ValueError("Live mode requires Entra settings and a resolved Commvault credential.")
        return self

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None):
        try:
            return cls.model_validate(dict(os.environ if env is None else env))
        except (ValidationError, ValueError):
            # Pydantic's default exception text includes input values, possibly secrets.
            raise ValueError("Invalid application configuration. Check .env.example and the deployment settings.") from None
