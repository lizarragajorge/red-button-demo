"""Durable at-least-once execution with conservative unknown-outcome handling.

Coordination intents deliberately survive an uncertain mutation. They require
operator reconciliation; expiring them would allow an unsafe blind retry.
"""

import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .commvault import CommvaultClient, CommvaultError
from .config import Settings
from .models import DelayOptions, DisableRequest, ServerList
from .storage import Conflict, Repository, StorageUnavailable

log = logging.getLogger(__name__)
TERMINAL = {"completed", "partial", "failed", "unknown"}


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class TargetResult(BaseModel):
    serverId: int
    status: Literal["pending", "running", "accepted", "failed", "unknown"] = "pending"
    success: bool | None = None
    error: str | None = None


class PublicRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    requestId: str
    mode: Literal["stub", "live"]
    status: Literal["queued", "running", "completed", "partial", "failed", "unknown"]
    submittedAt: str
    updatedAt: str
    serverIds: list[int]
    options: dict[str, int] = Field(default_factory=dict)
    results: list[TargetResult]


class RequestConflict(Exception):
    pass


class RequestNotFound(Exception):
    pass


class InvalidSchedule(Exception):
    pass


class DeliveryUncertain(Exception):
    def __init__(self, record: dict):
        self.record = record


def public_record(value: dict) -> dict:
    return PublicRequest.model_validate(value).model_dump(exclude_none=True) | {
        # success is explicitly null while pending/running/unknown.
        "results": [
            {key: val for key, val in result.model_dump().items() if key != "error" or val is not None}
            for result in PublicRequest.model_validate(value).results
        ],
    }


def request_key(request_id: str) -> str:
    return f"{UUID(request_id)}.json"


async def owned_request(repo: Repository, request_id: str, owner: str) -> dict:
    doc = await repo.read("requests", request_key(request_id))
    if not doc or doc.value["owner"] != owner:
        raise RequestNotFound()
    return public_record(doc.value)


async def submit(repo: Repository, request_id: str, owner: str, mode: str, body: DisableRequest) -> dict:
    payload = {"mode": mode, "serverIds": body.server_ids, "options": body.options.model_dump(by_alias=True, exclude_none=True)}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    now = timestamp()
    value = {
        **payload, "requestId": request_id, "owner": owner, "fingerprint": fingerprint,
        "status": "queued", "submittedAt": now, "updatedAt": now,
        "results": [{"serverId": server_id, "status": "pending", "success": None} for server_id in body.server_ids],
    }
    key = request_key(request_id)
    doc = await repo.read("requests", key)
    if doc is None:
        if body.options.enable_after_a_delay is not None and body.options.enable_after_a_delay <= time.time():
            raise InvalidSchedule()
        try:
            doc = await repo.create("requests", key, value)
        except Conflict:
            doc = await repo.read("requests", key)
    if doc:
        if doc.value["owner"] != owner:
            raise RequestNotFound() from None
        if doc.value["fingerprint"] != fingerprint:
            raise RequestConflict() from None
    else:
        raise StorageUnavailable("Request creation could not be confirmed.")
    if doc.value["status"] != "queued":
        return public_record(doc.value)
    try:
        # Re-enqueueing an existing queued record repairs a crash before send.
        await repo.enqueue(request_id)
    except StorageUnavailable:
        uncertain = doc.value
        uncertain["status"] = "unknown"
        uncertain["updatedAt"] = timestamp()
        uncertain["results"] = [
            {**result, "status": "unknown", "success": None, "error": "Queue delivery could not be confirmed; inspect this request before any new submission."}
            for result in uncertain["results"]
        ]
        try:
            await repo.replace("requests", key, uncertain, doc.etag)
        except Conflict:
            # A worker may already own it. Never overwrite its progress.
            current = await repo.read("requests", key)
            uncertain = current.value if current else uncertain
        except StorageUnavailable:
            # The response retains correlation even when recording uncertainty fails.
            pass
        raise DeliveryUncertain(public_record(uncertain)) from None
    return public_record(doc.value)


async def inventory(repo: Repository, settings: Settings, infrastructure_only: bool = False) -> dict:
    doc = await repo.read("inventory", f"{settings.mode}.json")
    if not doc or doc.value.get("data") is None:
        raise StorageUnavailable("Inventory has not been refreshed successfully.")
    value = doc.value
    data = ServerList.model_validate(value["data"]).model_dump(exclude_unset=True)
    if infrastructure_only:
        data["servers"] = [server for server in data["servers"] if server.get("isInfrastructure")]
        data["totalServers"] = len(data["servers"])
    updated = value["updatedAt"]
    stale = bool(value.get("refreshError")) or not updated or (
        datetime.now(UTC) - datetime.fromisoformat(updated)
    ).total_seconds() > settings.inventory_max_age_seconds
    return {**data, "inventory": {"updatedAt": updated, "stale": stale, "refreshError": value.get("refreshError")}}


