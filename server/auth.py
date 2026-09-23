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


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> Actor: ...


class EntraTokenVerifier:
    def __init__(self, settings: Settings, key_client=None):
        self.settings = settings
        self.issuer = f"https://login.microsoftonline.com/{settings.tenant_id}/v2.0"
        self.key_client = key_client or jwt.PyJWKClient(
            f"https://login.microsoftonline.com/{settings.tenant_id}/discovery/v2.0/keys",
            timeout=15,
            cache_jwk_set=True,
            lifespan=300,
        )

    async def verify(self, token: str) -> Actor:
        if not self.settings.identity_configured:
            raise TokenRejected("Identity is not configured.")
        signing_key = await asyncio.to_thread(self.key_client.get_signing_key_from_jwt, token)
        payload = jwt.decode(
            token, signing_key.key, algorithms=["RS256"],
            issuer=self.issuer, audience=self.settings.api_client_id,
            options={"require": ["exp", "iat", "nbf", "oid", "tid", "azp", "scp"]},
        )
        if (
            payload["tid"] != self.settings.tenant_id
            or payload["azp"] != self.settings.spa_client_id
            or not isinstance(payload["oid"], str) or not payload["oid"]
            or not isinstance(payload["scp"], str)
            or "access_as_user" not in payload["scp"].split()
        ):
            raise TokenRejected("Token is not authorized for this application.")
        roles = payload.get("roles", [])
        if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
            raise TokenRejected("Invalid role claims.")
        return Actor(oid=payload["oid"], roles=tuple(roles))
