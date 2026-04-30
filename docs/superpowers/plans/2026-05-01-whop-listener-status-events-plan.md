# Whop Listener Status Events — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 监控页 power button reflect listener health changes in real time by having `WhopListener` emit `whop.page_changed` events with action `errored` / `recovered` whenever its scan loop transitions between healthy and failing.

**Architecture:** Backend-only change. `WhopListener` gains an injected `on_status_change` callback. `WhopRegistry._start_listener` provides a closure that publishes `WHOP_PAGE_CHANGED` via the existing bus pipeline. Frontend `usePageTabsStore.applyPageChanged` already absorbs unknown actions through its replace-in-place fallback, so no UI code changes.

**Tech Stack:** Python 3.11, asyncio, FastAPI, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-01-whop-listener-status-events-design.md`

---

## File Structure

| File | Role | Change |
|------|------|--------|
| `backend/app/whop/listener.py` | polling loop, status props | add `on_status_change` ctor param, `_safe_status_callback` helper, two call sites in `_loop` / `_scan_once` |
| `backend/app/whop/registry.py` | manages entries + listeners | add `_make_status_callback` factory, inject result in `_start_listener` |
| `backend/tests/whop/test_listener.py` | listener unit tests | add `_ScriptedBrowser` helper + 3 new tests |
| `backend/tests/whop/test_registry.py` | registry unit tests | add 2 new tests |

No frontend changes. No new files.

---

## Task 1: Add `on_status_change` field + `_safe_status_callback` helper to `WhopListener`

This task adds the plumbing only — no behavior change. Tests assert the wrapper swallows exceptions and tolerates `None`.

**Files:**
- Modify: `backend/app/whop/listener.py`
- Test: `backend/tests/whop/test_listener.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/whop/test_listener.py`:

```python
@pytest.mark.asyncio
async def test_safe_status_callback_noop_when_none() -> None:
    """_safe_status_callback returns silently when no callback is wired."""
    listener = WhopListener(
        bus=EventBus(),
        url="http://test",
        source="stock",
        poll_interval=0.05,
        on_status_change=None,
    )
    # Should not raise.
    await listener._safe_status_callback("errored")


@pytest.mark.asyncio
async def test_safe_status_callback_swallows_exceptions(caplog) -> None:
    """A raising callback must not propagate — it's logged and absorbed."""
    async def boom(_action: str) -> None:
        raise RuntimeError("intentional")

    listener = WhopListener(
        bus=EventBus(),
        url="http://test",
        source="stock",
        poll_interval=0.05,
        on_status_change=boom,
    )
    with caplog.at_level("WARNING"):
        await listener._safe_status_callback("errored")
    assert any("status callback failed" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/test_listener.py::test_safe_status_callback_noop_when_none \
                tests/whop/test_listener.py::test_safe_status_callback_swallows_exceptions -v
```

Expected: FAIL — `WhopListener.__init__()` got an unexpected keyword argument `on_status_change`, OR `AttributeError: '_safe_status_callback'`.

- [ ] **Step 3: Add the import**

In `backend/app/whop/listener.py`, near the top with the other imports (after `import logging`, before `from datetime import ...`):

```python
from collections.abc import Awaitable, Callable
```

- [ ] **Step 4: Add the constructor param**

Edit `backend/app/whop/listener.py` `WhopListener.__init__` signature. After the existing `session_factory` param, add a new param. Replace the existing block:

```python
        skip_initial: bool = True,
        dedupe_processed_messages: bool = True,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
```

with:

```python
        skip_initial: bool = True,
        dedupe_processed_messages: bool = True,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        on_status_change: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
```

In the body, after `self._session_factory = session_factory`, add:

```python
        self._on_status_change = on_status_change
```

- [ ] **Step 5: Add `_safe_status_callback` helper**

Edit `backend/app/whop/listener.py`. Insert this method anywhere in the `WhopListener` class — placing it just before `async def _prime_dedupe(self)` keeps it near the other internal coroutines:

```python
    async def _safe_status_callback(self, action: str) -> None:
        """Invoke on_status_change(action) without ever propagating an exception.

        Swallowing failures keeps the polling loop alive even if the registry
        callback (or its downstream EventBus subscribers) misbehaves.
        """
        cb = self._on_status_change
        if cb is None:
            return
        try:
            await cb(action)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "WhopListener[%s] status callback failed: %s", self._source, e
            )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/test_listener.py::test_safe_status_callback_noop_when_none \
                tests/whop/test_listener.py::test_safe_status_callback_swallows_exceptions -v
