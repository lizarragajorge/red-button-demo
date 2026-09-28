import json
import shutil
import uuid
from pathlib import Path

import httpx
import pytest

from server import app as app_module
from server.config import Settings

RELEASE_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def marker(monkeypatch):
    directory = Path(".pytest_cache/release-runtime-tests") / str(uuid.uuid4())
    directory.mkdir(parents=True)
    path = directory / "release.json"
    monkeypatch.setattr(app_module, "RELEASE_MARKER", path)
    try:
        yield path
    finally:
        shutil.rmtree(directory)


async def config(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.invalid") as client:
        return (await client.get("/api/config")).json()


async def test_absent_marker_does_not_change_config(marker):
    app = app_module.create_app(Settings.from_env({"APP_ENV": "test"}))
    assert "releaseId" not in await config(app)


async def test_marker_loaded_once_at_app_creation(marker):
    marker.write_text(json.dumps({"releaseId": RELEASE_ID, "sourceSha256": "a" * 64}))
    app = app_module.create_app(Settings.from_env({"APP_ENV": "test"}))
    marker.write_text(json.dumps({"releaseId": str(uuid.uuid4()), "sourceSha256": "b" * 64}))
    assert (await config(app))["releaseId"] == RELEASE_ID
    marker.unlink()
    assert (await config(app))["releaseId"] == RELEASE_ID


@pytest.mark.parametrize("value", ["not json", "[]", "null", "{}", '{"releaseId": "bad"}',
                                    json.dumps({"releaseId": RELEASE_ID, "sourceSha256": "bad"}),
                                    json.dumps({"releaseId": 123, "sourceSha256": "a" * 64})])
def test_malformed_marker_fails_clearly_at_startup(marker, value):
    marker.write_text(value)
    with pytest.raises(RuntimeError, match="release.json is malformed"):
        app_module.create_app(Settings.from_env({"APP_ENV": "test"}))
