import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from itertools import product
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

import httpx
import pytest

from server.app import create_app
from server.auth import EntraTokenVerifier
from server.commvault import CommvaultClient, CommvaultError, UPSTREAM_TOTAL_TIMEOUT_SECONDS
from server.config import Settings
from server.execution import execute_request, finish_status, inventory, owned_request, refresh_inventory, submit
from server.models import ActionResult, DisableRequest, ServerList
from server.runtime import upstream_client
from server.storage import AzureRepository, Conflict, MemoryRepository, StorageUnavailable, REQUEST_LEASE_RENEWAL_SECONDS
from test_app import IDENTITY, LocalKeys, disable, private_key, token

CONFIG = Settings.from_env({
    **IDENTITY, "APP_ENV": "test", "EXECUTION_MODE": "queued", "ALLOW_SIGNED_IN_DEMO_OPERATIONS": "false",
})


class Client:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def list_servers(self, flag=0):
        if self.error:
            raise self.error
        return ServerList(totalServers=2, servers=[
            {"id": 102, "name": "finance", "isInfrastructure": False},
            {"id": 101, "name": "commserve", "isInfrastructure": True},
        ])

    async def disable_backups(self, server_id, options):
        self.calls.append(server_id)
        if self.error:
            raise self.error
        return ActionResult(errorCode=0)


@asynccontextmanager
async def api(private_key, repo=None, settings=CONFIG):
    repo = repo or MemoryRepository()
    app = create_app(
        settings, Client(), EntraTokenVerifier(settings, LocalKeys(private_key)),
        lambda entry: None, repository=repo,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://api.test",
            headers={"Authorization": f"Bearer {token(private_key)}"},
        ) as http:
            yield http, repo


async def seed(repo, server_ids=None, options=None, mode="stub"):
    request_id = str(uuid4())
    await submit(repo, request_id, "owner", mode, DisableRequest.model_validate(disable(server_ids, options)))
    return request_id


async def record(repo, request_id):
    return (await repo.read("requests", f"{request_id}.json")).value


async def test_queued_api_auth_cache_and_owner_idempotency(private_key):
    async with api(private_key) as (http, repo):
        assert (await http.get("/api/config")).json()["executionMode"] == "queued"
        assert (await http.get("/api/servers")).status_code == 503
        await refresh_inventory(repo, Client(), CONFIG)
        response = await http.get("/api/servers")
        assert response.json()["inventory"] == {
            "updatedAt": (await repo.read("inventory", "stub.json")).value["updatedAt"],
            "stale": False, "refreshError": None,
        }
        assert (await http.get("/api/servers?showOnlyInfrastructureMachines=1")).json()["totalServers"] == 1
        key = str(uuid4())
        headers = {"Idempotency-Key": key}
        first = await http.post("/api/disable", json=disable(), headers=headers)
        assert first.status_code == 202
        assert first.headers["location"] == f"/api/requests/{key}"
        data = first.json()
        assert set(data) == {"requestId", "mode", "status", "submittedAt", "updatedAt", "serverIds", "options", "results"}
        assert data["mode"] == "stub" and data["status"] == "queued"
        assert all(result["status"] == "pending" for result in data["results"])
        for field in ("submittedAt", "updatedAt"):
            assert isinstance(data[field], str)
            assert datetime.fromisoformat(data[field]).utcoffset() == timedelta(0)
        assert data["results"] == [{"serverId": 102, "status": "pending", "success": None}]
        assert (await http.post("/api/disable", json=disable(), headers=headers)).json() == data
        assert (await http.post("/api/disable", json=disable([103]), headers=headers)).status_code == 409
        foreign = {"Authorization": f"Bearer {token(private_key, {'oid': 'other'})}", **headers}
        assert (await http.get(f"/api/requests/{key}", headers=foreign)).status_code == 404
        assert (await http.post("/api/disable", json=disable(), headers=foreign)).status_code == 404
        assert (await http.get(f"/api/requests/{key}")).json() == data
        assert (await http.get("/api/requests/not-a-uuid")).status_code == 404
        assert (await http.post("/api/disable", json=disable(), headers={"Idempotency-Key": "bad"})).status_code == 400
        denied = {"Authorization": f"Bearer {token(private_key, {'roles': []})}"}
        assert (await http.post("/api/disable", json=disable(), headers=denied)).status_code == 403
        assert (await http.get(f"/api/requests/{key}", headers={"Authorization": ""})).status_code == 401
        generated = await http.post("/api/disable", json=disable())
        assert generated.status_code == 202 and generated.json()["requestId"] != key
        await execute_request(repo, Client(), CONFIG, key)
        replay = await http.post("/api/disable", json=disable(), headers=headers)
        assert replay.status_code == 202 and replay.json()["status"] == "completed"


