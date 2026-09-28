import json
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from server.auth import EntraTokenVerifier, TokenRejected
from server.config import Settings
from server.execution import refresh_inventory
from test_app import CONFIG, IDENTITY, LocalKeys, disable, harness, private_key, token
from test_queued import Client, api

EXTERNAL = "44444444-4444-4444-8444-444444444444"
SECOND = "55555555-5555-4555-8555-555555555555"
UNTRUSTED = "66666666-6666-4666-8666-666666666666"


def multi_settings(**overrides):
    return Settings.from_env({
        **IDENTITY, "APP_ENV": "test", "ENTRA_MULTI_TENANT": "true",
        "ENTRA_ALLOWED_TENANT_IDS": f"{EXTERNAL},{SECOND}", **overrides,
    })


def claims(tenant=EXTERNAL, **overrides):
    return {"tid": tenant, "iss": f"https://login.microsoftonline.com/{tenant}/v2.0", **overrides}


def test_allowlist_is_opt_in_bounded_and_home_tenant_is_preserved():
    assert CONFIG.trusted_tenant_ids == {CONFIG.tenant_id}
    settings = multi_settings()
    assert settings.trusted_tenant_ids == {CONFIG.tenant_id, EXTERNAL, SECOND}
    with_letters = "abcdefab-cdef-4abc-8def-abcdefabcdef"
    assert multi_settings(ENTRA_ALLOWED_TENANT_IDS=f" {with_letters.upper()} ").allowed_tenant_ids == (with_letters,)


@pytest.mark.parametrize("overrides", [
    {"ENTRA_MULTI_TENANT": "false"},
    {"ENTRA_ALLOWED_TENANT_IDS": ""},
    {"ENTRA_ALLOWED_TENANT_IDS": CONFIG.tenant_id},
    {"ENTRA_ALLOWED_TENANT_IDS": "organizations"},
    {"ENTRA_ALLOWED_TENANT_IDS": "common"},
    {"ENTRA_ALLOWED_TENANT_IDS": "https://attacker.invalid/keys"},
    {"ENTRA_ALLOWED_TENANT_IDS": "9188040d-6c67-4c5b-b112-36a304b66dad"},
    {"ENTRA_ALLOWED_TENANT_IDS": f"{EXTERNAL},{EXTERNAL}"},
    {"ENTRA_ALLOWED_TENANT_IDS": f"{EXTERNAL},"},
    {"ENTRA_ALLOWED_TENANT_IDS": ",".join(str(uuid4()) for _ in range(21))},
    {"ENTRA_TENANT_ID": ""},
    {"ENTRA_TENANT_ID": "9188040d-6c67-4c5b-b112-36a304b66dad"},
    {"ENTRA_MULTI_TENANT": "yes"},
])
def test_bad_allowlist_fails_closed_without_echoing_values(overrides):
    with pytest.raises(ValueError, match="Invalid application configuration"):
        multi_settings(**overrides)


@pytest.mark.parametrize("tenant", [CONFIG.tenant_id, EXTERNAL, SECOND])
async def test_each_explicit_tenant_validates_and_preserves_actor_tenant(private_key, tenant):
    actor = await EntraTokenVerifier(multi_settings(), LocalKeys(private_key)).verify(token(private_key, claims(tenant)))
    assert actor.tenant_id == tenant
    assert actor.oid == "operator-object-id"
    assert actor.roles == ("BackupOperator",)


@pytest.mark.parametrize("tenant", [UNTRUSTED, "common", "../../keys", ["bad"], None])
async def test_untrusted_tenant_is_rejected_before_key_lookup(private_key, tenant):
    class NoLookup:
        def get_signing_key_from_jwt(self, raw):
            raise AssertionError("Untrusted token must not trigger key retrieval")

    verifier = EntraTokenVerifier(multi_settings(), NoLookup())
    raw = token(private_key, {"tid": tenant, "preferred_username": "person@microsoft.com"})
    with pytest.raises(TokenRejected):
        await verifier.verify(raw)