```

Expected: 2 passed.

- [ ] **Step 7: Run the full listener suite to confirm no regressions**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/test_listener.py -v
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add backend/app/whop/listener.py backend/tests/whop/test_listener.py
git commit -m "feat(whop): add on_status_change callback + safe wrapper to WhopListener"
```

---

## Task 2: Fire `errored` on healthy → errored transition

**Files:**
- Modify: `backend/app/whop/listener.py` (the `_loop` except branch)
- Test: `backend/tests/whop/test_listener.py`

- [ ] **Step 1: Add the `_ScriptedBrowser` helper to the test module**

This helper is reused in Task 3. Place it in `backend/tests/whop/test_listener.py` right after the existing `_FakeBrowser` class:

```python
class _ScriptedBrowser:
    """A WhopBrowser stand-in that runs a scripted sequence per scrape call.

    Each scrape consumes one entry from the script. Each entry is either:
        ("html", "<some html>")   — return that string
        ("raise", Exception)      — raise that exception

    Once the script is exhausted, the LAST entry is repeated forever — so a
    one-element ``[("raise", RuntimeError(...))]`` script gives an always-failing
    browser, and ``[("raise", err), ("html", "<html></html>")]`` fails once
    then succeeds forever.
    """

    def __init__(self, script: list[tuple[str, object]]) -> None:
        self._script = list(script)
        self._idx = 0
        self.closed = False

    async def start(self) -> None:
        return None

    async def navigate(self, url: str) -> bool:  # noqa: ARG002
        return True

    async def scrape_html(self) -> str:
        if self._idx < len(self._script):
            kind, val = self._script[self._idx]
            self._idx += 1
        else:
            kind, val = self._script[-1]
        if kind == "raise":
            raise val if isinstance(val, Exception) else RuntimeError(str(val))
        return str(val)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def patch_scripted_browser(monkeypatch):
    """Install a _ScriptedBrowser as the listener's WhopBrowser.

    Usage:
        patch_scripted_browser([("raise", RuntimeError("boom"))])
    """
    def _setup(script: list[tuple[str, object]]) -> None:
        def _factory(*args, **kwargs) -> _ScriptedBrowser:  # noqa: ARG001
            return _ScriptedBrowser(script)
        monkeypatch.setattr("app.whop.listener.WhopBrowser", _factory)
    return _setup
```

- [ ] **Step 2: Write the failing test**

Append to `backend/tests/whop/test_listener.py`:

```python
@pytest.mark.asyncio
async def test_errored_callback_fires_once_on_first_failure(patch_scripted_browser) -> None:
    """A failing scrape transitions healthy → errored and fires the callback exactly once.

    Subsequent failures inside the same error streak must NOT fire again, because
    nothing has actually transitioned.
    """
    patch_scripted_browser([("raise", RuntimeError("net down"))])

    actions: list[str] = []

    async def record(action: str) -> None:
        actions.append(action)

    listener = WhopListener(
        bus=EventBus(),
        url="http://test",
        source="stock",
        poll_interval=0.05,
        skip_initial=False,
        dedupe_processed_messages=False,
        on_status_change=record,
    )
    await listener.start()
    # 0.3s lets the first scan run + sets last_error; backoff is 1.0s so the
    # second attempt has not started yet.
    await asyncio.sleep(0.3)
    await listener.stop()

    assert actions == ["errored"], f"expected ['errored'], got {actions}"
    assert listener.last_error == "net down"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/test_listener.py::test_errored_callback_fires_once_on_first_failure -v
```

Expected: FAIL — `assert [] == ['errored']` (callback was never invoked).

- [ ] **Step 4: Wire the `errored` callback in `_loop`**

Edit `backend/app/whop/listener.py`, the `_loop` method's `except Exception as e:` block. Replace:

