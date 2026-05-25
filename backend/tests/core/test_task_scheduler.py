"""Tests for core/task_scheduler.py — asyncio periodic-job manager."""

from __future__ import annotations

import asyncio

import pytest

from app.core.task_scheduler import TaskScheduler


@pytest.mark.asyncio
async def test_job_runs_repeatedly_on_interval() -> None:
    sched = TaskScheduler()
    counter = {"n": 0}

    async def tick() -> None:
        counter["n"] += 1

    sched.add_job("tick", tick, interval_seconds=0.05)
    await sched.start()
    await asyncio.sleep(0.22)
    await sched.stop()

    # ~4 ticks expected (initial + ~3 intervals). Loose lower bound to
    # avoid flakiness on slow CI.
    assert counter["n"] >= 3


@pytest.mark.asyncio
async def test_initial_delay_zero_fires_immediately() -> None:
    """A long-interval job with initial_delay=0 should run once on start
    before the first sleep. Mirrors our market-schedule use case where the
    cache must be warm ASAP."""
    sched = TaskScheduler()
    counter = {"n": 0}

    async def tick() -> None:
        counter["n"] += 1

    sched.add_job("tick", tick, interval_seconds=10.0, initial_delay=0)
    await sched.start()
    await asyncio.sleep(0.05)
    await sched.stop()

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_job_error_is_logged_but_does_not_kill_scheduler() -> None:
    """An exception in one tick must not stop subsequent ticks — the
    scheduler is meant to survive transient broker / network failures."""
    sched = TaskScheduler()
    counter = {"n": 0}

    async def flaky() -> None:
        counter["n"] += 1
        if counter["n"] == 1:
            raise RuntimeError("transient blip")

    sched.add_job("flaky", flaky, interval_seconds=0.05)
    await sched.start()
    await asyncio.sleep(0.22)
    await sched.stop()

    assert counter["n"] >= 3


@pytest.mark.asyncio
async def test_stop_cancels_running_jobs() -> None:
    sched = TaskScheduler()
    counter = {"n": 0}

    async def tick() -> None:
        counter["n"] += 1

    sched.add_job("tick", tick, interval_seconds=0.05)
    await sched.start()
    await asyncio.sleep(0.12)
    await sched.stop()

    n_after_stop = counter["n"]
    await asyncio.sleep(0.15)
    # No new ticks should fire after stop returned.
    assert counter["n"] == n_after_stop


@pytest.mark.asyncio
async def test_multiple_jobs_run_independently() -> None:
    sched = TaskScheduler()
    fast = {"n": 0}
    slow = {"n": 0}

    async def tick_fast() -> None:
        fast["n"] += 1

    async def tick_slow() -> None:
        slow["n"] += 1

    sched.add_job("fast", tick_fast, interval_seconds=0.05)
    sched.add_job("slow", tick_slow, interval_seconds=0.15)
    await sched.start()
    await asyncio.sleep(0.35)
    await sched.stop()

    assert fast["n"] > slow["n"]
    assert slow["n"] >= 2


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    """Calling start() twice must not double-schedule jobs."""
    sched = TaskScheduler()
    counter = {"n": 0}

    async def tick() -> None:
        counter["n"] += 1

    sched.add_job("tick", tick, interval_seconds=0.05)
    await sched.start()
    await sched.start()  # second start is a no-op
    await asyncio.sleep(0.18)
    await sched.stop()

    # If start had double-scheduled we'd see ~6-8 ticks; bound to single
    # scheduling.
    assert counter["n"] <= 5
