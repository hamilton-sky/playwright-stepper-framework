"""
actions/subflow.py — running another workflow from inside this one.

Split out of flow.py, which holds the dispatchers that run sub-steps *within*
the current plan. This one is a different job: it loads another plan off disk
and runs it, which is why it is session-agnostic (domain None) where every
dispatcher in flow.py acts on the web.

Pattern: Strategy + Template Method — the execute() skeleton lives on
ActionStrategy, the class below overrides _execute() only.
"""

from __future__ import annotations
import json
import logging
from pathlib import Path

from stepper.engine.interfaces import (
    ActionStrategy, StepConfig, StepResult, ExecutionContext,
)
from stepper.engine.utils import dict_to_step_config as _dict_to_step_config

logger = logging.getLogger(__name__)


class RunWorkflowAction(ActionStrategy):
    """
    Execute a sub-workflow JSON file at runtime, then return to the parent flow.

    Expected step.extra:
      path: str        # path to workflow JSON file (relative or absolute)
      vars: dict       # optional variable overrides for this subflow
      base_dir: str    # optional base dir for relative paths
    """
    action_name = "run_workflow"
    domain      = None  # session-agnostic

    def __init__(self, run_steps_callable=None, base_dir: Path | None = None):
        self._run_steps = run_steps_callable
        self._base_dir = base_dir or Path.cwd()

    def bind(self, run_steps_callable):
        """
        Attach the runner's run() after construction.

        A plan can only be validated once every action it names is registered,
        but the runner cannot exist before its page does. Registering this
        action unbound and binding it here breaks that cycle, so validation
        happens before a browser is launched.
        """
        self._run_steps = run_steps_callable
        return self

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        from stepper.engine.planner.planner import _substitute

        if self._run_steps is None:
            return StepResult(
                step=step,
                status="failed",
                error="run_workflow: action was registered but never bound to a runner",
            )

        wf_path = (step.extra or {}).get("path") or (step.extra or {}).get("workflow")
        if not wf_path:
            return StepResult(
                step=step,
                status="failed",
                error="run_workflow: missing extra.path",
            )

        base_dir = self._base_dir
        if (step.extra or {}).get("base_dir"):
            base_dir = Path(step.extra["base_dir"])

        wf_path = Path(wf_path)
        if not wf_path.is_absolute():
            wf_path = (base_dir / wf_path).resolve()

        if not wf_path.exists():
            return StepResult(
                step=step,
                status="failed",
                error=f"run_workflow: file not found: {wf_path}",
            )

        with open(wf_path, encoding="utf-8") as f:
            data = json.load(f)

        steps_raw = data.get("steps", data) if isinstance(data, dict) else data
        if not isinstance(steps_raw, list):
            return StepResult(
                step=step,
                status="failed",
                error="run_workflow: workflow JSON must be a list or {steps:[...]}",
            )

        merged_vars = {
            **(data.get("variables", {}) if isinstance(data, dict) else {}),
            **((step.extra or {}).get("vars") or {}),
        }
        if merged_vars:
            steps_raw = _substitute(steps_raw, merged_vars)

        sub_steps = [_dict_to_step_config(s) for s in steps_raw]

        results, _ = await self._run_steps(sub_steps, context)
        failures = [r for r in results if r.status == "failed"]
        if failures:
            msg = failures[0].error or "subflow failed"
            return StepResult(step=step, status="failed", error=msg)

        return StepResult(step=step, status="passed")
