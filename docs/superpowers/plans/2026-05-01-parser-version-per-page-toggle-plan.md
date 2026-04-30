# parser_version per-page toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-page `parser_version` setting (`"v1" | "v2"`, default `"v1"`) wired from `PageSettings` → API → frontend `PageSettingsModal` checkbox, with `parser/service.py` branching on it per-message so changes take effect on the very next message with no restart.

**Architecture:** Add a single field to the existing `PageSettings` dataclass and tolerant to/from-dict pair, surface it through the existing `WhopPageSettingsOut` / `WhopPageSettingsPatch` Pydantic schemas and the existing PATCH endpoint, branch the stock-parser dispatch in `parser/service.py`, and add one checkbox to `PageSettingsModal.tsx`. No new endpoints, no new persistence path, no listener restart logic — settings are read fresh from the registry on every incoming message, so the toggle is real-time by construction. parser_v2 alias-flip (`app/parser_v2/__init__.py`) is **not** part of this plan; the toggle is plumbing only and becomes meaningful once the separate v2 implementation lands.

**Tech Stack:** Python 3.11 (FastAPI, pydantic, dataclasses, pytest, pytest-asyncio), TypeScript / React (vitest, @testing-library/react). No new dependencies.

**Reference spec:** `docs/superpowers/specs/2026-05-01-parser-version-per-page-toggle-design.md`

---

## File Map

**Modify:**
- `backend/app/whop/page_settings.py` — add field to `PageSettings`, default constants, `default_settings_for`, `page_settings_to_dict`, `page_settings_from_dict`
- `backend/app/api/schemas.py` — add field to `WhopPageSettingsOut`, `WhopPageSettingsPatch`, and `whop_page_to_out` builder
- `backend/app/api/http.py` — wire field through `whop_settings_defaults` and `patch_whop_page_settings`
- `backend/app/parser/service.py` — hoist `page_settings` lookup out of the watched-tickers branch; in the stock parse path, dispatch to `parser_v2.parse` when `page_settings.parser_version == "v2"`; add `parser_version` to telemetry log lines
- `frontend/src/api/domain-types.ts` — add `parser_version?: "v1" | "v2"` to `WhopPageSettings`
- `frontend/src/components/Dashboard/PageSettingsModal.tsx` — add state + checkbox + save patch field

**Test (modify, not create — these test files exist):**
- `backend/tests/whop/test_page_settings.py`
- `backend/tests/api/test_whop_settings.py`
- `backend/tests/parser/test_service.py`
- `frontend/src/components/Dashboard/PageSettingsModal.test.tsx`

---

## Conventions

- All Python commands run from `backend/` directory. The project venv is `backend/.venv/`.
- All `pytest` invocations use `.venv/bin/python -m pytest …`.
- All Vitest invocations run from `frontend/` and use `npx vitest run …`.
- Each task ends with a single commit.
- Commit messages follow conventional commits matching recent history: `feat(...)`, `test(...)`, `refactor(...)`.
- Co-author trailer matches recent commits: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- TDD: write failing test → confirm it fails → implement → confirm it passes → commit.

---

## Task 1: Add `parser_version` to `PageSettings` dataclass and (de)serializers

**Why:** The whole feature hangs off this field. Once it exists on the dataclass and survives the to_dict/from_dict round-trip with sensible default + sanitization, every later wiring step is a one-liner.

**Files:**
- Modify: `backend/app/whop/page_settings.py`
- Test: `backend/tests/whop/test_page_settings.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/whop/test_page_settings.py`:

