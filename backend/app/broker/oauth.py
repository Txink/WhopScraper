"""LongBridge OAuth 2.0 helper — client registration + authorization session.

The official ``longbridge`` Python SDK (4.x) exposes ``OAuthBuilder`` which
runs a local HTTP callback server on a chosen port (default 60355) to
receive the OAuth authorization code, exchanges it for tokens, and persists
those tokens to ``~/.longbridge/openapi/tokens/<client_id>``. The SDK
auto-refreshes the access token when it expires, so subsequent
``OAuthBuilder(client_id).build(...)`` calls reuse the cached token without
prompting the user.

What the SDK does NOT provide is the one-shot OAuth client registration:
the developer has to POST to ``/oauth2/register`` themselves and store the
``client_id``. We bundle that here so the UI can register on first login
and never bother the user with developer-portal navigation.

This module is import-safe — it does not start any tasks or hit the network
at import time. Callers (FastAPI endpoint handlers) drive the lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import socket
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

import httpx

logger = logging.getLogger(__name__)

# Endpoint for the OAuth client-registration call. Documented at
# https://open.longbridge.com/zh-CN/docs/getting-started — the ``client_id``
# is returned in the response body and is permanent for the registered
# redirect URI set.
_OAUTH_REGISTER_URL = "https://openapi.longbridge.com/oauth2/register"

# Default port the SDK opens its local callback server on. We register
# multiple candidate ports up-front so the coordinator can fall back when
# a port is still bound by a previous in-flight session (Rust-side socket
# release is not deterministic on asyncio cancellation).
DEFAULT_CALLBACK_PORT = 60355
CANDIDATE_CALLBACK_PORTS: tuple[int, ...] = (60355, 60356, 60357)

# Where the SDK persists OAuth tokens. Documented in the official SDK
# reference. We probe this path to derive ``authorized`` state without
# inspecting SDK internals.
_TOKEN_DIR = Path.home() / ".longbridge" / "openapi" / "tokens"

# How long the UI may take to open the browser + complete authorization
# before we time out the awaiting task. 5 minutes is generous but bounded.
DEFAULT_AUTH_TIMEOUT_SEC = 300.0

# How long the SDK is given to fire the URL callback after build_async is
# invoked. The SDK spawns the local server immediately, so this should be
# near-instant — 10s is a safety net for slow CI / disk-bound startup.
URL_CAPTURE_TIMEOUT_SEC = 10.0


SessionState = Literal["awaiting_url", "ready", "success", "error", "cancelled"]


def _is_port_bind_error(message: str) -> bool:
    """True iff the error message looks like the SDK's port-bind failure.

    The SDK surfaces it via ``OpenApiException(ErrorKind.OAuth, ...)`` with
    a message like:
        "failed to bind callback server on port 60355:
         Address already in use (os error 48)"
    """
    m = message.lower()
    return "bind callback server" in m or "address already in use" in m


def _is_port_free(port: int) -> bool:
    """Return True iff we can bind a fresh listening socket on ``port``.

    Trying to bind tests the port the same way the SDK's Rust HTTP server
    will — if our trial bind succeeds (and the kernel releases the socket
    immediately on close), the SDK's bind will succeed too.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        return False
    finally:
        s.close()
    return True


