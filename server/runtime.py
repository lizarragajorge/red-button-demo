"""Shared API/Functions upstream lifecycle; the stub is internal-only."""

import secrets
from contextlib import asynccontextmanager

import httpx

from .commvault import CommvaultClient
from .config import Settings
from .storage import Repository
from .stub import create_stub


@asynccontextmanager
async def upstream_client(settings: Settings, repository: Repository | None = None):
    auth_value = settings.commvault_auth_value
    base_url = settings.commvault_base_url
    transport = None
    if settings.mode == "stub":
        auth_value = secrets.token_urlsafe(32)
        stub = create_stub(auth_value, settings.commvault_auth_header, repository=repository)
        transport = httpx.ASGITransport(app=stub)
        base_url = "http://commvault-stub.internal"
    async with httpx.AsyncClient(transport=transport) as http:
        yield CommvaultClient(http, base_url, settings.commvault_auth_header, auth_value)
