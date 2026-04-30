# Whop Listener Status Events — Design

**Date:** 2026-05-01
**Branch:** refactor-v2

## Problem

The 监控页 (Dashboard) top-bar power button (`PageActionBar` 中的 `power-btn`) only repaints
its tri-state (off / on / err) when the user explicitly clicks 开机/关机/重启 — i.e. when
`WhopRegistry` publishes a `whop.page_changed` event triggered by a user action.

If the underlying `WhopListener` polling loop transitions to an error state on its own
(network drop, browser crash, scrape exception), the button stays green. The listener
sets `_last_error = str(e)` internally and keeps retrying with exponential backoff, but
no event is published, so neither the WS nor the frontend ever learn about the change.

Conversely, if the listener recovers from an error on a later successful scan, the
button does not transition back from red → green either.

## Goal

Make the existing power button reflect listener state transitions in real time, with
**no frontend changes** and the smallest possible backend surface.

Out of scope (YAGNI):

- Periodic heartbeat updates of `last_poll_at` to the frontend (relative-time rendering
  is sufficient).
- "Listener task is alive but hasn't successfully polled in N minutes" silent-failure
  detection. The current `except Exception` branch in `_loop` covers all real-world
  failure modes; users who want a faster signal can click 重启.
- Any UI surface beyond the existing `PageActionBar` button.

## Existing Pipeline (already wired, no changes)

```
WhopRegistry._publish_page_event
  → EventBus
  → /ws  (Topics.WHOP_PAGE_CHANGED forwarded by app/api/ws.py)
  → frontend WS client (App.tsx onEvent)
  → usePageTabsStore.applyPageChanged
  → App.activePage  (derived: pages.find(p => p.id === activeTabId))
  → PageActionBar(page=activePage)  ← reads page.running / page.last_error
```

The frontend store's `applyPageChanged` already handles unknown actions via a
"replace in place" else branch (see `frontend/src/stores/pageTabs.ts:78-81`), so any
new action string is absorbed with no code change.

## Design

### Data flow added

```
WhopListener._loop  (state transition detected)
  → on_status_change("errored" | "recovered")    [new: injected callback]
  → registry._make_status_callback closure
      → acquire registry._lock
      → _build_page_dict(entry)                  [existing helper]
      → release lock
      → _publish_page_event(action, page_dict)   [existing helper]
  → existing pipeline above carries it to the button
```

### Backend changes

**1. `backend/app/whop/listener.py`**

Add a constructor parameter:

```python
on_status_change: Callable[[str], Awaitable[None]] | None = None
```

Store it as `self._on_status_change`. Two call sites inside the polling loop:

- **Healthy → errored.** In `_loop`'s `except Exception as e:` branch, **before**
  `self._last_error = str(e)`:
    ```python
    if self._last_error is None:
        await self._safe_status_callback("errored")
    ```
- **Errored → recovered.** In `_scan_once`, replace the existing
  `self._last_error = None` with:
    ```python
    prev_error = self._last_error
    self._last_error = None
    if prev_error is not None:
        await self._safe_status_callback("recovered")
    ```

`_safe_status_callback(action)` is a helper that wraps the call:

```python
async def _safe_status_callback(self, action: str) -> None:
    cb = self._on_status_change
    if cb is None:
        return
    try:
        await cb(action)
    except Exception as e:  # noqa: BLE001
        logger.warning("WhopListener[%s] status callback failed: %s",
                       self._source, e)
```

Failure of the callback must not crash or stall the polling loop.

**2. `backend/app/whop/registry.py`**

In `_start_listener`, inject the callback:

```python
listener = WhopListener(
    ...,
    on_status_change=self._make_status_callback(entry.id),
)
```

Add the closure factory:

```python
def _make_status_callback(self, page_id: str) -> Callable[[str], Awaitable[None]]:
    async def _on_status(action: str) -> None:
        async with self._lock:
            entry = self._entries.get(page_id)
            if entry is None:
                return                              # entry was removed
            page_dict = self._build_page_dict(entry)
        await self._publish_page_event(action, page_dict)
    return _on_status
```

Action names sit alongside the registry's existing vocabulary
(`added` / `removed` / `started` / `stopped` / `restarted` / `settings_updated`):

- `"errored"` — first scan failure since the listener was last healthy.
- `"recovered"` — first successful scan after one or more failures.

### Frontend changes

**None.** `usePageTabsStore.applyPageChanged` already routes unknown actions
through its else branch which calls `pages.map(x => x.id === page.id ? page : x)`.
The replaced `page` carries fresh `running` and `last_error` fields, which
`PageActionBar` already uses to compute the tri-state class.

### Concurrency / deadlock analysis

The callback acquires `registry._lock`. Failure modes considered:

1. **Listener task fires the callback during a `stop_page` / `restart_page` call.**
   The mutating registry method holds `_lock` and `await listener.stop()` from
   inside it. `listener.stop()` cancels the polling task. If the task happens to
   be inside `_safe_status_callback` waiting on `_lock.acquire()`, the
   `CancelledError` propagates through the acquire and unwinds correctly — no
   deadlock, lock is not held by the cancelled task. The `contextlib.suppress`
   in `WhopListener.stop` already handles the propagating cancel.

2. **Listener task currently holds `_lock` (inside the callback) when stop is
   called.** The mutating registry method tries to acquire `_lock` and waits.
   The listener task completes its publish and releases the lock; the mutating
   call then proceeds. No deadlock, brief contention only.

3. **Callback raises.** `_safe_status_callback` swallows it. Loop continues.

### Test plan

**Listener unit test** (`backend/tests/whop/test_listener.py`):

- Inject a fake browser whose `scrape_html` raises on calls 1 and 2 and returns
  empty HTML on call 3.
- Inject a stub `on_status_change` that records every call.
- Run the listener for ~3 poll cycles, then stop.
- Assert exactly two callback invocations: `["errored", "recovered"]`. Not three,
  not one.

**Registry unit test** (`backend/tests/whop/test_registry.py`):

- Build a registry with a real `EventBus`, subscribe a recorder.
- Manually invoke `registry._make_status_callback("some-page-id")("errored")`
  on a registry that has an entry with that id (no live listener needed for
  this test — `_build_page_dict` works off the entry).
- Assert one `WHOP_PAGE_CHANGED` event was published with `action == "errored"`,
  `payload["page_dict"]["id"] == "some-page-id"`.
- Repeat for `"recovered"`.
- Edge case: invoke the callback for a `page_id` that does not exist in the
  registry — assert no event is published, no exception raised.

**No frontend test changes required.** The existing `pageTabs.test.ts` already
covers replace-in-place behaviour for unknown actions.

## Files touched (estimate)

| File | LOC | Kind |
|------|-----|------|
| `backend/app/whop/listener.py` | ~25 | new field, two call sites, helper |
| `backend/app/whop/registry.py` | ~15 | closure factory, one call site |
| `backend/tests/whop/test_listener.py` | ~30 | one new test |
| `backend/tests/whop/test_registry.py` | ~25 | one new test (or two) |
| **Total** | **~95** | all backend |