async def test_enqueue_uncertainty_never_returns_accepted_and_is_correlated(private_key):
    repo = MemoryRepository()
    repo.enqueue_failure = True
    async with api(private_key, repo) as (http, _):
        key = str(uuid4())
        response = await http.post("/api/disable", json=disable(), headers={"Idempotency-Key": key})
        assert response.status_code == 503
        assert response.json()["requestId"] == response.headers["x-request-id"] == key
        assert response.json()["request"]["status"] == "unknown"
        assert (await http.get(f"/api/requests/{key}")).json()["status"] == "unknown"
        client = Client()
        await execute_request(repo, client, CONFIG, key)
        assert client.calls == []


async def test_cache_failure_preserves_last_good_and_stale_age():
    repo = MemoryRepository()
    with pytest.raises(StorageUnavailable):
        await inventory(repo, CONFIG)
    await refresh_inventory(repo, Client(CommvaultError("private upstream detail")), CONFIG)
    with pytest.raises(StorageUnavailable):
        await inventory(repo, CONFIG)
    await refresh_inventory(repo, Client(), CONFIG)
    old = await repo.read("inventory", "stub.json")
    old.value["updatedAt"] = (datetime.now(UTC) - timedelta(seconds=901)).isoformat()
    await repo.replace("inventory", "stub.json", old.value, old.etag)
    assert (await inventory(repo, CONFIG))["inventory"]["stale"]
    await refresh_inventory(repo, Client(RuntimeError("credential-secret")), CONFIG)
    response = await inventory(repo, CONFIG)
    assert response["servers"] == old.value["data"]["servers"]
    assert response["inventory"]["refreshError"]
    assert "credential-secret" not in json.dumps(response)
    await refresh_inventory(repo, Client(), CONFIG)
    assert not (await inventory(repo, CONFIG))["inventory"]["stale"]


async def test_terminal_replay_is_noop_and_partial_has_precise_results():
    for count in (1, 2, 3):
        for statuses in product(("accepted", "failed", "unknown"), repeat=count):
            expected = (
                "unknown" if "unknown" in statuses else
                "completed" if all(status == "accepted" for status in statuses) else
                "partial" if "accepted" in statuses else "failed"
            )
            assert finish_status([{"status": status} for status in statuses]) == expected

    class PartialClient(Client):
        async def disable_backups(self, server_id, options):
            self.calls.append(server_id)
            if server_id == 103:
                raise CommvaultError("Commvault rejected the operation (errorCode 5).", "5")
            return ActionResult(errorCode=0)

    repo, client = MemoryRepository(), PartialClient()
    key = await seed(repo, [102, 103])
    await execute_request(repo, client, CONFIG, key)
    await execute_request(repo, client, CONFIG, key)
    value = await record(repo, key)
    assert value["status"] == "partial"
    assert [result["status"] for result in value["results"]] == ["accepted", "failed"]
    assert client.calls == [102, 103]
    assert not await repo.read("coordination", "stub-102.json")


@pytest.mark.parametrize("failure_stage", ["intent", "outcome"])
async def test_crash_recovery_never_retries_a_possible_mutation(failure_stage):
    class CrashRepository(MemoryRepository):
        crash = True

        async def replace(self, container, key, value, etag, lease=None):
            if container == "requests" and self.crash:
                status = value["results"][0]["status"]
                if status == ("running" if failure_stage == "intent" else "accepted"):
                    self.crash = False
                    raise StorageUnavailable("Injected crash")
            return await super().replace(container, key, value, etag, lease)

    repo, client = CrashRepository(), Client()
    key = await seed(repo)
    with pytest.raises(StorageUnavailable):
        await execute_request(repo, client, CONFIG, key)
    assert client.calls == ([] if failure_stage == "intent" else [102])
    await execute_request(repo, client, CONFIG, key)
    await execute_request(repo, client, CONFIG, key)
    assert (await record(repo, key))["status"] == "unknown"
    assert client.calls == ([] if failure_stage == "intent" else [102])
    another = await seed(repo)
    await execute_request(repo, client, CONFIG, another)
    assert (await record(repo, another))["status"] == "failed"
    assert (await repo.read("coordination", "stub-102.json")).value["requestId"] == key