```python
def test_default_stock_settings_parser_version_v1():
    assert DEFAULT_STOCK_SETTINGS.parser_version == "v1"


def test_default_option_settings_parser_version_v1():
    assert DEFAULT_OPTION_SETTINGS.parser_version == "v1"


def test_to_dict_writes_parser_version():
    s = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        block_historical_messages=False,
        launch_headless=False,
        tickers={},
        parser_version="v2",
    )
    d = page_settings_to_dict(s)
    assert d["parser_version"] == "v2"


def test_from_dict_reads_parser_version_v2():
    d = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "block_historical_messages": False,
        "launch_headless": False,
        "parser_version": "v2",
    }
    s = page_settings_from_dict(d, source="stock")
    assert s.parser_version == "v2"


def test_from_dict_missing_parser_version_defaults_to_v1():
    """Backward compat: settings JSON written before this field existed must
    deserialize cleanly with parser_version='v1'."""
    d = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "block_historical_messages": False,
        "launch_headless": False,
    }
    s = page_settings_from_dict(d, source="stock")
    assert s.parser_version == "v1"


def test_from_dict_unknown_parser_version_falls_back_to_v1():
    """Sanitization: any value other than 'v2' degrades to 'v1' so a corrupted
    or future-unknown saved value cannot crash the parser dispatcher."""
    d = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "block_historical_messages": False,
        "launch_headless": False,
        "parser_version": "v3",
    }
    s = page_settings_from_dict(d, source="stock")
    assert s.parser_version == "v1"


def test_round_trip_preserves_parser_version():
    src = PageSettings(
        dedupe_processed_messages=False,
        price_deviation_tolerance=0.7,
        block_historical_messages=True,
        launch_headless=True,
        tickers={"TSLL": TickerConfig(trade_quantity=2000)},
        parser_version="v2",
    )
    out = page_settings_from_dict(page_settings_to_dict(src), source="stock")
    assert out == src
    assert out.parser_version == "v2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/whop/test_page_settings.py -v -k "parser_version or round_trip_preserves_parser_version"`