```python
            except Exception as e:
                self._last_error = str(e)
                logger.exception("WhopListener[%s] scan error: %s", self._source, e)
                # Exponential backoff
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
```

with:

```python
            except Exception as e:
                # Fire the "errored" event ONLY on the healthy → errored transition,
                # i.e. when last_error was previously None. Subsequent failures inside
                # the same error streak just refresh the message — no event.
                if self._last_error is None:
                    await self._safe_status_callback("errored")
                self._last_error = str(e)
                logger.exception("WhopListener[%s] scan error: %s", self._source, e)
                # Exponential backoff
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/test_listener.py::test_errored_callback_fires_once_on_first_failure -v
```

Expected: PASS.

- [ ] **Step 6: Run the full listener suite**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/test_listener.py -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/whop/listener.py backend/tests/whop/test_listener.py
git commit -m "feat(whop): publish errored event on healthy→errored transition"
```

---

## Task 3: Fire `recovered` on errored → healthy transition

**Files:**
- Modify: `backend/app/whop/listener.py` (the `_scan_once` reset block)
- Test: `backend/tests/whop/test_listener.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/whop/test_listener.py`:

```python
@pytest.mark.asyncio
async def test_errored_then_recovered_callback_sequence(patch_scripted_browser) -> None:
    """One failure followed by a success fires ['errored', 'recovered'] in order.

    The recovery scan happens after the 1.0s backoff that follows the first failure,
    so we sleep 1.5s to give it time to land. Subsequent successful scans inside the
    same healthy streak must NOT fire 'recovered' again — only the transition counts.
    """
    patch_scripted_browser([
        ("raise", RuntimeError("blip")),
        ("html", "<html></html>"),
    ])

    actions: list[str] = []

    async def record(action: str) -> None:
        actions.append(action)

    listener = WhopListener(
        bus=EventBus(),
        url="http://test",
        source="stock",
        poll_interval=0.05,
        skip_initial=False,
        dedupe_processed_messages=False,
        on_status_change=record,
    )
    await listener.start()
    await asyncio.sleep(1.5)
    await listener.stop()

    assert actions == ["errored", "recovered"], f"expected ['errored','recovered'], got {actions}"
    assert listener.last_error is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/test_listener.py::test_errored_then_recovered_callback_sequence -v
```

Expected: FAIL — `assert ['errored'] == ['errored', 'recovered']` (the recovery callback is never wired yet).

- [ ] **Step 3: Wire the `recovered` callback in `_scan_once`**

Edit `backend/app/whop/listener.py`. Find the end of `_scan_once`. Replace:

```python
        self._last_poll_at = datetime.now(UTC)
        self._last_error = None

        if new_count > 0:
```

with:

```python
        self._last_poll_at = datetime.now(UTC)
        prev_error = self._last_error
        self._last_error = None
        if prev_error is not None:
            # errored → healthy transition. Fire AFTER clearing _last_error so any
            # observer that reads listener state inside the callback sees the
            # post-recovery snapshot.
            await self._safe_status_callback("recovered")

        if new_count > 0:
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/test_listener.py::test_errored_then_recovered_callback_sequence -v
```

Expected: PASS.

- [ ] **Step 5: Add a "no spurious recovered on fresh start" guard test**

Append to `backend/tests/whop/test_listener.py`:

```python
@pytest.mark.asyncio
async def test_no_recovered_callback_on_fresh_healthy_start(patch_scripted_browser) -> None:
    """A listener that never errored must NOT fire 'recovered' on its first success."""
    patch_scripted_browser([("html", "<html></html>")])

    actions: list[str] = []

    async def record(action: str) -> None:
        actions.append(action)

    listener = WhopListener(
        bus=EventBus(),
        url="http://test",
        source="stock",
        poll_interval=0.05,
        skip_initial=False,
        dedupe_processed_messages=False,
        on_status_change=record,
    )
    await listener.start()
    await asyncio.sleep(0.2)
    await listener.stop()

    assert actions == [], f"expected no callbacks on healthy startup, got {actions}"
```

Run it:

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/test_listener.py::test_no_recovered_callback_on_fresh_healthy_start -v
```

Expected: PASS (the gate `if prev_error is not None` already protects against this).