async def refresh_inventory(repo: Repository, client: CommvaultClient, settings: Settings) -> None:
    key = f"{settings.mode}.json"
    old = await repo.read("inventory", key)
    try:
        data = await client.list_servers(0)
        value = {"data": data.model_dump(exclude_unset=True), "updatedAt": timestamp(), "refreshError": None}
    except Exception as error:
        log.warning("Inventory refresh failed: %s", type(error).__name__)
        value = dict(old.value) if old else {"data": None, "updatedAt": None}
        value["refreshError"] = "Inventory refresh failed; showing last known good data when available."
    try:
        if old:
            await repo.replace("inventory", key, value, old.etag)
        else:
            await repo.create("inventory", key, value)
    except Conflict:
        # A concurrent timer already published a newer snapshot.
        return


def finish_status(results: list[dict]) -> str:
    statuses = {result["status"] for result in results}
    if "unknown" in statuses:
        return "unknown"
    if statuses == {"accepted"}:
        return "completed"
    if "accepted" in statuses:
        return "partial"
    return "failed"


async def execute_request(repo: Repository, client: CommvaultClient, settings: Settings, request_id: str, *, poison=False) -> None:
    key = request_key(request_id)
    initial = await repo.read("requests", key)
    if not initial:
        log.warning("Queue references missing request %s", request_id)
        return
    if initial.value["status"] in TERMINAL:
        return
    # Lease contention is raised to Functions for redelivery, never acknowledged.
    async with repo.lease("requests", key) as lease:
        doc = await repo.read("requests", key)
        if not doc or doc.value["status"] in TERMINAL:
            return
        value = doc.value

        async def save():
            nonlocal doc
            value["updatedAt"] = timestamp()
            doc = await repo.replace("requests", key, value, doc.etag, lease=lease)

        gate_error = None
        if settings.execution_mode != "queued" or value["mode"] != settings.mode:
            gate_error = "Worker execution mode does not match the recorded request."
        elif value["mode"] == "live" and settings.live_operations != "true":
            gate_error = "Live backup changes are disabled by worker configuration."
        options = DelayOptions.model_validate(value["options"])
        value["status"] = "running"
        await save()
        for result in value["results"]:
            target_key = f'{value["mode"]}-{result["serverId"]}.json'
            if result["status"] in ("accepted", "failed", "unknown"):
                if result["status"] != "unknown":
                    # Recover a crash after recording a certain outcome but before
                    # releasing exclusion. Never remove another request's intent.
                    completed_intent = await repo.read("coordination", target_key)
                    if completed_intent and completed_intent.value["requestId"] == request_id:
                        await repo.delete("coordination", target_key, completed_intent.etag)
                continue
            previous_intent = await repo.read("coordination", target_key)
            if result["status"] == "running" or (
                previous_intent and previous_intent.value["requestId"] == request_id
            ):
                result.update(status="unknown", success=None, error="A prior worker stopped after durable mutation intent. Verify upstream state; automatic retry is blocked.")
                await save()
                continue
            reason = gate_error
            if poison:
                reason = "Queue retries exhausted. This target was not started."
            elif options.enable_after_a_delay is not None and options.enable_after_a_delay <= time.time():
                reason = "Re-enable time expired before execution."
            if reason:
                result.update(status="failed", success=False, error=reason)
                await save()
                continue
            try:
                intent = await repo.create("coordination", target_key, {
                    "requestId": request_id, "serverId": result["serverId"], "createdAt": timestamp(),
                })
            except Conflict:
                result.update(status="failed", success=False, error="Another operation owns this target or has an unresolved outcome. Reconcile it before submitting a new request.")
                await save()
                continue
            result.update(status="running", success=None)
            # This write must complete BEFORE any upstream mutation.
            await save()
            try:
                await client.disable_backups(result["serverId"], options)
            except CommvaultError as error:
                # Only a validated Commvault rejection proves a negative outcome.
                uncertain = error.code in ("TRANSPORT_ERROR", "HTTP_ERROR", "INVALID_RESPONSE", "UPSTREAM_ERROR")
                result.update(
                    status="unknown" if uncertain else "failed", success=None if uncertain else False,
                    error="Upstream outcome is unknown. Verify it before retrying." if uncertain else str(error),
                )
                log.warning("Mutation result request=%s server=%s code=%s", request_id, result["serverId"], error.code)
            except Exception as error:
                result.update(status="unknown", success=None, error="Upstream outcome is unknown. Verify it before retrying.")
                log.warning("Mutation raised request=%s exception=%s", request_id, type(error).__name__)
            else:
                result.update(status="accepted", success=True)
            # A crash/failure writing this outcome leaves durable running + intent.
            await save()
            if result["status"] != "unknown":
                await repo.delete("coordination", target_key, intent.etag)
        value["status"] = finish_status(value["results"])
        await save()
