"""Tests for app.api.auth — APP_TOKEN dependency."""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.auth import require_app_token
from app.core.config import Settings, get_settings

_TEST_TOKEN = "test-token-123"

# ---------------------------------------------------------------------------
# Toy app fixture
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    """Create a minimal FastAPI app with a single protected route."""
    app = FastAPI()

    def _override_settings() -> Settings:
        return Settings(app_token=_TEST_TOKEN)

    app.dependency_overrides[get_settings] = _override_settings

    @app.get("/protected", dependencies=[Depends(require_app_token)])
    async def protected() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(_make_app(), raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Happy-path: all three token sources
# ---------------------------------------------------------------------------


def test_query_param_token_accepted(client: TestClient) -> None:
    resp = client.get("/protected", params={"token": _TEST_TOKEN})
    assert resp.status_code == 200


def test_bearer_header_token_accepted(client: TestClient) -> None:
    resp = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
    )
    assert resp.status_code == 200


def test_x_app_token_header_accepted(client: TestClient) -> None:
    resp = client.get(
        "/protected",
        headers={"X-App-Token": _TEST_TOKEN},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------


def test_no_token_returns_403(client: TestClient) -> None:
    resp = client.get("/protected")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "invalid or missing token"


def test_wrong_token_returns_403(client: TestClient) -> None:
    resp = client.get("/protected", params={"token": "wrong-token"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "invalid or missing token"