async def test_distributed_overlap_and_duplicate_deliveries():
    started, release = asyncio.Event(), asyncio.Event()

    class SlowClient(Client):
        async def disable_backups(self, server_id, options):
            self.calls.append(server_id)
            started.set()
            await release.wait()
            return ActionResult(errorCode=0)

    repo, client = MemoryRepository(), SlowClient()
    first, second = await seed(repo), await seed(repo)
    task = asyncio.create_task(execute_request(repo, client, CONFIG, first))
    await started.wait()
    try:
        with pytest.raises(Conflict):
            await execute_request(repo, client, CONFIG, first)
        await execute_request(repo, Client(), CONFIG, second)
        assert (await record(repo, second))["status"] == "failed"
    finally:
        release.set()
        await task
    await execute_request(repo, client, CONFIG, first)
    assert client.calls == [102]


async def test_expired_request_lease_cannot_authorize_a_mutation():
    class LostLeaseRepository(MemoryRepository):
        expire_once = True

        async def replace(self, container, key, value, etag, lease=None):
            if self.expire_once and container == "requests" and value["results"][0]["status"] == "running":
                self.expire_once = False
                self.leases[(container, key)] = (lease, time.monotonic() - 1)
            return await super().replace(container, key, value, etag, lease)

    repo, client = LostLeaseRepository(), Client()
    key = await seed(repo)
    with pytest.raises(Conflict):
        await execute_request(repo, client, CONFIG, key)
    assert client.calls == []
    assert await repo.read("coordination", "stub-102.json")
    await execute_request(repo, client, CONFIG, key)
    assert (await record(repo, key))["status"] == "unknown"
    assert client.calls == []


async def test_committed_outcome_with_lost_storage_response_is_recovered_without_repeat():
    class LostResponseRepository(MemoryRepository):
        lose_response = True

        async def replace(self, container, key, value, etag, lease=None):
            committed = await super().replace(container, key, value, etag, lease)
            if container == "requests" and self.lose_response and value["results"][0]["status"] == "accepted":
                self.lose_response = False
                raise StorageUnavailable("Response lost after committed write")
            return committed

    repo, client = LostResponseRepository(), Client()
    key = await seed(repo)
    with pytest.raises(StorageUnavailable):
        await execute_request(repo, client, CONFIG, key)
    assert await repo.read("coordination", "stub-102.json")
    await execute_request(repo, client, CONFIG, key)
    assert client.calls == [102]
    assert (await record(repo, key))["status"] == "completed"
    assert not await repo.read("coordination", "stub-102.json")


async def test_enqueue_error_after_delivery_does_not_overwrite_worker_progress():
    class ConcurrentDeliveryRepository(MemoryRepository):
        client = Client()

        async def enqueue(self, request_id):
            await execute_request(self, self.client, CONFIG, request_id)
            raise StorageUnavailable("Queue response lost")

    from server.execution import DeliveryUncertain
    repo = ConcurrentDeliveryRepository()
    key = str(uuid4())
    with pytest.raises(DeliveryUncertain) as failure:
        await submit(repo, key, "owner", "stub", DisableRequest.model_validate(disable()))
    assert failure.value.record["status"] == "completed"
    assert (await record(repo, key))["status"] == "completed"
    assert repo.client.calls == [102]


async def test_lost_queue_delivery_with_uncertain_status_write_can_be_safely_resumed():
    class UnavailableRepository(MemoryRepository):
        fail_write = True

        async def replace(self, container, key, value, etag, lease=None):
            if self.fail_write and container == "requests":
                raise StorageUnavailable()
            return await super().replace(container, key, value, etag, lease)

    from server.execution import DeliveryUncertain
    repo = UnavailableRepository()
    repo.enqueue_failure = True
    key = str(uuid4())
    body = DisableRequest.model_validate(disable())
    with pytest.raises(DeliveryUncertain) as failure:
        await submit(repo, key, "owner", "stub", body)
    assert failure.value.record["requestId"] == key
    assert (await record(repo, key))["status"] == "queued"
    repo.fail_write = repo.enqueue_failure = False
    resumed = await submit(repo, key, "owner", "stub", body)
    assert resumed["requestId"] == key
    client = Client()
    await execute_request(repo, client, CONFIG, key)
    await execute_request(repo, client, CONFIG, key)
    assert client.calls == [102]


