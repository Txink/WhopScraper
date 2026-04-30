"""Simulator REST endpoints.

``GET  /api/sim/scenarios``        — list available scenarios
``POST /api/sim/run/{name}``       — kick off a scenario in the background;
                                     returns the synthetic message_id so the
                                     UI can scroll to / highlight the card

Auth shares the same ``require_app_token`` gate as the rest of the API.
The runner runs as a fire-and-forget asyncio task — REST returns
immediately, the actual push-step delays unfold over several seconds.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth import require_app_token
from app.core.event_bus import EventBus
from app.sim import SCENARIOS, list_scenarios, run_scenario
from app.sim.runner import build_scenario_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ScenarioOverviewOut(BaseModel):
    name: str
    label: str
    description: str
    source: str
    message_text: str
    push_step_count: int


class ScenariosOut(BaseModel):
    scenarios: list[ScenarioOverviewOut]


class SimRunOut(BaseModel):
    scenario_name: str
    message_id: str
    # Order id is only present once the synthetic submit step ran. ``null``
    # when the scenario halted at parse-only or before INSTRUCTION_READY.
    order_id: str | None = None
    started: bool = True


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def build_sim_router(
    *,
    bus: EventBus,
    session_factory: async_sessionmaker[AsyncSession],
    push_listener_getter: Callable[[], Any | None],
) -> APIRouter:
    """Build the /api/sim/* router.

    ``push_listener_getter`` is a closure rather than a static reference so
    we always pick up the current PushListener — the lifespan rebuilds it
    when the broker reloads (POST /api/longport/broker/reload).
    """
    router = APIRouter(dependencies=[Depends(require_app_token)])

    @router.get("/api/sim/scenarios", response_model=ScenariosOut)
    async def get_scenarios() -> ScenariosOut:
        return ScenariosOut(
            scenarios=[ScenarioOverviewOut(**s.__dict__) for s in list_scenarios()]
        )

    @router.post("/api/sim/run/{name}", response_model=SimRunOut)
    async def post_run_scenario(name: str) -> SimRunOut:
        if name not in SCENARIOS:
            raise HTTPException(status_code=404, detail=f"unknown scenario: {name}")

        # Build the synthetic Message synchronously so the response carries
        # the message_id for the UI to scroll to / highlight. The actual
        # pipeline run (parse → submit → push replay) goes to the background
        # because push delays span several seconds.
        msg = build_scenario_message(name)

        async def _runner() -> None:
            try:
                await run_scenario(
                    name,
                    msg,
                    bus=bus,
                    session_factory=session_factory,
                    push_listener=push_listener_getter(),
                )
            except Exception:
                logger.exception("sim: scenario %s crashed", name)

        # Note: keep a strong reference so the task isn't GC'd; asyncio
        # tracks running tasks weakly when only the create_task() return
        # value holds them.
        background_task = asyncio.create_task(_runner(), name=f"sim:{name}")
        # Hand the task to the bus's tracker so it survives until completion.
        # Bus tracks in-flight handlers via add_done_callback; for sim runs we
        # add it to a module-level set with the same eviction pattern.
        _SIM_TASKS.add(background_task)
        background_task.add_done_callback(_SIM_TASKS.discard)

        return SimRunOut(scenario_name=name, message_id=msg.id, order_id=None, started=True)

    return router


# Process-wide registry of in-flight sim runs — keeps asyncio.Tasks alive so
# the runtime doesn't GC them mid-execution.
_SIM_TASKS: set[asyncio.Task[None]] = set()
