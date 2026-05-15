"""Tests for app.broker.oauth — register_client + OAuthCoordinator.

We never hit the real LongBridge endpoints; httpx is replaced with a
respx-style mock, and the OAuthBuilder factory is replaced with a fake that
synchronously calls back with a deterministic URL and resolves immediately.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio

from app.broker import oauth as oauth_mod


class TestRegisterClient:
    @pytest.mark.asyncio
    async def test_returns_client_id_on_success(self) -> None:
        # Mock the underlying httpx call by patching AsyncClient.post.
        async def fake_post(self, url, json):  # noqa: ANN001
            assert url == "https://openapi.longbridge.com/oauth2/register"
            assert json["client_name"] == "Test Station"
            return httpx.Response(200, json={"client_id": "cid-abc-123"})

        with patch.object(httpx.AsyncClient, "post", fake_post):
            cid = await oauth_mod.register_client(client_name="Test Station")
        assert cid == "cid-abc-123"

    @pytest.mark.asyncio
    async def test_4xx_raises_runtime_error(self) -> None:
        async def fake_post(self, url, json):  # noqa: ANN001
            return httpx.Response(400, json={"error": "bad request"})

        with patch.object(httpx.AsyncClient, "post", fake_post):
            with pytest.raises(RuntimeError, match="registration failed"):
                await oauth_mod.register_client()

    @pytest.mark.asyncio
    async def test_missing_client_id_in_response_raises(self) -> None:
        async def fake_post(self, url, json):  # noqa: ANN001
            return httpx.Response(200, json={"other": "field"})

        with patch.object(httpx.AsyncClient, "post", fake_post):
            with pytest.raises(RuntimeError, match="missing client_id"):
                await oauth_mod.register_client()


class TestTokenProbeAndRevoke:
    def test_is_authorized_false_for_empty_client_id(self) -> None:
        assert oauth_mod.is_authorized("") is False
        assert oauth_mod.is_authorized(None) is False

    def test_is_authorized_reflects_token_file(self, tmp_path: Path) -> None:
        client_id = "cid-probe"
        token_dir = tmp_path / "tokens"
        token_dir.mkdir()
        token_file = token_dir / client_id
        with patch.object(oauth_mod, "token_path", return_value=token_file):
            assert oauth_mod.is_authorized(client_id) is False
            token_file.write_text("dummy", encoding="utf-8")
            assert oauth_mod.is_authorized(client_id) is True

    def test_revoke_deletes_token_file(self, tmp_path: Path) -> None:
        client_id = "cid-revoke"
        token_file = tmp_path / client_id
        token_file.write_text("dummy", encoding="utf-8")
        with patch.object(oauth_mod, "token_path", return_value=token_file):
            assert oauth_mod.revoke_local_token(client_id) is True
            assert not token_file.exists()
            # Re-revoke is a no-op.
            assert oauth_mod.revoke_local_token(client_id) is False


class _FakeOAuthBuilder:
    """Drop-in OAuthBuilder for tests.

    On ``build_async`` it (1) immediately invokes the URL callback with a
    deterministic auth URL and (2) waits for ``release_event`` (or completes
    instantly when ``auto_release=True``). Errors can be injected via
    ``raise_on_build``.
    """

    instances: list["_FakeOAuthBuilder"] = []

    def __init__(self, client_id: str, callback_port: int = 60355) -> None:
        self.client_id = client_id
        self.callback_port = callback_port
        self.release_event: asyncio.Event | None = None
        self.auto_release = True
        self.raise_on_build: Exception | None = None
        _FakeOAuthBuilder.instances.append(self)

    async def build_async(self, on_url):  # noqa: ANN001
        on_url(f"https://example.test/oauth/authorize?cid={self.client_id}")
        if self.raise_on_build is not None:
            raise self.raise_on_build
        if self.auto_release:
            return object()
        # Manual: wait until the test releases us.
        assert self.release_event is not None
        await self.release_event.wait()
        return object()


@pytest_asyncio.fixture
async def coordinator() -> oauth_mod.OAuthCoordinator:
    _FakeOAuthBuilder.instances.clear()
    return oauth_mod.OAuthCoordinator(
        builder_factory=lambda cid, port: _FakeOAuthBuilder(cid, port),
        auth_timeout=5.0,
    )


class TestCoordinator:
    @pytest.mark.asyncio
    async def test_start_returns_ready_session_with_url(
        self,
        coordinator: oauth_mod.OAuthCoordinator,
    ) -> None:
        session = await coordinator.start("cid-1")
        # State right after URL capture should be "ready" — the task may or
        # may not have completed yet (FakeOAuthBuilder returns instantly).
        assert session.client_id == "cid-1"
        assert session.auth_url is not None
        assert "cid-1" in session.auth_url
        assert session.state in ("ready", "success")
        # Wait for the underlying task to complete (auto_release=True).
        await asyncio.sleep(0.05)
        final = coordinator.get(session.session_id)
        assert final is not None
        assert final.state == "success"

    @pytest.mark.asyncio
    async def test_start_propagates_error_from_builder(
        self,
        coordinator: oauth_mod.OAuthCoordinator,
    ) -> None:
        def factory(cid: str, port: int) -> _FakeOAuthBuilder:
            b = _FakeOAuthBuilder(cid, port)
            b.raise_on_build = RuntimeError("boom")
            return b

        coordinator = oauth_mod.OAuthCoordinator(builder_factory=factory)
        session = await coordinator.start("cid-2")
        # URL callback fires before the exception, so we still get an
        # auth_url; the eventual session state should flip to error.
        await asyncio.sleep(0.05)
        final = coordinator.get(session.session_id)
        assert final is not None
        assert final.state == "error"
        assert final.error and "boom" in final.error

    @pytest.mark.asyncio
    async def test_start_cancels_prior_session(
        self,
    ) -> None:
        # Use a manual-release builder so the first session stays "ready"
        # until the second start kicks in.
        builders: list[_FakeOAuthBuilder] = []

        def factory(cid: str, port: int) -> _FakeOAuthBuilder:
            b = _FakeOAuthBuilder(cid, port)
            b.auto_release = False
            b.release_event = asyncio.Event()
            builders.append(b)
            return b

        coord = oauth_mod.OAuthCoordinator(builder_factory=factory, auth_timeout=10.0)
        s1 = await coord.start("cid-A")
        assert s1.state == "ready"

        # Start a second session — coordinator must cancel s1 first.
        s2 = await coord.start("cid-B")
        assert s2.session_id != s1.session_id
        # s1 transitioned to cancelled state.
        await asyncio.sleep(0.05)
        cancelled = coord.get(s1.session_id)
        assert cancelled is not None
        assert cancelled.state == "cancelled"

        # Cleanup: release the second so we don't leak an awaiting task.
        builders[-1].release_event.set()  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_url_capture_timeout(self) -> None:
        # Builder that never fires the URL callback — coordinator should
        # surface an error session within URL_CAPTURE_TIMEOUT_SEC.
        class _NoUrlBuilder(_FakeOAuthBuilder):
            async def build_async(self, on_url):  # noqa: ANN001
                # never fire on_url; just block forever
                await asyncio.sleep(60)

        with patch.object(oauth_mod, "URL_CAPTURE_TIMEOUT_SEC", 0.1):
            coord = oauth_mod.OAuthCoordinator(
                builder_factory=lambda cid, port: _NoUrlBuilder(cid, port),
            )
            session = await coord.start("cid-slow")
        assert session.state == "error"
        assert session.error and "URL" in session.error