async def test_poison_finishes_unstarted_and_uncertain_targets_without_calls():
    repo, client = MemoryRepository(), Client()
    key = await seed(repo, [102, 103])
    doc = await repo.read("requests", f"{key}.json")
    doc.value["status"] = "running"
    doc.value["results"][0]["status"] = "running"
    await repo.replace("requests", f"{key}.json", doc.value, doc.etag)
    await repo.create("coordination", "stub-102.json", {"requestId": key})
    await execute_request(repo, client, CONFIG, key, poison=True)
    value = await record(repo, key)
    assert value["status"] == "unknown"
    assert [result["status"] for result in value["results"]] == ["unknown", "failed"]
    assert all("error" in result for result in value["results"])
    assert client.calls == []
    pending = await seed(repo, [101])
    await execute_request(repo, client, CONFIG, pending, poison=True)
    assert (await record(repo, pending))["status"] == "failed"


async def test_worker_rechecks_expiry_mode_and_live_gates(monkeypatch):
    repo, client = MemoryRepository(), Client()
    now = time.time()
    key = await seed(repo, options={"enableAfterADelay": int(now + 60)})
    monkeypatch.setattr("server.execution.time.time", lambda: now + 120)
    await execute_request(repo, client, CONFIG, key)
    assert (await record(repo, key))["status"] == "failed"
    # Retrying the same original payload returns its record even after expiry.
    reused = await submit(repo, key, "owner", "stub", DisableRequest.model_validate(disable(options={"enableAfterADelay": int(now + 60)})))
    assert reused["requestId"] == key
    live_settings = CONFIG.model_copy(update={
        "mode": "live", "live_operations": "false",
        "commvault_base_url": "https://commvault.invalid", "commvault_auth_value": "secret",
    })
    for settings, mode in [(CONFIG, "live"), (live_settings, "live"), (CONFIG.model_copy(update={"execution_mode": "sync"}), "stub")]:
        new = await seed(repo, mode=mode)
        await execute_request(repo, client, settings, new)
        assert (await record(repo, new))["status"] == "failed"
    assert client.calls == []


@pytest.mark.parametrize("code", ["TRANSPORT_ERROR", "INVALID_RESPONSE", "HTTP_ERROR"])
async def test_ambiguous_upstream_errors_are_unknown_and_hold_exclusion(code):
    repo, client = MemoryRepository(), Client(CommvaultError("secret", code))
    key = await seed(repo)
    await execute_request(repo, client, CONFIG, key)
    result = await owned_request(repo, key, "owner")
    assert result["status"] == "unknown"
    assert result["results"][0]["success"] is None
    assert "secret" not in json.dumps(result)
    assert await repo.read("coordination", "stub-102.json")
    await execute_request(repo, client, CONFIG, key)
    assert client.calls == [102]


async def test_shared_stub_survives_separate_runtime_clients():
    repo = MemoryRepository()
    async with upstream_client(CONFIG, repo) as worker_client:
        key = await seed(repo)
        await execute_request(repo, worker_client, CONFIG, key)
    async with upstream_client(CONFIG, repo) as timer_client:
        await refresh_inventory(repo, timer_client, CONFIG)
    servers = (await inventory(repo, CONFIG))["servers"]
    assert next(server for server in servers if server["id"] == 102)["stubBackupDisabled"] is True
    assert next(server for server in servers if server["id"] == 103)["stubBackupDisabled"] is False


async def test_repository_cas_copy_isolation_and_leases():
    await repository_contract(MemoryRepository())


