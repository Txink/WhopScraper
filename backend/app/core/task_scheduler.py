"""Asyncio-based periodic task scheduler.

Centralises long-running background jobs (cache refreshers, heartbeat
loops, periodic cleanups) so each consumer doesn't have to roll its own
``asyncio.create_task`` + cancellation lifecycle.

Each registered job runs in its own task with an independent fixed
interval; jobs are isolated — an exception in one tick is logged and
the next tick still fires. Lifecycle is start/stop, owned by the FastAPI
lifespan in :mod:`app.main`.

Future additions (e.g. cron-style expressions, calendar triggers) can
slot in as new ``add_*`` methods without changing this minimal core.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Scheduler discards the awaitable's return value, so jobs may return
# anything (e.g. ``MarketSchedule.maybe_refresh`` returns ``bool``).
JobFn = Callable[[], Awaitable[Any]]


@dataclass
class _Job:
    name: str
    fn: JobFn
    interval_seconds: float
    initial_delay: float = 0.0
    task: asyncio.Task[None] | None = field(default=None, repr=False)


class TaskScheduler:
    """Owns a set of periodic async jobs.

    Usage::

        sched = TaskScheduler()
        sched.add_job("market_refresh", schedule.maybe_refresh,
                      interval_seconds=3600, initial_delay=0)
        await sched.start()
        ...
        await sched.stop()

    Idempotent: a second ``start()`` is a no-op, ``stop()`` after stop
    is a no-op. Adding jobs after ``start()`` is supported — they are
    spawned immediately.
    """

    def __init__(self) -> None:
        self._jobs: list[_Job] = []
        self._started = False

    def add_job(
        self,
        name: str,
        fn: JobFn,
        *,
        interval_seconds: float,
        initial_delay: float = 0.0,
    ) -> None:
        """Register a coroutine to run every ``interval_seconds``.

        ``initial_delay=0`` (default) means the job fires once
        immediately on start; otherwise the first tick waits that many
        seconds. Exceptions are logged and swallowed so a single broker
        blip doesn't take the loop down.
        """
        job = _Job(
            name=name,
            fn=fn,
            interval_seconds=interval_seconds,
            initial_delay=initial_delay,
        )
        self._jobs.append(job)
        if self._started:
            job.task = asyncio.create_task(
                self._run_job(job), name=f"sched:{job.name}",
            )

    async def start(self) -> None:
        """Spawn one background task per registered job."""
        if self._started:
            return
        self._started = True
        for job in self._jobs:
            job.task = asyncio.create_task(
                self._run_job(job), name=f"sched:{job.name}",
            )

    async def stop(self) -> None:
        """Cancel all jobs and wait for them to unwind."""
        if not self._started:
            return
        self._started = False
        tasks = [j.task for j in self._jobs if j.task is not None]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                logger.warning("TaskScheduler: job teardown raised: %s", exc)
        for j in self._jobs:
            j.task = None

    async def _run_job(self, job: _Job) -> None:
        if job.initial_delay > 0:
            try:
                await asyncio.sleep(job.initial_delay)
            except asyncio.CancelledError:
                return
        while True:
            try:
                await job.fn()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("TaskScheduler: job '%s' raised", job.name)
            try:
                await asyncio.sleep(job.interval_seconds)
            except asyncio.CancelledError:
                return
