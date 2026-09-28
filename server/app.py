import json
import re
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import Actor, EntraTokenVerifier, TokenRejected, TokenVerifier, can_disable
from .commvault import CommvaultClient, CommvaultError
from .config import Settings
from .middleware import BodyLimitMiddleware
from .models import DisableRequest
from .queries import strict_query
from .execution import DeliveryUncertain, InvalidSchedule, RequestConflict, RequestNotFound, inventory, owned_request, submit
from .runtime import upstream_client
from .storage import AzureRepository, Repository, StorageUnavailable

DIST = Path(__file__).resolve().parent.parent / "dist"


def write_audit(entry: dict):
    print(json.dumps({"time": datetime.now(UTC).isoformat(), **entry}), flush=True)


def create_app(
    settings: Settings,
    client: CommvaultClient | None = None,
    verifier: TokenVerifier | None = None,
    audit: Callable[[dict], None] = write_audit,
    repository: Repository | None = None,
) -> FastAPI:
    verifier = verifier or EntraTokenVerifier(settings)
    active_servers: set[int] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repo = repository
        if settings.execution_mode == "queued" and repo is None:
            repo = AzureRepository(settings)
        app.state.repository = repo
        try:
            if client is not None:
                app.state.client = client
                yield
            else:
                async with upstream_client(settings, repo) as upstream:
                    app.state.client = upstream
                    audit({"event": "started", "mode": settings.mode, "executionMode": settings.execution_mode, "identityConfigured": settings.identity_configured})
                    if not settings.identity_configured:
                        audit({"event": "identity_configuration_required", "message": "Protected APIs are unavailable; configure ENTRA_* settings."})
                    yield
        finally:
            if repo is not None and repository is None:
                await repo.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimitMiddleware)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        silent_callback = request.url.path == "/auth/silent" and request.method == "GET" and response.status_code == 200
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN" if silent_callback else "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        csp = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self' https://login.microsoftonline.com; "
            "frame-src 'self' https://login.microsoftonline.com; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if silent_callback:
            csp = "default-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'none'"
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            csp += "; upgrade-insecure-requests"
        response.headers["Content-Security-Policy"] = csp
        if request.url.path.startswith("/api") or request.url.path == "/" or silent_callback:
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

    @app.exception_handler(StorageUnavailable)
    async def storage_error(request: Request, error: StorageUnavailable):
        audit({"event": "storage_unavailable", "requestId": request.state.request_id})
        return JSONResponse({"error": str(error), "requestId": request.state.request_id}, status_code=503)

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

    @app.get("/auth/silent", response_class=HTMLResponse)
    async def silent_sign_in():
        # MSAL's parent window consumes the fragment; no app/router runs in this iframe.
        return '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Microsoft sign-in callback</title></head><body></body></html>'

    @app.get("/api/config")
    async def public_config():
        return {
            "displayName": settings.display_name,
            "supportUrl": settings.support_url,
            "mode": settings.mode,
            "executionMode": settings.execution_mode,
            "liveOperationsEnabled": settings.live_operations == "true",
            "signedInDemoOperations": settings.mode == "stub" and settings.demo_operations == "true",
            "identityConfigured": settings.identity_configured,
            "tenantId": settings.tenant_id,
            "multiTenant": settings.multi_tenant == "true",
            "allowedTenantIds": sorted(settings.trusted_tenant_ids),
            "clientId": settings.spa_client_id,
            "scope": f"api://{settings.api_client_id}/access_as_user",
            "redirectUri": settings.public_origin + "/",
            "silentRedirectUri": settings.public_origin + "/auth/silent",
        }

    @app.get("/api/me")
    async def me(actor: Actor = Depends(authenticate)):
        return {"canDisable": can_disable(actor, settings)}

    @app.get("/api/servers")
    async def list_servers(request: Request, actor: Actor = Depends(authenticate)):
        try:
            query = strict_query(request.query_params, {"showOnlyInfrastructureMachines"})
            flag = query.get("showOnlyInfrastructureMachines", "0")
            if flag not in ("0", "1"):
                raise ValueError("Invalid filter.")
        except ValueError:
            raise HTTPException(400, "Invalid server filter.") from None
        if settings.execution_mode == "queued":
            return await inventory(request.app.state.repository, settings, flag == "1")
        data = await request.app.state.client.list_servers(int(flag))
        return data.model_dump(exclude_unset=True)

    @app.get("/api/requests/{request_id}")
    async def get_request(request_id: str, request: Request, actor: Actor = Depends(authenticate)):
        if settings.execution_mode != "queued":
            raise HTTPException(404, "Request not found.")
        try:
            return await owned_request(
                request.app.state.repository, str(UUID(request_id)), f"{actor.tenant_id}:{actor.oid}",
            )
        except (ValueError, RequestNotFound):
            raise HTTPException(404, "Request not found.") from None

    @app.post("/api/disable")
    async def disable_backups(body: DisableRequest, request: Request, actor: Actor = Depends(authenticate)):
        if not can_disable(actor, settings):
            if "BackupOperator" not in actor.roles:
                raise HTTPException(403, "BackupOperator role is required.")
            raise HTTPException(403, "Live backup changes are disabled by configuration.")
        if settings.execution_mode == "sync" and body.options.enable_after_a_delay is not None and body.options.enable_after_a_delay <= time.time():
            raise HTTPException(400, "Re-enable time must be in the future.")
        if settings.execution_mode == "queued":
            try:
                keys = request.headers.getlist("idempotency-key")
                if len(keys) > 1:
                    raise ValueError()
                request_id = str(UUID(keys[0])) if keys else str(uuid4())
            except ValueError:
                raise HTTPException(400, "Idempotency-Key must be one UUID.") from None
            request.state.request_id = request_id
            try:
                record = await submit(
                    request.app.state.repository, request_id, f"{actor.tenant_id}:{actor.oid}",
                    settings.mode, body,
                )
            except RequestNotFound:
                raise HTTPException(404, "Request not found.") from None
            except RequestConflict:
                raise HTTPException(409, "Idempotency-Key already identifies different request content.") from None
            except InvalidSchedule:
                raise HTTPException(400, "Re-enable time must be in the future.") from None
            except DeliveryUncertain as error:
                audit({"event": "enqueue_uncertain", "requestId": request_id, "actorId": actor.oid, "actorTenantId": actor.tenant_id})
                return JSONResponse({
                    "error": "Queue delivery could not be confirmed. Inspect this request before submitting again.",
                    "requestId": request_id, "request": error.record,
                }, status_code=503, headers={"Location": f"/api/requests/{request_id}"})
            audit({"event": "disable_queued", "requestId": request_id, "actorId": actor.oid, "actorTenantId": actor.tenant_id, "mode": settings.mode})
            return JSONResponse(record, status_code=202, headers={"Location": f"/api/requests/{request_id}"})
        if active_servers.intersection(body.server_ids):
            raise HTTPException(409, "An operation is already running for a selected server. Check its result before retrying.")
        active_servers.update(body.server_ids)
        results = []
        metadata = {"requestId": request.state.request_id, "actorId": actor.oid, "actorTenantId": actor.tenant_id, "mode": settings.mode}
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