- [ ] **Step 6: Run the full listener suite**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/test_listener.py -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/whop/listener.py backend/tests/whop/test_listener.py
git commit -m "feat(whop): publish recovered event on errored→healthy transition"
```

---

## Task 4: Add `_make_status_callback` factory to `WhopRegistry` and wire it in `_start_listener`

**Files:**
- Modify: `backend/app/whop/registry.py`
- Test: `backend/tests/whop/test_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/whop/test_registry.py`:

```python
@pytest.mark.asyncio
async def test_status_callback_publishes_page_changed_event(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """Invoking the registry's status callback publishes a WHOP_PAGE_CHANGED event.

    No live listener required — the callback resolves the entry from the registry
    dict and uses _build_page_dict, which works off the entry alone.
    """
    from app.core.events import Topics, WhopPagePayload

    bus = EventBus()
    received: list[Event] = []

    async def capture(evt: Event) -> None:
        received.append(evt)

    bus.subscribe(Topics.WHOP_PAGE_CHANGED, capture)

    pages_file = tmp_path / "pages.json"
    registry = WhopRegistry(
        bus=bus, settings=settings_test, pages_file=pages_file
    )
    entry = await registry.add_page(url="http://example.com/x", source="stock", name="X")
    received.clear()  # discard the "added" event

    cb = registry._make_status_callback(entry.id)
    await cb("errored")
    await bus.wait_idle(timeout=1)

    assert len(received) == 1
    payload = received[0].payload
    assert isinstance(payload, WhopPagePayload)
    assert payload.action == "errored"
    assert payload.page_dict["id"] == entry.id


@pytest.mark.asyncio
async def test_status_callback_silent_when_entry_missing(
    patch_browser: None, settings_test: Settings, tmp_path: Path
) -> None:
    """If the entry was removed before the callback fires, no event is published and no exception bubbles up."""
    from app.core.events import Topics

    bus = EventBus()
    received: list[Event] = []

    async def capture(evt: Event) -> None:
        received.append(evt)

    bus.subscribe(Topics.WHOP_PAGE_CHANGED, capture)

    pages_file = tmp_path / "pages.json"
    registry = WhopRegistry(
        bus=bus, settings=settings_test, pages_file=pages_file
    )

    cb = registry._make_status_callback("nonexistent-id")
    await cb("errored")  # must not raise
    await bus.wait_idle(timeout=1)

    assert received == []
```

The test file already imports `Event` indirectly via fixtures, but make sure the top-of-file imports include it. If `Event` is not yet imported at module level, add to `backend/tests/whop/test_registry.py` near the existing imports:

```python
from app.core.event_bus import Event
```

(if not already present — check the existing import block first; do not duplicate.)

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/test_registry.py::test_status_callback_publishes_page_changed_event \
                tests/whop/test_registry.py::test_status_callback_silent_when_entry_missing -v
```

Expected: FAIL — `AttributeError: 'WhopRegistry' object has no attribute '_make_status_callback'`.

- [ ] **Step 3: Add the imports + factory method to `WhopRegistry`**

In `backend/app/whop/registry.py`, ensure the imports include `Awaitable` and `Callable` from `collections.abc`. Add (if not present) near the existing imports:

```python
from collections.abc import Awaitable, Callable
```

Then add the factory method to the `WhopRegistry` class. A natural location is right after `_publish_page_event` (around line 432), keeping the publish-related helpers grouped:

```python
    def _make_status_callback(self, page_id: str) -> Callable[[str], Awaitable[None]]:
        """Build the on_status_change callback that a listener invokes when its
        scan loop transitions between healthy and errored.

        The closure looks up the entry under the registry lock, snapshots its
        current page dict, then publishes a whop.page_changed event with the
        given action ("errored" or "recovered"). If the entry has already been
        removed by the time the callback fires, it returns silently — the
        listener is in the process of being torn down, so there's nothing to
        report.
        """
        async def _on_status(action: str) -> None:
            async with self._lock:
                entry = self._entries.get(page_id)
                if entry is None:
                    return
                page_dict = self._build_page_dict(entry)
            await self._publish_page_event(action, page_dict)

        return _on_status
```

- [ ] **Step 4: Wire the callback into `_start_listener`**

In `backend/app/whop/registry.py`, replace the `WhopListener(...)` construction in `_start_listener`:

```python
        listener = WhopListener(
            bus=self._bus,
            url=entry.url,
            source=entry.source,
            poll_interval=self._settings.whop_poll_interval,
            headless=entry.settings.launch_headless,
            skip_initial=skip_initial,
            dedupe_processed_messages=entry.settings.dedupe_processed_messages,
            session_factory=self._session_factory,
        )
```

with:

```python
        listener = WhopListener(
            bus=self._bus,
            url=entry.url,
            source=entry.source,
            poll_interval=self._settings.whop_poll_interval,
            headless=entry.settings.launch_headless,
            skip_initial=skip_initial,
            dedupe_processed_messages=entry.settings.dedupe_processed_messages,
            session_factory=self._session_factory,
            on_status_change=self._make_status_callback(entry.id),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/test_registry.py::test_status_callback_publishes_page_changed_event \
                tests/whop/test_registry.py::test_status_callback_silent_when_entry_missing -v
```

Expected: 2 passed.

- [ ] **Step 6: Run the full registry suite to confirm no regressions**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest tests/whop/ -v
```

Expected: all green (incl. the existing add_page / start_page / restart_page tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/whop/registry.py backend/tests/whop/test_registry.py
git commit -m "feat(whop): registry injects status callback so listener-internal transitions reach the bus"
```

---

## Task 5: Whole-suite verification + manual smoke check

**Files:** none (verification only).

- [ ] **Step 1: Run the entire backend test suite**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run pytest -v
```

Expected: all green. If any non-whop test regresses, investigate before declaring done.

- [ ] **Step 2: Type-check (if the project runs mypy / pyright)**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend && \
  uv run python -m mypy app/whop/listener.py app/whop/registry.py 2>&1 | tail -20
```

Expected: no new errors. If mypy isn't configured for this repo, skip.

- [ ] **Step 3 (optional manual): Browser smoke test**

This is a manual sanity check; skip if the engineer is confident from the unit tests alone.

1. Start the backend: `cd backend && uv run uvicorn app.main:app --reload`
2. Open the dashboard, click 开机 on a real Whop page tab. Power button turns green.
3. Force a network failure — easiest path is to pull the network cable / toggle wifi off, or manually edit `data/whop_pages.json` to point that page at a bogus URL and click 重启.
4. Within ~2× the poll interval (so a few seconds), the power button should go red. Hover: the tooltip shows the error message. This confirms the WS-driven repaint without a manual refresh.
5. Restore the network. The button should flip green within one poll cycle.

- [ ] **Step 4: Final review — verify plan is complete**

Confirm every spec section maps to merged code:

| Spec section | Implemented in |
|---|---|
| Listener `on_status_change` ctor param | Task 1 step 4 |
| `_safe_status_callback` helper | Task 1 step 5 |
| Healthy → errored fire | Task 2 step 4 |
| Errored → recovered fire | Task 3 step 3 |
| Registry `_make_status_callback` factory | Task 4 step 3 |
| Wired into `_start_listener` | Task 4 step 4 |
| No frontend change | (intentionally untouched) |
| Listener test: errored + recovered sequence | Task 2 + Task 3 tests |
| Registry test: publishes event | Task 4 step 1 |
| Registry test: silent when entry missing | Task 4 step 1 |

If anything is missing, return to that task before merging.

---

## Notes for the implementer

- **TDD discipline.** Each test is written and shown failing before the implementation step. Don't skip the "run and confirm fail" step — it confirms the test actually exercises the new code path.
- **The 1.5s sleep in Task 3** is unavoidable given the listener's 1.0s initial backoff. Don't reduce it further (will become flaky). Don't add a constructor knob to shrink the backoff — that's scope creep beyond the spec.
- **Don't touch the frontend.** The store's replace-in-place fallback already handles the new actions.
- **Watch for a subtle ordering issue in `_scan_once`.** The `recovered` callback fires *after* `self._last_error = None`, so any subscriber that synchronously snapshots `listener.last_error` inside the callback sees the post-recovery state. The spec calls this out; the implementation comment in Task 3 step 3 mirrors it. Don't reorder.