async def repository_contract(repo):
    key = f"contract-{uuid4()}.json"
    value = {"value": 1}
    first = await repo.create("coordination", key, value)
    value["value"] = 900
    assert (await repo.read("coordination", key)).value == {"value": 1}
    with pytest.raises(Conflict):
        await repo.create("coordination", key, {})
    second = await repo.replace("coordination", key, {"value": 2}, first.etag)
    with pytest.raises(Conflict):
        await repo.replace("coordination", key, {}, first.etag)
    async with repo.lease("coordination", key) as lease:
        with pytest.raises(Conflict):
            await repo.replace("coordination", key, {}, second.etag)
        with pytest.raises(Conflict):
            async with repo.lease("coordination", key):
                pass
        third = await repo.replace("coordination", key, {"value": 3}, second.etag, lease=lease)
    with pytest.raises(Conflict):
        await repo.delete("coordination", key, second.etag)
    await repo.delete("coordination", key, third.etag)
    assert await repo.read("coordination", key) is None


def emulator_settings():
    settings = CONFIG.model_copy(update={"storage_connection_string": os.environ["AZURITE_TEST_CONNECTION_STRING"]})
    Settings.model_validate(settings.model_dump(by_alias=True))
    return settings


@pytest.mark.skipif(not os.environ.get("AZURITE_TEST_CONNECTION_STRING"), reason="Opt-in local Azurite integration")
async def test_azurite_conditional_storage_and_cross_client_execution():
    settings = emulator_settings()
    repo, other = AzureRepository(settings), AzureRepository(settings)
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.queue.aio import QueueClient
    # Isolate SDK delivery tests from an optionally running Functions listener.
    encoder = repo.queue._message_encode_policy
    await repo.queue.close()
    repo.queue = QueueClient.from_connection_string(
        settings.storage_connection_string, f"requests-sdk-test-{uuid4().hex}",
        message_encode_policy=encoder,
    )
    try:
        for container in ("requests", "inventory", "coordination", "stub-state"):
            try:
                await repo.blobs.create_container(container)
            except ResourceExistsError:
                pass
        try:
            await repo.queue.create_queue()
        except ResourceExistsError:
            pass
        await repository_contract(repo)
        key = await seed(repo, [2147483001])
        # Observe the actual HTTP-stored queue body, not only the encoder class.
        found = False
        async for message in repo.queue.receive_messages(max_messages=32, visibility_timeout=1):
            if base64.b64decode(message.content, validate=True).decode("utf-8") == key:
                found = True
                await repo.queue.delete_message(message)
                break
        assert found
        async with repo.lease("requests", f"{key}.json"):
            with pytest.raises(Conflict):
                async with other.lease("requests", f"{key}.json"):
                    pass
        client = Client()
        await execute_request(other, client, settings, key)
        await execute_request(repo, client, settings, key)
        assert client.calls == [2147483001]
        assert (await record(repo, key))["status"] == "completed"
        # Messages contain only the UUID, encoded for Functions.
        assert repo.queue._message_encode_policy is not None
        doc = await repo.read("requests", f"{key}.json")
        await repo.delete("requests", f"{key}.json", doc.etag)

        crashed = await seed(repo, [2147483002])
        intent = await repo.create("coordination", "stub-2147483002.json", {"requestId": crashed})
        async with repo.lease("requests", f"{crashed}.json") as lease:
            doc = await repo.read("requests", f"{crashed}.json")
            doc.value["status"] = "running"
            doc.value["results"][0]["status"] = "running"
            await repo.replace("requests", f"{crashed}.json", doc.value, doc.etag, lease=lease)
        await execute_request(other, client, settings, crashed)
        assert (await record(repo, crashed))["status"] == "unknown"
        assert client.calls == [2147483001]
        assert await repo.read("coordination", "stub-2147483002.json")
        # Only this test-created unknown intent is removed during emulator cleanup.
        await repo.delete("coordination", "stub-2147483002.json", intent.etag)
        doc = await repo.read("requests", f"{crashed}.json")
        await repo.delete("requests", f"{crashed}.json", doc.etag)
    finally:
        await repo.queue.delete_queue()
        await repo.close()
        await other.close()


