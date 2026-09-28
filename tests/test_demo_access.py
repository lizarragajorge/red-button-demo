from uuid import uuid4

import pytest

from server.config import Settings
from server.execution import execute_request
from test_app import CONFIG, IDENTITY, disable, harness, private_key, token
from test_multitenant import EXTERNAL, claims, multi_settings
from test_queued import Client, api


@pytest.mark.parametrize("tenant", [CONFIG.tenant_id, EXTERNAL])
async def test_default_demo_allows_authenticated_users_without_operator_role(harness, tenant):
    async with harness(multi_settings()) as app:
        actor = claims(tenant, roles=[])
        assert (await app.request("/api/config", anonymous=True)).json()["signedInDemoOperations"] is True
        assert (await app.request("/api/me", claims=actor)).json() == {"canDisable": True}
        assert (await app.request("/api/servers", claims=actor)).status_code == 200
        result = await app.request("/api/disable", body=disable(), claims=actor)
        assert result.status_code == 200 and result.json()["results"][0]["success"] is True
        assert app.store.get_state(102).disabled


async def test_demo_does_not_require_a_roles_claim_but_still_requires_confirmation(harness, private_key):
    async with harness() as app:
        headers = {"Authorization": "Bearer " + token(private_key, remove=("roles",))}
        assert (await app.http.get("/api/me", headers=headers)).json() == {"canDisable": True}
        assert (await app.http.post("/api/disable", headers=headers, json={**disable(), "confirmation": ""})).status_code == 400
        assert not app.store.get_state(102).disabled
        assert (await app.request("/api/disable", body=disable(), anonymous=True)).status_code == 401


@pytest.mark.parametrize("role", ["DemoOperator", "Reader", None])
@pytest.mark.parametrize("live_gate", ["true", "false"])
async def test_demo_permissions_never_authorize_live_actions(harness, role, live_gate):
    settings = Settings.from_env({
        **IDENTITY, "APP_ENV": "test", "COMMVAULT_MODE": "live",
        "COMMVAULT_BASE_URL": "https://live.invalid", "COMMVAULT_AUTH_VALUE": "test-value",
        "ENABLE_LIVE_OPERATIONS": live_gate,
    })
    async with harness(settings) as app:
        actor = {"roles": [role] if role else []}
        assert (await app.request("/api/config", anonymous=True)).json()["signedInDemoOperations"] is False
        assert (await app.request("/api/me", claims=actor)).json() == {"canDisable": False}
        assert (await app.request("/api/disable", body=disable(), claims=actor)).status_code == 403
        assert not app.store.get_state(102).disabled


async def test_queued_demo_allows_submission_and_own_recovery_without_operator_role(private_key):
    settings = multi_settings(EXECUTION_MODE="queued")
    async with api(private_key, settings=settings) as (http, repo):
        owner = {"Authorization": "Bearer " + token(private_key, claims(roles=[]))}
        foreign = {"Authorization": "Bearer " + token(private_key, claims(roles=[], oid="another-user"))}
        request_id = str(uuid4())
        response = await http.post("/api/disable", headers={**owner, "Idempotency-Key": request_id}, json=disable())
        assert response.status_code == 202 and response.json()["status"] == "queued"
        client = Client()
        await execute_request(repo, client, settings, request_id)
        assert client.calls == [102]
        assert (await http.get(f"/api/requests/{request_id}", headers=owner)).json()["status"] == "completed"
        assert (await http.get(f"/api/requests/{request_id}", headers=foreign)).status_code == 404
        assert (await http.post("/api/disable", headers={**foreign, "Idempotency-Key": request_id}, json=disable())).status_code == 404
