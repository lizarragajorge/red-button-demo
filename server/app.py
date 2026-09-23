import json
import re
import secrets
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import Actor, EntraTokenVerifier, TokenRejected, TokenVerifier
from .commvault import CommvaultClient, CommvaultError
from .config import Settings
from .middleware import BodyLimitMiddleware
from .models import DisableRequest
from .queries import strict_query
from .stub import create_stub

DIST = Path(__file__).resolve().parent.parent / "dist"


def write_audit(entry: dict):
    print(json.dumps({"time": datetime.now(UTC).isoformat(), **entry}), flush=True)


def create_app(
    settings: Settings,
    client: CommvaultClient | None = None,
    verifier: TokenVerifier | None = None,
    audit: Callable[[dict], None] = write_audit,
) -> FastAPI:
    verifier = verifier or EntraTokenVerifier(settings)
    active_servers: set[int] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if client is not None:
            app.state.client = client
            yield
            return
        auth_value = settings.commvault_auth_value
        base_url = settings.commvault_base_url
        transport = None
        if settings.mode == "stub":
            auth_value = secrets.token_urlsafe(32)
            stub = create_stub(auth_value, settings.commvault_auth_header)
            transport = httpx.ASGITransport(app=stub)
            base_url = "http://commvault-stub.internal"
        async with httpx.AsyncClient(transport=transport) as http:
            app.state.client = CommvaultClient(http, base_url, settings.commvault_auth_header, auth_value)
            audit({"event": "started", "mode": settings.mode, "identityConfigured": settings.identity_configured})
            if not settings.identity_configured:
                audit({"event": "identity_configuration_required", "message": "Protected APIs are unavailable; configure ENTRA_* settings."})
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimitMiddleware)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        csp = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self' https://login.microsoftonline.com; "
            "frame-src https://login.microsoftonline.com; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            csp += "; upgrade-insecure-requests"
        response.headers["Content-Security-Policy"] = csp
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    async def authenticate(request: Request) -> Actor:
        if not settings.identity_configured:
            raise HTTPException(503, "Entra sign-in is not configured. Set the ENTRA_* settings.")
        match = re.fullmatch(r"Bearer (\S+)", request.headers.get("authorization", ""), flags=re.IGNORECASE)
        if not match:
            raise HTTPException(401, "A bearer access token is required.")
        try:
            return await verifier.verify(match[1])
        except jwt.PyJWKClientConnectionError:
            audit({"event": "signing_keys_unavailable", "requestId": request.state.request_id})
            raise HTTPException(503, "Entra signing keys are unavailable. Try again later.") from None
        except (jwt.PyJWTError, TokenRejected):
            audit({"event": "authentication_rejected", "requestId": request.state.request_id})
            raise HTTPException(401, "Access token is invalid, expired, or not authorized for this API.") from None

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException):
        return JSONResponse({"error": error.detail, "requestId": request.state.request_id}, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        return JSONResponse({
            "error": "Select 1-50 unique servers, type DISABLE BACKUPS, and supply a valid JSON request with re-enable options.",
            "requestId": request.state.request_id,
        }, status_code=400)

    @app.exception_handler(CommvaultError)
    async def upstream_error(request: Request, error: CommvaultError):
        audit({"event": "request_failed", "requestId": request.state.request_id, "code": error.code})
        return JSONResponse({"error": str(error), "requestId": request.state.request_id}, status_code=502)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        request_id = getattr(request.state, "request_id", str(uuid4()))
        audit({"event": "request_failed", "requestId": request_id, "code": "INTERNAL_ERROR", "exceptionType": type(error).__name__})
        return JSONResponse({
            "error": "Unexpected server error. Consult the audit logs.",
            "requestId": request_id,
        }, status_code=500, headers={"Cache-Control": "no-store", "X-Request-Id": request_id})

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/config")
    async def public_config():
        return {
            "displayName": settings.display_name,
            "supportUrl": settings.support_url,
            "mode": settings.mode,
            "liveOperationsEnabled": settings.live_operations == "true",
            "identityConfigured": settings.identity_configured,
            "tenantId": settings.tenant_id,
            "clientId": settings.spa_client_id,
            "scope": f"api://{settings.api_client_id}/access_as_user",
            "redirectUri": settings.public_origin + "/",
        }

    @app.get("/api/me")
    async def me(actor: Actor = Depends(authenticate)):
        return {"canDisable": "BackupOperator" in actor.roles and (settings.mode == "stub" or settings.live_operations == "true")}

    @app.get("/api/servers")
    async def list_servers(request: Request, actor: Actor = Depends(authenticate)):
        try:
            query = strict_query(request.query_params, {"showOnlyInfrastructureMachines"})
            flag = query.get("showOnlyInfrastructureMachines", "0")
            if flag not in ("0", "1"):
                raise ValueError("Invalid filter.")
        except ValueError:
            raise HTTPException(400, "Invalid server filter.") from None
        data = await request.app.state.client.list_servers(int(flag))
        return data.model_dump(exclude_unset=True)

    @app.post("/api/disable")
    async def disable_backups(body: DisableRequest, request: Request, actor: Actor = Depends(authenticate)):
        if "BackupOperator" not in actor.roles:
            raise HTTPException(403, "BackupOperator role is required.")
        if settings.mode == "live" and settings.live_operations != "true":
            raise HTTPException(403, "Live backup changes are disabled by configuration.")
        if body.options.enable_after_a_delay is not None and body.options.enable_after_a_delay <= time.time():
            raise HTTPException(400, "Re-enable time must be in the future.")
        if active_servers.intersection(body.server_ids):
            raise HTTPException(409, "An operation is already running for a selected server. Check its result before retrying.")
        active_servers.update(body.server_ids)
        results = []
        metadata = {"requestId": request.state.request_id, "actorId": actor.oid, "mode": settings.mode}
        try:
            audit({"event": "disable_requested", **metadata, "serverIds": body.server_ids, "options": body.options.model_dump(by_alias=True, exclude_none=True)})
            for server_id in body.server_ids:
                try:
                    await request.app.state.client.disable_backups(server_id, body.options)
                    results.append({"serverId": server_id, "success": True})
                    audit({"event": "disable_succeeded", **metadata, "serverId": server_id})
                except CommvaultError as error:
                    results.append({"serverId": server_id, "success": False, "error": str(error)})
                    audit({"event": "disable_failed", **metadata, "serverId": server_id, "code": error.code})
        finally:
            active_servers.difference_update(body.server_ids)
        return JSONResponse(
            {"requestId": request.state.request_id, "results": results},
            status_code=200 if all(result["success"] for result in results) else 207,
        )

    @app.get("/")
    async def index():
        path = DIST / "index.html"
        if not path.is_file():
            raise HTTPException(404, "Web app is not built. Run npm run build.")
        return FileResponse(path)

    app.mount("/assets", StaticFiles(directory=DIST / "assets", check_dir=False), name="assets")
    return app