@pytest.mark.skipif(not os.environ.get("AZURITE_TEST_CONNECTION_STRING"), reason="Opt-in local Azurite integration")
async def test_azurite_real_lease_renewal_keeps_exclusion(monkeypatch):
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob.aio import BlobLeaseClient

    repo, other = AzureRepository(emulator_settings()), AzureRepository(emulator_settings())
    renewed = asyncio.Event()
    original_renew = BlobLeaseClient.renew

    async def observe_renew(lease, **kwargs):
        await original_renew(lease, **kwargs)
        renewed.set()

    monkeypatch.setattr(BlobLeaseClient, "renew", observe_renew)
    monkeypatch.setattr("server.storage.REQUEST_LEASE_RENEWAL_SECONDS", 0.05)
    key = f"renewal-{uuid4()}.json"
    try:
        try:
            await repo.blobs.create_container("coordination")
        except ResourceExistsError:
            pass
        doc = await repo.create("coordination", key, {"value": 1})
        async with repo.lease("coordination", key) as lease:
            await asyncio.wait_for(renewed.wait(), timeout=5)
            with pytest.raises(Conflict):
                async with other.lease("coordination", key):
                    pass
            doc = await repo.replace("coordination", key, {"value": 2}, doc.etag, lease=lease)
        await repo.delete("coordination", key, doc.etag)
    finally:
        await repo.close()
        await other.close()


@pytest.mark.skipif(
    not (os.environ.get("AZURITE_TEST_CONNECTION_STRING") and os.environ.get("FUNCTIONS_HOST_TEST_URL")),
    reason="Opt-in isolated Functions Core Tools host and Azurite integration",
)
async def test_real_functions_host_worker_poison_and_timer():
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.queue import TextBase64EncodePolicy
    from azure.storage.queue.aio import QueueClient
    from server.execution import timestamp

    url = os.environ["FUNCTIONS_HOST_TEST_URL"]
    parsed = urlsplit(url)
    assert parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    settings = emulator_settings()
    repo = AzureRepository(settings)
    poison = QueueClient.from_connection_string(
        settings.storage_connection_string, "requests-poison", message_encode_policy=TextBase64EncodePolicy(),
    )

    async def terminal(request_id):
        async with asyncio.timeout(90):
            while True:
                doc = await repo.read("requests", f"{request_id}.json")
                if doc.value["status"] in ("completed", "partial", "failed", "unknown"):
                    return doc.value
                await asyncio.sleep(0.2)

    normal_id, poison_id = str(uuid4()), str(uuid4())
    target_key = "stub-2147483003.json"
    try:
        try:
            await poison.create_queue()
        except ResourceExistsError:
            pass
        async with httpx.AsyncClient(base_url=url) as http:
            status = await http.get("/admin/host/status")
            assert status.status_code == 200 and status.json()["state"] == "Running"
            await submit(repo, normal_id, "local-host-test", "stub", DisableRequest.model_validate(disable()))
            completed = await terminal(normal_id)
            assert completed["status"] == "completed"
            assert completed["results"] == [{"serverId": 102, "status": "accepted", "success": True}]
            state = await repo.read("stub-state", "102.json")
            assert state.value["disabled"] is True
            await repo.enqueue(normal_id)
            await asyncio.sleep(3)
            assert (await repo.read("stub-state", "102.json")).etag == state.etag

            now = timestamp()
            await repo.create("requests", f"{poison_id}.json", {
                "requestId": poison_id, "owner": "local-host-test", "fingerprint": "local-fixture",
                "mode": "stub", "status": "running", "submittedAt": now, "updatedAt": now,
                "serverIds": [2147483003, 101], "options": {},
                "results": [
                    {"serverId": 2147483003, "status": "running", "success": None},
                    {"serverId": 101, "status": "pending", "success": None},
                ],
            })
            await repo.create("coordination", target_key, {"requestId": poison_id, "createdAt": now})
            await poison.send_message(poison_id)
            poisoned = await terminal(poison_id)
            assert poisoned["status"] == "unknown"
            assert [result["status"] for result in poisoned["results"]] == ["unknown", "failed"]
            assert await repo.read("coordination", target_key)

            refreshed = await http.post("/admin/functions/inventory_refresh", json={"input": None})
            assert refreshed.status_code == 202
            async with asyncio.timeout(30):
                while True:
                    snapshot = await repo.read("inventory", "stub.json")
                    if snapshot and snapshot.value.get("updatedAt") and snapshot.value["updatedAt"] >= now:
                        break
                    await asyncio.sleep(0.2)
            cached = await inventory(repo, settings)
            assert cached["inventory"]["refreshError"] is None
            assert next(server for server in cached["servers"] if server["id"] == 102)["stubBackupDisabled"]
    finally:
        for container, key in (
            ("requests", f"{normal_id}.json"), ("requests", f"{poison_id}.json"),
            ("coordination", target_key),
        ):
            doc = await repo.read(container, key)
            if doc:
                await repo.delete(container, key, doc.etag)
        await poison.close()
        await repo.close()