async def _wait_for_port_free(port: int, *, timeout: float = 5.0) -> bool:
    """Poll ``port`` every 100 ms until it's free or the timeout elapses.

    Returns True if the port became free, False on timeout. We use this
    after cancelling a previous OAuth task because asyncio.CancelledError
    propagates into the Rust SDK asynchronously — the underlying HTTP
    server may take a beat to release the listening socket even after the
    Python task object reports done.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_port_free(port):
            return True
        await asyncio.sleep(0.1)
    return _is_port_free(port)


@dataclass
class OAuthSession:
    """In-memory snapshot of an in-flight OAuth flow.

    ``ready`` is the steady state once the URL has been handed back to the
    UI: the task is still running, waiting for the user to authorize in
    their browser. On the SDK callback firing with ``code``, the task
    completes and we transition to ``success``.
    """

    session_id: str
    client_id: str
    state: SessionState = "awaiting_url"
    auth_url: str | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)


async def register_client(
    *,
    callback_port: int = DEFAULT_CALLBACK_PORT,
    client_name: str = "Signal Station",
    timeout: float = 15.0,
) -> str:
    """Register an OAuth client with Longbridge and return its ``client_id``.

    We always use a single callback port — the coordinator deterministically
    tears down the previous listener before binding a new one on the same
    port, so there's no benefit to declaring multiple redirect_uris.
    """
    payload: dict[str, Any] = {
        "redirect_uris": [f"http://localhost:{callback_port}/callback"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_name": client_name,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(_OAUTH_REGISTER_URL, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"OAuth client registration failed (HTTP {resp.status_code}): {resp.text}"
        )
    body = resp.json()
    client_id = body.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise RuntimeError(f"OAuth registration response missing client_id: {body!r}")
    return client_id


def token_path(client_id: str) -> Path:
    """Return the path where the SDK persists OAuth tokens for ``client_id``.

    Existence of this file is treated as the source of truth for whether
    the user has completed an authorization flow at some point — the SDK
    auto-refreshes the access token transparently as long as the refresh
    token in this file is still valid.
    """
    return _TOKEN_DIR / client_id


def is_authorized(client_id: str | None) -> bool:
    """True iff a persisted OAuth token exists for ``client_id``."""
    if not client_id:
        return False
    return token_path(client_id).exists()


def revoke_local_token(client_id: str | None) -> bool:
    """Delete the local persisted token for ``client_id``.

    Returns True if a token existed and was deleted. Note this does not
    revoke the token server-side at Longbridge — the user would need to
    revoke from the developer portal for a true logout.
    """
    if not client_id:
        return False
    p = token_path(client_id)
    if not p.exists():
        return False
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return True
    except OSError as e:
        logger.warning("Failed to revoke local OAuth token for %s: %s", client_id, e)
        return False


# ----------------------------------------------------------------------------- #
# Session coordinator                                                            #
# ----------------------------------------------------------------------------- #

# Type alias for the OAuthBuilder factory; pulled out so tests can inject a
# fake. Real callers don't need to override.
OAuthBuilderFactory = Callable[[str, int], Any]


def _default_builder_factory(client_id: str, callback_port: int) -> Any:
    """Construct a real ``longbridge.openapi.OAuthBuilder``.

    Lazy-imported so this module remains import-safe in tests that haven't
    installed the SDK (rare, but supported).
    """
    from longbridge.openapi import OAuthBuilder

    return OAuthBuilder(client_id, callback_port)


class OAuthCoordinator:
    """Tracks in-flight OAuth flows and exposes a session-based polling API.

    Only one flow can be active at a time because the SDK's local callback
    server binds to a fixed TCP port. ``start`` cancels any prior in-flight
    session before launching a new one.
    """

    def __init__(
        self,
        *,
        builder_factory: OAuthBuilderFactory | None = None,
        auth_timeout: float = DEFAULT_AUTH_TIMEOUT_SEC,
    ) -> None:
        self._builder_factory = builder_factory or _default_builder_factory
        self._auth_timeout = auth_timeout
        self._sessions: dict[str, OAuthSession] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        # ``_current`` points at the most-recently-started session, if any —
        # used to cancel before binding to the SDK port again.
        self._current: str | None = None

    def get(self, session_id: str) -> OAuthSession | None:
        return self._sessions.get(session_id)

    async def start(
        self,
        client_id: str,
        *,
        callback_port: int = DEFAULT_CALLBACK_PORT,
    ) -> OAuthSession:
        """Kick off an OAuth flow for ``client_id``.

        Always uses the same callback port (default 60355). Any prior
        in-flight session is cancelled, then we poll the port until it's
        actually free before re-binding. asyncio.CancelledError propagates
        into the SDK's Rust task asynchronously — a fixed sleep can race;
        the OS-level probe is deterministic.
        """
        if self._current is not None:
            await self._cancel(self._current)

        # Probe the port. If a previous OAuth task (in this process or a
        # leaked one from before a backend reload) still holds the
        # listening socket, wait up to 5 s for it to release. If after
        # that the port is still busy, surface a clear error — the holder
        # is outside our control (different process, system service, etc.).
        if not await _wait_for_port_free(callback_port, timeout=5.0):
            session_id = uuid.uuid4().hex
            sess = OAuthSession(session_id=session_id, client_id=client_id)
            sess.state = "error"
            sess.error = (
                f"OAuth 回调端口 {callback_port} 被占用且 5 秒内未释放。"
                "可能有其他进程在监听此端口，请关闭后重试，或重启 signal-station 后端。"
            )
            self._sessions[session_id] = sess
            return sess

        return await self._try_port(client_id, callback_port)

    async def _try_port(self, client_id: str, callback_port: int) -> OAuthSession:
        """Attempt one OAuth flow on the given port. Caller decides whether
        to fall back to the next port based on the resulting session.error.
        """
        session_id = uuid.uuid4().hex
        session = OAuthSession(session_id=session_id, client_id=client_id)
        self._sessions[session_id] = session
        self._current = session_id

        loop = asyncio.get_running_loop()
        url_future: asyncio.Future[str] = loop.create_future()

        def on_url(url: str) -> None:
            if not url_future.done():
                loop.call_soon_threadsafe(url_future.set_result, url)

        task = asyncio.create_task(
            self._run(session_id, client_id, callback_port, on_url, url_future)
        )
        self._tasks[session_id] = task

        try:
            auth_url = await asyncio.wait_for(url_future, timeout=URL_CAPTURE_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            task.cancel()
            session.state = "error"
            session.error = "OAuth URL was not produced within timeout"
            return session
        except Exception as e:  # _run set the future exception
            session.state = "error"
            session.error = session.error or f"OAuth init failed: {e!r}"
            return session

        session.auth_url = auth_url
        if session.state == "awaiting_url":
            session.state = "ready"
        return session

    async def _run(
        self,
        session_id: str,
        client_id: str,
        callback_port: int,
        on_url: Callable[[str], None],
        url_future: asyncio.Future[str],
    ) -> None:
        """Background task: drives the SDK to completion, captures result."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        try:
            builder = self._builder_factory(client_id, callback_port)
            # ``build_async`` returns once the user completes the browser
            # flow (or never, if they walk away — hence the outer timeout).
            await asyncio.wait_for(
                builder.build_async(on_url),
                timeout=self._auth_timeout,
            )
            session.state = "success"
        except asyncio.CancelledError:
            session.state = "cancelled"
            raise
        except Exception as e:
            session.state = "error"
            session.error = str(e) or repr(e)
            # Surface the URL-capture failure too if it hadn't fired.
            if not url_future.done():
                url_future.set_exception(e)
        finally:
            # Clear current pointer if this is still the active session, so
            # the next start() doesn't pointlessly cancel a finished task.
            if self._current == session_id:
                self._current = None

    async def _cancel(self, session_id: str) -> None:
        """Cancel an in-flight task and wait for it to release its port."""
        task = self._tasks.get(session_id)
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        session = self._sessions.get(session_id)
        if session is not None and session.state in ("awaiting_url", "ready"):
            session.state = "cancelled"

    async def cancel(self, session_id: str) -> None:
        """Public: cancel a session by id (e.g., user closed the modal)."""
        await self._cancel(session_id)
