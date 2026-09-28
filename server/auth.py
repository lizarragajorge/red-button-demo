import asyncio
from dataclasses import dataclass
from typing import Protocol

import jwt

from .config import Settings


class TokenRejected(Exception):
    pass


@dataclass(frozen=True)
class Actor:
    oid: str
    roles: tuple[str, ...]
    tenant_id: str


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> Actor: ...


class EntraTokenVerifier:
    def __init__(self, settings: Settings, key_client=None):
        self.settings = settings
        self.key_clients = {
            tenant_id: key_client or jwt.PyJWKClient(
                f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
                timeout=15, cache_jwk_set=True, lifespan=300,
            )
            for tenant_id in settings.trusted_tenant_ids
        }

    async def verify(self, token: str) -> Actor:
        if not self.settings.identity_configured:
            raise TokenRejected("Identity is not configured.")
        # Unverified tid only selects a preconfigured authority; it grants no access.
        unverified = jwt.decode(token, options={"verify_signature": False})
        if "tid" not in unverified:
            raise jwt.MissingRequiredClaimError("tid")
        tenant_id = unverified["tid"]
        if not isinstance(tenant_id, str) or tenant_id not in self.key_clients:
            raise TokenRejected("Tenant is not authorized for this application.")
        signing_key = await asyncio.to_thread(self.key_clients[tenant_id].get_signing_key_from_jwt, token)
        payload = jwt.decode(
            token, signing_key.key, algorithms=["RS256"],
            issuer=f"https://login.microsoftonline.com/{tenant_id}/v2.0", audience=self.settings.api_client_id,
            options={"require": ["exp", "iat", "nbf", "oid", "tid", "azp", "scp"]},
        )
        if (
            payload["tid"] != tenant_id
            or payload["azp"] != self.settings.spa_client_id
            or not isinstance(payload["oid"], str) or not payload["oid"]
            or not isinstance(payload["scp"], str)
            or "access_as_user" not in payload["scp"].split()
        ):
            raise TokenRejected("Token is not authorized for this application.")
        roles = payload.get("roles", [])
        if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
            raise TokenRejected("Invalid role claims.")
        return Actor(oid=payload["oid"], roles=tuple(roles), tenant_id=tenant_id)