@pytest.mark.parametrize("env", [
    {"EXECUTION_MODE": "other"},
    {"APP_ENV": "production", "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true", **IDENTITY},
    {"AZURE_STORAGE_CONNECTION_STRING": "DefaultEndpointsProtocol=https;AccountName=prod;AccountKey=secret"},
    {"AZURE_STORAGE_CONNECTION_STRING": "BlobEndpoint=http://127.0.0.1:10000/a;QueueEndpoint=https://remote.invalid"},
    {"INVENTORY_MAX_AGE_SECONDS": "0"},
])
def test_storage_configuration_is_fail_closed_and_redacted(env):
    with pytest.raises(ValueError) as error:
        Settings.from_env(env)
    assert "secret" not in str(error.value)


def test_functions_register_timer_work_and_poison():
    import function_app
    functions = function_app.app.get_functions()
    assert {function.get_function_name() for function in functions} == {
        "inventory_refresh", "request_worker", "request_poison",
    }
    bindings = {
        function.get_function_name(): function.get_dict_repr()["bindings"][0]
        for function in functions
    }
    assert bindings["request_worker"]["type"] == "queueTrigger"
    assert bindings["request_worker"]["queueName"] == "requests"
    assert bindings["request_poison"]["queueName"] == "requests-poison"
    assert all(bindings[name]["connection"] == "WORK_STORAGE" for name in ("request_worker", "request_poison"))
    assert bindings["inventory_refresh"]["type"] == "timerTrigger"
    assert bindings["inventory_refresh"]["runOnStartup"] is False
    assert bindings["inventory_refresh"]["schedule"] == os.environ.get("INVENTORY_REFRESH_SCHEDULE", "0 */5 * * * *")


def test_minimal_functions_package_discovers_bindings_without_workspace(tmp_path):
    root = Path(__file__).resolve().parent.parent
    paths = [root / name for name in ("function_app.py", "host.json", "requirements.txt")]
    paths.extend(sorted((root / "server").glob("*.py")))
    archive = tmp_path / "function-app.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in paths:
            bundle.write(path, path.relative_to(root))
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {str(path.relative_to(root)) for path in paths}
        assert ".env" not in bundle.namelist()
        bundle.extractall(tmp_path / "extracted")
    result = subprocess.run(
        [sys.executable, "-c",
         "import json,function_app; print(json.dumps(sorted(f.get_function_name() for f in function_app.app.get_functions())))"],
        cwd=tmp_path / "extracted", capture_output=True, text=True, check=True,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
    )
    assert json.loads(result.stdout) == ["inventory_refresh", "request_poison", "request_worker"]


async def test_upstream_total_deadline_is_below_lease_renewal_and_never_retries(monkeypatch):
    assert UPSTREAM_TOTAL_TIMEOUT_SECONDS < REQUEST_LEASE_RENEWAL_SECONDS
    monkeypatch.setattr("server.commvault.UPSTREAM_TOTAL_TIMEOUT_SECONDS", 0.02)
    calls = []

    async def slow_response(request):
        calls.append(request)
        await asyncio.sleep(1)
        return httpx.Response(200, json={"errorCode": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow_response)) as http:
        client = CommvaultClient(http, "https://upstream.invalid", "Authorization", "private-credential")
        repo = MemoryRepository()
        key = await seed(repo)
        started = time.monotonic()
        await execute_request(repo, client, CONFIG, key)
        assert time.monotonic() - started < 0.5
        assert len(calls) == 1
        assert (await record(repo, key))["status"] == "unknown"
        await execute_request(repo, client, CONFIG, key)
        assert len(calls) == 1


async def test_actual_queue_encoding_matches_functions_decoder():
    repo = AzureRepository(CONFIG.model_copy(update={"storage_connection_string": "UseDevelopmentStorage=true"}))
    try:
        request_id = str(uuid4())
        encoded = repo.queue._message_encode_policy.encode(request_id)
        assert base64.b64decode(encoded, validate=True).decode("utf-8") == request_id
        host = json.loads((Path(__file__).resolve().parent.parent / "host.json").read_text())
        assert host["extensions"]["queues"]["messageEncoding"] == "base64"
    finally:
        await repo.close()
