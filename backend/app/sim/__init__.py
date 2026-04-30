"""app.sim — scripted scenarios that exercise the real bus → parser → DB → WS pipeline.

The simulator constructs a synthetic ``Message``, publishes
``MESSAGE_RECEIVED`` so the real parser runs, then (when the scenario has
push steps) skips the broker submit step (assigning a fake order_id) and
feeds prebuilt ``PushOrderChanged``-shaped objects through
``PushListener._handle_raw_push``.

Everything else — storage listeners, WebSocket bridge, frontend rendering —
runs unchanged. So a "simulated card" is observationally identical to a
real one as far as the UI is concerned.
"""

from app.sim.scenarios import SCENARIOS, Scenario, ScenarioOverview, list_scenarios
from app.sim.runner import SimRunResult, run_scenario

__all__ = [
    "SCENARIOS",
    "Scenario",
    "ScenarioOverview",
    "SimRunResult",
    "list_scenarios",
    "run_scenario",
]
