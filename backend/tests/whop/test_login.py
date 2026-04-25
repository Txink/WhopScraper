from pathlib import Path

import pytest

from app.whop.login import cookie_path, load_cookie_state, login_if_needed, save_cookie_state


def test_cookie_path_default_under_project_root():
    p = cookie_path()
    assert p.name == "whop_cookie.json"
    assert p.parent.name == ".auth"


def test_load_cookie_state_returns_none_when_missing(tmp_path: Path):
    assert load_cookie_state(tmp_path / "nonexistent.json") is None


def test_load_cookie_state_handles_invalid_json(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert load_cookie_state(bad) is None


def test_save_then_load_round_trip(tmp_path: Path):
    p = tmp_path / "auth" / "cookie.json"
    state = {"cookies": [{"name": "session", "value": "abc"}], "origins": []}
    save_cookie_state(state, p)
    assert p.is_file()
    loaded = load_cookie_state(p)
    assert loaded == state


@pytest.mark.asyncio
async def test_login_if_needed_skips_when_already_logged_in():
    saved: list[dict] = []

    async def is_logged() -> bool:
        return True

    async def interactive_login() -> dict:
        raise AssertionError("should not be called")

    result = await login_if_needed(is_logged, interactive_login, save=saved.append)
    assert result is False
    assert saved == []


@pytest.mark.asyncio
async def test_login_if_needed_runs_interactive_when_not_logged_in():
    saved: list[dict] = []

    async def is_logged() -> bool:
        return False

    async def interactive_login() -> dict:
        return {"cookies": [{"name": "session", "value": "fresh"}]}

    result = await login_if_needed(is_logged, interactive_login, save=saved.append)
    assert result is True
    assert saved == [{"cookies": [{"name": "session", "value": "fresh"}]}]
