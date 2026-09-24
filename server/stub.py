import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from .models import DelayOptions
from .queries import query_int, strict_query
from .storage import Conflict, Repository

SEEDS = (
    {"id": 101, "name": "demo-commserve", "displayName": "Demo CommServe", "hostName": "commserve.demo.invalid", "OS": "Windows Server 2022", "isInfrastructure": True, "isCommServer": True},
    {"id": 102, "name": "demo-finance", "displayName": "Finance files", "hostName": "finance.demo.invalid", "OS": "Windows Server 2022", "isInfrastructure": False, "isCommServer": False},
    {"id": 103, "name": "demo-linux", "displayName": "Application server", "hostName": "app.demo.invalid", "OS": "Ubuntu 24.04", "isInfrastructure": False, "isCommServer": False},
)


@dataclass
class BackupState:
    disabled: bool = False
    enable_at: int | None = None


class StubStore:
    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.states = {server["id"]: BackupState() for server in SEEDS}

    def get_state(self, server_id: int) -> BackupState | None:
        state = self.states.get(server_id)
        if state is None:
            return None
        if state.disabled and state.enable_at is not None and self.clock() >= state.enable_at:
            state.disabled = False
            state.enable_at = None
        return replace(state)


def create_stub(
    auth_value: str, auth_header: str = "Authorization", store: StubStore | None = None,
    repository: Repository | None = None,
) -> FastAPI:
    store = store or StubStore()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    def failure(status: int, message: str):
        return JSONResponse({"errorCode": 1, "errorMessage": message}, status_code=status)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        supplied = request.headers.get(auth_header, "").encode()
        if not auth_value or not secrets.compare_digest(supplied, auth_value.encode()):
            return failure(401, "Invalid stub credential.")
        return await call_next(request)

    @app.get("/V4/Servers")
    async def list_servers(request: Request):
        try:
            query = strict_query(request.query_params, {"showOnlyInfrastructureMachines"})
            flag = query.get("showOnlyInfrastructureMachines", "1")
            if flag not in ("0", "1"):
                raise ValueError("Invalid filter.")
        except ValueError:
            return failure(400, "showOnlyInfrastructureMachines must be 0 or 1.")
        servers = [
            {**server, "configured": True, "networkReadiness": "ONLINE", "version": "11.46.0"}
            for server in SEEDS if flag == "0" or server["isInfrastructure"]
        ]
        if repository is not None:
            for server in servers:
                doc = await repository.read("stub-state", f'{server["id"]}.json')
                state = doc.value if doc else {}
                enable_at = state.get("enableAt")
                server["stubBackupDisabled"] = bool(state.get("disabled")) and (
                    enable_at is None or store.clock() < enable_at
                )
                server["stubEnableAt"] = enable_at if server["stubBackupDisabled"] else None
        return {"totalServers": len(servers), "servers": servers}

    @app.put("/V4/Server/{server_id}/Backup/Action/Disable")
    async def disable_backups(server_id: str, request: Request):
        try:
            parsed_id = query_int(server_id)
            if parsed_id == 0:
                raise ValueError("Invalid ID.")
            raw = strict_query(request.query_params, {"enableAfterADelay", "enableAfterDelayTimeZone"})
            options = DelayOptions.model_validate({key: query_int(value) for key, value in raw.items()})
        except (ValueError, ValidationError):
            return failure(400, "Invalid serverId or re-enable query parameters.")
        if parsed_id not in store.states:
            return failure(404, "Server not found.")
        if options.enable_after_a_delay is not None and options.enable_after_a_delay <= store.clock():
            return failure(400, "Re-enable timestamp must be in the future.")
        if repository is not None:
            key = f"{parsed_id}.json"
            doc = await repository.read("stub-state", key)
            value = {"disabled": True, "enableAt": options.enable_after_a_delay}
            try:
                if doc:
                    await repository.replace("stub-state", key, value, doc.etag)
                else:
                    await repository.create("stub-state", key, value)
            except Conflict:
                return failure(409, "Concurrent simulated backup update.")
        else:
            store.states[parsed_id] = BackupState(disabled=True, enable_at=options.enable_after_a_delay)
        return {"errorCode": 0, "errorMessage": ""}

    @app.exception_handler(404)
    async def not_found(request: Request, error):
        return failure(404, "Stub endpoint not found.")

    return app
