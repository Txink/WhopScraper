"""APP_TOKEN authentication middleware for REST and WebSocket endpoints."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request

from app.core.config import Settings, get_settings


async def require_app_token(
    request: Request,
    token_q: Annotated[str | None, Query(alias="token")] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> None:
    """FastAPI dependency: 403 if no valid token is present.

    Token sources checked in priority order:
    1. Query param  ?token=<value>
    2. Header       Authorization: Bearer <value>
    3. Header       X-App-Token: <value>
    """
    assert settings is not None  # guaranteed by Depends(get_settings)
    expected: str = settings.app_token
    presented: str | None = token_q

    if presented is None:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            presented = auth_header[7:]

    if presented is None:
        presented = request.headers.get("x-app-token")

    if presented is None:
        raise HTTPException(status_code=403, detail="invalid or missing token")

    # hmac.compare_digest requires both args to be the same type (str or bytes).
    # Guard against type mismatch to avoid TypeError.
    try:
        valid = hmac.compare_digest(presented, expected)
    except TypeError:
        valid = False

    if not valid:
        raise HTTPException(status_code=403, detail="invalid or missing token")


async def ws_token_valid(token: str | None, settings: Settings) -> bool:
    """Pure check for WebSocket path.

    Returns False (caller should close with 403) when token is absent or wrong.
    """
    expected: str = settings.app_token
    if not token or not expected:
        return False
    try:
        return hmac.compare_digest(token, expected)
    except TypeError:
        return False