@pytest.mark.parametrize("overrides", [
    {"iss": f"https://login.microsoftonline.com/{CONFIG.tenant_id}/v2.0"},
    {"iss": f"https://attacker.invalid/{EXTERNAL}/v2.0"},
    {"aud": CONFIG.spa_client_id},
    {"azp": UNTRUSTED},
    {"scp": "unrelated_scope"},
    {"exp": 1},
    {"roles": "BackupOperator"},
])
async def test_external_tokens_keep_existing_security_checks(private_key, overrides):
    verifier = EntraTokenVerifier(multi_settings(), LocalKeys(private_key))
    with pytest.raises((jwt.PyJWTError, TokenRejected)):
        await verifier.verify(token(private_key, claims(**overrides)))


async def test_external_tenant_is_not_accepted_in_default_single_tenant_mode(private_key):
    with pytest.raises(TokenRejected):
        await EntraTokenVerifier(CONFIG, LocalKeys(private_key)).verify(token(private_key, claims()))


async def test_key_clients_are_bound_to_allowlisted_authorities(monkeypatch, private_key):
    second_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    requested = []

    def keys(url, **kwargs):
        requested.append(url)
        return LocalKeys(second_key if url == f"https://login.microsoftonline.com/{SECOND}/discovery/v2.0/keys" else private_key)

    monkeypatch.setattr(jwt, "PyJWKClient", keys)
    verifier = EntraTokenVerifier(multi_settings())
    assert set(requested) == {
        f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
        for tenant in (CONFIG.tenant_id, EXTERNAL, SECOND)
    }
    assert (await verifier.verify(token(second_key, claims(SECOND)))).tenant_id == SECOND
    with pytest.raises(jwt.InvalidSignatureError):
        await verifier.verify(token(private_key, claims(SECOND)))


async def test_external_read_access_does_not_grant_operator_permission(harness):
    async with harness(multi_settings()) as app:
        readonly = claims(roles=[])
        assert (await app.request("/api/servers", claims=readonly)).status_code == 200
        assert (await app.request("/api/me", claims=readonly)).json() == {"canDisable": False}
        assert (await app.request("/api/disable", body=disable(), claims=readonly)).status_code == 403
        assert (await app.request("/api/disable", body=disable(), claims=claims())).status_code == 200
        assert app.audit[-1]["actorTenantId"] == EXTERNAL
        public = (await app.request("/api/config", anonymous=True)).json()
        assert public["multiTenant"] is True
        assert set(public["allowedTenantIds"]) == multi_settings().trusted_tenant_ids


async def test_same_oid_in_another_tenant_cannot_read_or_reuse_request(private_key):
    settings = multi_settings(EXECUTION_MODE="queued")
    async with api(private_key, settings=settings) as (http, repo):
        await refresh_inventory(repo, Client(), settings)
        request_id = str(uuid4())
        first_headers = {"Authorization": "Bearer " + token(private_key, claims(EXTERNAL)), "Idempotency-Key": request_id}
        second_headers = {"Authorization": "Bearer " + token(private_key, claims(SECOND)), "Idempotency-Key": request_id}
        first = await http.post("/api/disable", json=disable(), headers=first_headers)
        assert first.status_code == 202
        assert (await http.get(f"/api/requests/{request_id}", headers=first_headers)).status_code == 200
        assert (await http.get(f"/api/requests/{request_id}", headers=second_headers)).status_code == 404
        assert (await http.post("/api/disable", json=disable(), headers=second_headers)).status_code == 404
        assert (await repo.read("requests", f"{request_id}.json")).value["owner"] == f"{EXTERNAL}:operator-object-id"
        home_id = str(uuid4())
        home = await http.post("/api/disable", json=disable(), headers={"Idempotency-Key": home_id})
        assert home.status_code == 202
        assert (await repo.read("requests", f"{home_id}.json")).value["owner"] == f"{CONFIG.tenant_id}:operator-object-id"
        assert "owner" not in json.dumps(first.json())