Expected: 7 failing tests with `AttributeError: 'PageSettings' object has no attribute 'parser_version'` (or similar — the field doesn't exist yet).

- [ ] **Step 3: Add the field to the dataclass and defaults**

Edit `backend/app/whop/page_settings.py`:

Add `Literal` to the existing import (if `from typing import Any, Literal` is already there, no change is needed — it is, per `page_settings.py:10`).

In `class PageSettings`, append after `option_total_price_limit`:

```python
    parser_version: Literal["v1", "v2"] = "v1"
```

In `DEFAULT_STOCK_SETTINGS`, add `parser_version="v1"` to the kwargs.
In `DEFAULT_OPTION_SETTINGS`, add `parser_version="v1"` to the kwargs.

In `default_settings_for("stock")`, add `parser_version=DEFAULT_STOCK_SETTINGS.parser_version` to the kwargs.
In `default_settings_for("option")`, add `parser_version=DEFAULT_OPTION_SETTINGS.parser_version` to the kwargs.

In `page_settings_to_dict`, add to the `out` dict:

```python
        "parser_version": s.parser_version,
```

In `page_settings_from_dict`, add (before the `return PageSettings(...)`):

```python
    pv_raw = d.get("parser_version", base.parser_version)
    parser_version: Literal["v1", "v2"] = "v2" if pv_raw == "v2" else "v1"
```

Then add `parser_version=parser_version,` to the `PageSettings(...)` constructor call at the end of the function.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/whop/test_page_settings.py -v`
Expected: ALL tests pass (the 7 new ones + the existing ones — round-trip on existing tests must still pass because `parser_version` defaults to `"v1"` and survives round-trip).

- [ ] **Step 5: Commit**

```bash
git add backend/app/whop/page_settings.py backend/tests/whop/test_page_settings.py
git commit -m "$(cat <<'EOF'
feat(page_settings): add parser_version field with v1 default

Per-page Literal["v1","v2"] field on PageSettings, persisted via
to_dict/from_dict round-trip. Missing key in saved JSON → "v1"
(backward compat); unknown values → "v1" (sanitization).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Wire `parser_version` through API schemas and endpoints

**Why:** PATCH must accept `parser_version`, GET must return it, and the defaults endpoint must include it. Without this the frontend can't read or write the setting.

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/http.py`
- Test: `backend/tests/api/test_whop_settings.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/test_whop_settings.py`:

```python
# ---------------------------------------------------------------------------
# Tests — parser_version per-page toggle
# ---------------------------------------------------------------------------


def test_get_pages_includes_parser_version_default_v1(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """A freshly-added stock page reports parser_version='v1'."""
    _, client, stock, _ = registry_and_client
    resp = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert resp.status_code == 200
    pages = resp.json()["pages"]
    s = next(p["settings"] for p in pages if p["id"] == stock.id)
    assert s["parser_version"] == "v1"


def test_defaults_endpoint_includes_parser_version_v1(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """GET /api/whop/pages/defaults?source=stock includes parser_version='v1'."""
    _, client, _, _ = registry_and_client
    resp = client.get(
        "/api/whop/pages/defaults",
        params={"token": _TOKEN, "source": "stock"},
    )
    assert resp.status_code == 200
    assert resp.json()["parser_version"] == "v1"


def test_patch_parser_version_v2_persists(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """PATCH parser_version='v2' is reflected in the response and on the next GET."""
    _, client, stock, _ = registry_and_client
    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        params={"token": _TOKEN},
        json={"parser_version": "v2"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["settings"]["parser_version"] == "v2"

    # Re-read via list endpoint to confirm registry was updated
    resp2 = client.get("/api/whop/pages", params={"token": _TOKEN})
    s = next(p["settings"] for p in resp2.json()["pages"] if p["id"] == stock.id)
    assert s["parser_version"] == "v2"


def test_patch_parser_version_v1_reverts(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """PATCH v2 then v1 reverts cleanly."""
    _, client, stock, _ = registry_and_client
    client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        params={"token": _TOKEN},
        json={"parser_version": "v2"},
    )
    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        params={"token": _TOKEN},
        json={"parser_version": "v1"},
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["parser_version"] == "v1"


def test_patch_parser_version_invalid_value_rejected(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """Pydantic Literal validation rejects non-{v1,v2} values at the boundary."""
    _, client, stock, _ = registry_and_client
    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        params={"token": _TOKEN},
        json={"parser_version": "v3"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/api/test_whop_settings.py -v -k "parser_version"`
Expected: 5 failing tests. The first two will fail with `KeyError` or assertion mismatch (the field is not in the response). The PATCH ones will fail with 422 (Pydantic doesn't know about the field) or with the field absent in the response.

- [ ] **Step 3: Add field to Pydantic schemas**

Edit `backend/app/api/schemas.py`:

In `class WhopPageSettingsOut` (around line 261), add **after** `launch_headless: bool`:

```python
    parser_version: Literal["v1", "v2"] = "v1"
```

(Add `Literal` to the typing import at the top of the file if not already present.)

In `class WhopPageSettingsPatch` (around line 273), add after `launch_headless: bool | None = None`:

```python
    parser_version: Literal["v1", "v2"] | None = None
```

In the `whop_page_to_out` helper (around line 510-532), add to the `WhopPageSettingsOut(...)` constructor kwargs:

```python
        parser_version=entry.settings.parser_version,
```

- [ ] **Step 4: Wire through HTTP endpoints**

Edit `backend/app/api/http.py`:

In `whop_settings_defaults` (around line 515-540), add to the `WhopPageSettingsOut(...)` constructor kwargs:

```python
                parser_version=s.parser_version,
```

In `patch_whop_page_settings` (around line 542+, the `patch_dict` building block), add after the `launch_headless` block:

```python
            if body.parser_version is not None:
                patch_dict["parser_version"] = body.parser_version
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/api/test_whop_settings.py -v`
Expected: ALL tests pass — the 5 new ones plus all pre-existing ones (no regressions).

Also run the schema tests once: `.venv/bin/python -m pytest tests/api/test_schemas.py -v`
Expected: PASS (no regressions; schemas just gained a defaulted field).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/http.py backend/tests/api/test_whop_settings.py
git commit -m "$(cat <<'EOF'
feat(api): expose parser_version on whop page settings endpoints

WhopPageSettingsOut and Patch schemas, the defaults endpoint, and
patch_whop_page_settings all carry parser_version through. Pydantic
Literal validation rejects unknown values at the boundary.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Branch `parser/service.py` on `parser_version` + add telemetry

**Why:** The point of the toggle. Without this task the field is plumbed through but does nothing.

**Files:**
- Modify: `backend/app/parser/service.py`
- Test: `backend/tests/parser/test_service.py`

The current `service.py` already calls `registry.get_settings_for_url(msg.url)` for stock messages (`service.py:82-85`), but the variable is bound only inside that branch. We need it visible later for the parser dispatch. We also need to add a `parser_version` field to the structured log lines.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/parser/test_service.py` (after the existing tests, before any final newlines):

```python
# ---------------------------------------------------------------------------
# Tests — parser_version per-page toggle
# ---------------------------------------------------------------------------


def _fake_registry_with_parser_version(
    parser_version: str,
    tickers: set[str] | None = None,
) -> MagicMock:
    """Like _fake_registry but also sets parser_version on the returned settings."""
    registry = MagicMock()
    registry.get_settings_for_url.return_value = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={t: TickerConfig(trade_quantity=100) for t in (tickers or set())},
        parser_version=parser_version,  # type: ignore[arg-type]
    )
    return registry


@pytest.mark.asyncio
async def test_stock_parser_v1_called_when_parser_version_v1(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """parser_version='v1' (or no registry) → app.parser.stock_parser.parse is called,
    parser_v2.parse is NOT called."""
    from app.parser import service as service_mod
    from app.parser_v2 import parse as v2_parse_real  # noqa: F401

    v1_calls: list[str] = []
    v2_calls: list[str] = []

    real_v1 = service_mod.stock_parser.parse

    def fake_v1(content: str, *, message_id: str):
        v1_calls.append(message_id)
        return real_v1(content, message_id=message_id)

    def fake_v2(content: str, *, message_id: str):
        v2_calls.append(message_id)
        return None

    monkeypatch.setattr(service_mod.stock_parser, "parse", fake_v1)
    # parser_v2 is imported lazily inside the dispatch — patch the module attr
    import app.parser_v2 as v2_mod
    monkeypatch.setattr(v2_mod, "parse", fake_v2)

    bus = EventBus()
    register_parser_service(
        bus,
        session_factory,
        registry=_fake_registry_with_parser_version("v1", tickers={"TSLL"}),
    )

    msg = _stock_msg("v1-routed", "TSLL 26.5 买一半")
    await _run(bus, msg)

    assert v1_calls == ["v1-routed"]
    assert v2_calls == []


@pytest.mark.asyncio
async def test_parser_v2_called_when_parser_version_v2(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """parser_version='v2' → parser_v2.parse is called, stock_parser.parse is NOT."""
    from app.parser import service as service_mod
    import app.parser_v2 as v2_mod

    v1_calls: list[str] = []
    v2_calls: list[str] = []

    real_v2 = v2_mod.parse  # currently aliased to v1; we don't call it, just count

    def fake_v1(content: str, *, message_id: str):
        v1_calls.append(message_id)
        return None

    def fake_v2(content: str, *, message_id: str):
        v2_calls.append(message_id)
        return real_v2(content, message_id=message_id)

    monkeypatch.setattr(service_mod.stock_parser, "parse", fake_v1)
    monkeypatch.setattr(v2_mod, "parse", fake_v2)

    bus = EventBus()
    register_parser_service(
        bus,
        session_factory,
        registry=_fake_registry_with_parser_version("v2", tickers={"TSLL"}),
    )

    msg = _stock_msg("v2-routed", "TSLL 26.5 买一半")
    await _run(bus, msg)

    assert v2_calls == ["v2-routed"]
    assert v1_calls == []


@pytest.mark.asyncio
async def test_option_message_ignores_parser_version(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Option messages take the option branch regardless of parser_version,
    and parser_v2.parse is never called for them."""
    from app.parser import service as service_mod
    import app.parser_v2 as v2_mod

    v2_calls: list[str] = []

    def fake_v2(content: str, *, message_id: str):
        v2_calls.append(message_id)
        return None

    monkeypatch.setattr(v2_mod, "parse", fake_v2)

    bus = EventBus()
    register_parser_service(
        bus,
        session_factory,
        registry=_fake_registry_with_parser_version("v2"),
    )

    msg = _option_msg("opt-1", "NVDA 135C 本周 2.15 买")
    await _run(bus, msg)

    assert v2_calls == []  # option path never hits parser_v2


@pytest.mark.asyncio
async def test_stock_parser_v1_called_when_no_registry(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No registry → page_settings is None → falls back to v1 (safe default)."""
    from app.parser import service as service_mod
    import app.parser_v2 as v2_mod

    v1_calls: list[str] = []
    v2_calls: list[str] = []

    real_v1 = service_mod.stock_parser.parse

    def fake_v1(content: str, *, message_id: str):
        v1_calls.append(message_id)
        return real_v1(content, message_id=message_id)

    def fake_v2(content: str, *, message_id: str):
        v2_calls.append(message_id)
        return None

    monkeypatch.setattr(service_mod.stock_parser, "parse", fake_v1)
    monkeypatch.setattr(v2_mod, "parse", fake_v2)

    bus = EventBus()
    register_parser_service(bus, session_factory)  # no registry

    msg = _stock_msg("no-reg", "TSLL 26.5 买一半")
    await _run(bus, msg)

    assert v1_calls == ["no-reg"]
    assert v2_calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/parser/test_service.py -v -k "parser_version or parser_v1 or parser_v2 or no_registry or option_message_ignores"`
Expected: 4 failing tests. The `parser_v2` ones fail because the dispatch code branch doesn't exist yet — `v2_calls` stays empty even when `parser_version='v2'`. The `parser_v1` and `no_registry` ones may currently pass (v1 is already the only path), but they encode the contract going forward, so we keep them.

- [ ] **Step 3: Refactor service.py to dispatch on parser_version**

Edit `backend/app/parser/service.py`. Find the block at `service.py:79-99`:

```python
        # Per-page tickers for the stock fallback. orphan / option / no-registry
        # all collapse to an empty set, which the resolver treats as "no help".
        watched: set[str] = set()
        if msg.source == "stock" and registry is not None:
            page_settings = registry.get_settings_for_url(msg.url)
            if page_settings is not None and page_settings.tickers:
                watched = set(page_settings.tickers.keys())

        started = time.perf_counter()

        try:
            # --- Single-message parse ---
            parsed: Instruction | None
            if msg.source == "stock":
                parsed = stock_parser.parse(msg.content, message_id=msg.id)
            else:
                parsed = option_parser.parse(
                    msg.content,
                    message_id=msg.id,
                    message_posted_at=msg.posted_at,
                )
```

Replace with:

```python
        # Per-page settings. Looked up here once (not inside the try block) so
        # both the watched-ticker fallback and the parser-version dispatch can
        # use it. orphan / option / no-registry → page_settings is None.
        page_settings: PageSettings | None = None
        watched: set[str] = set()
        if msg.source == "stock" and registry is not None:
            page_settings = registry.get_settings_for_url(msg.url)
            if page_settings is not None and page_settings.tickers:
                watched = set(page_settings.tickers.keys())

        started = time.perf_counter()
        parser_version_used: str | None = None

        try:
            # --- Single-message parse ---
            parsed: Instruction | None
            if msg.source == "stock":
                if page_settings is not None and page_settings.parser_version == "v2":
                    import app.parser_v2 as parser_v2  # local import: avoid cycle
                    parsed = parser_v2.parse(msg.content, message_id=msg.id)
                    parser_version_used = "v2"
                else:
                    parsed = stock_parser.parse(msg.content, message_id=msg.id)
                    parser_version_used = "v1"
            else:
                parsed = option_parser.parse(
                    msg.content,
                    message_id=msg.id,
                    message_posted_at=msg.posted_at,
                )
```

Now also lift the `TYPE_CHECKING`-guarded import: change

```python
if TYPE_CHECKING:
    from app.whop.page_settings import PageSettings
```

at `service.py:38-39` — it's already there, so no change needed; the runtime annotation `page_settings: PageSettings | None = None` works because of `from __future__ import annotations` (confirm that line exists at the top of `service.py`; if missing, add it as the first non-docstring line).

Add `parser_version` to the existing telemetry log calls. Find the success path (where `task.attach_instruction(...)` is followed by `logger.info(...)` if any) and the failure path (`task.mark_parse_failed(...)`) and the exception path (`logger.exception(...)`). Augment each `logger.info` / `logger.exception` for stock messages with `extra={"parser_version": parser_version_used}` (option messages: `parser_version_used` is None). If a path has no log line today, **do not invent one** — limit the change to existing log calls.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/parser/test_service.py -v`
Expected: ALL tests pass — both the new dispatch tests and all pre-existing service tests.

Then run a broader sweep to make sure nothing in the parser pipeline regressed:

Run: `.venv/bin/python -m pytest tests/parser/ -v`
Expected: PASS (the v2-against-golden test still uses its own monkeypatched parse and is unaffected by this change).

- [ ] **Step 5: Commit**

```bash
git add backend/app/parser/service.py backend/tests/parser/test_service.py
git commit -m "$(cat <<'EOF'
feat(parser/service): dispatch stock parsing on page_settings.parser_version

Hoist page_settings lookup out of the watched-tickers branch so it's
available for parser dispatch. parser_version='v2' routes the stock
branch to parser_v2.parse; v1 / None / option keeps the existing path.
Telemetry: existing log lines now carry parser_version.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Frontend — type, checkbox, save wiring, test

**Why:** Without the UI the user has no way to flip the toggle. Backend is fully functional after Task 3 (curl/PATCH works), but the brief is "前端监控页设置添加一个勾选".

**Files:**
- Modify: `frontend/src/api/domain-types.ts`
- Modify: `frontend/src/components/Dashboard/PageSettingsModal.tsx`
- Test: `frontend/src/components/Dashboard/PageSettingsModal.test.tsx`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/Dashboard/PageSettingsModal.test.tsx`, inside the existing `describe("<PageSettingsModal>", () => { ... })` block:

```ts
  it("toggling parser_version checkbox saves it as v2", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(stockPage);
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    const checkbox = screen.getByLabelText(/parser v2/i);
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText(/^保存/));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.parser_version).toBe("v2");
  });

  it("checkbox initial state reflects existing parser_version=v2", async () => {
    const v2Page: WhopPage = {
      ...stockPage,
      settings: { ...stockPage.settings, parser_version: "v2" },
    };
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(v2Page);
    render(<PageSettingsModal page={v2Page} onClose={vi.fn()} />);
    const checkbox = screen.getByLabelText(/parser v2/i) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    fireEvent.click(checkbox); // unchecks
    fireEvent.click(screen.getByText(/^保存/));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.parser_version).toBe("v1");
  });
```

- [ ] **Step 2: Run tests to verify they fail**

From `frontend/`: `npx vitest run src/components/Dashboard/PageSettingsModal.test.tsx -t "parser v2"`
Expected: 2 failing tests — `getByLabelText(/parser v2/i)` throws because the checkbox doesn't exist; the second test additionally fails type-checking on `parser_version: "v2"` until Task Step 3.

- [ ] **Step 3: Add the field to the FE type**

Edit `frontend/src/api/domain-types.ts`. Find the `WhopPageSettings` interface/type and add:

```ts
  parser_version?: "v1" | "v2";
```

The `?` keeps the existing test fixtures (which omit the field) valid.

- [ ] **Step 4: Add state + checkbox + save wiring to PageSettingsModal**

Edit `frontend/src/components/Dashboard/PageSettingsModal.tsx`.

After the `launchHeadless` state declaration (`PageSettingsModal.tsx:16`), add:

```ts
  const [parserV2, setParserV2] = useState(page.settings.parser_version === "v2");
```

In the JSX, after the "用无头模式启动网页（Headless）" section (`PageSettingsModal.tsx:161-173`), add a new `<section>`:

```tsx
          <section>
            <label>
              <input
                type="checkbox"
                checked={parserV2}
                onChange={e => setParserV2(e.target.checked)}
              />
              <span>使用 parser v2（实验）</span>
            </label>
            <p className="hint small">
              切换后下一条消息即用新 parser 解析，无需重启监听。默认关闭。
            </p>
          </section>
```

In `handleSave` (`PageSettingsModal.tsx:59`), inside the `patch` object literal (around line 84-89), add:

```ts
        parser_version: parserV2 ? "v2" : "v1",
```

- [ ] **Step 5: Run tests to verify they pass**

From `frontend/`: `npx vitest run src/components/Dashboard/PageSettingsModal.test.tsx`
Expected: ALL tests pass — the 2 new ones plus the 8 existing ones.

Then a broader sweep:

From `frontend/`: `npx vitest run`
Expected: PASS (no regressions; the optional `parser_version?` field doesn't break existing fixtures).

Also run the typecheck:

From `frontend/`: `npx tsc --noEmit`
Expected: clean.

- [ ] **Step 6: Smoke-test in the browser**

This is a feature-correctness check that types/tests can't catch. Required before marking the plan done.

1. From `backend/`: `.venv/bin/python -m uvicorn app.main:app --reload --port 8000` (or whatever the project's existing dev command is — check `backend/Makefile` or root `Makefile` for `dev` / `run` targets).
2. From `frontend/`: `npm run dev`.
3. Open the dashboard, click into an existing stock page's settings modal.
4. Verify the new checkbox is visible with label "使用 parser v2（实验）" and is unchecked.
5. Tick it, click 保存, reopen the modal — the checkbox should still be ticked.
6. Tail the backend logs and post a stock message into the page (or use whatever existing replay/inject path the project supports). The log line should include `parser_version=v2` (or in a structured logger, `extra.parser_version="v2"`). Untick → log shows `v1`.
7. Restart backend; reopen modal — checkbox state survives restart (settings persisted via `registry._save_entries`).

If any of these fail, fix before committing.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/domain-types.ts frontend/src/components/Dashboard/PageSettingsModal.tsx frontend/src/components/Dashboard/PageSettingsModal.test.tsx
git commit -m "$(cat <<'EOF'
feat(ui): per-page parser v2 checkbox in PageSettingsModal

Surface page_settings.parser_version as an opt-in checkbox in the
settings modal. Reflects current state on open, saves "v1" or "v2"
through the existing PATCH path; takes effect on the next message
without restart.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final Verification

After all four tasks land:

- [ ] **Run the full backend test suite**

From `backend/`: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Run the full frontend test suite**

From `frontend/`: `npx vitest run && npx tsc --noEmit`
Expected: PASS.

- [ ] **Verify the spec's acceptance criteria are met**

Walk through the spec's "Edge Cases & Decisions" table mentally and confirm each row is exercised by a test or hand-verified in the smoke test:

| Spec row | Where verified |
|----------|----------------|
| Settings file without `parser_version` → `"v1"` | `test_from_dict_missing_parser_version_defaults_to_v1` |
| Unknown saved value → `"v1"` | `test_from_dict_unknown_parser_version_falls_back_to_v1` |
| `parser_version="v2"` while alias not flipped | Task 3 tests verify dispatch routing; v2 alias state is documented as separate concern |
| Option page with `parser_version` set | `test_option_message_ignores_parser_version` |
| Switch in a high-traffic moment | Inherent to per-message lookup; no test (race-free by construction) |
| Restart preserves state | Task 4 smoke-test step 7 |

If any row has no verifier, add one before declaring the plan done.
