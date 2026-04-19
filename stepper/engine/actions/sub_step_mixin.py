"""
engine/actions/sub_step_mixin.py — SubStepRunnerMixin

Shared sub-step dispatch logic for ActionStrategy subclasses that run nested
steps from workflow JSON at runtime (ForEachItemAction, EnsureLoginAction, etc.).

Pattern: Mixin
  Host classes gain sub-step dispatch without inheriting from a heavyweight base.
  Requires self._factory (ActionFactory) on the host class.
"""

from __future__ import annotations
import copy
import json
import logging

from engine.utils import dict_to_step_config as _dict_to_step_config

logger = logging.getLogger(__name__)


def _apply_substitutions(obj, subs: dict):
    """
    Recursively replace {{key}} tokens in a nested dict/list/str structure.

    Values in subs that are dicts or lists are serialised to JSON strings
    so they can be safely embedded into string fields.
    Non-string scalar fields (int, bool, None) are passed through untouched.
    """
    if isinstance(obj, str):
        # Pure reference: preserve original type (mirrors _substitute in planner.py)
        stripped = obj.strip()
        if stripped.startswith("{{") and stripped.endswith("}}"):
            key = stripped[2:-2].strip()
            if key in subs:
                return subs[key]
        for k, v in subs.items():
            token = f"{{{{{k}}}}}"
            if token in obj:
                v_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                obj = obj.replace(token, v_str)
        return obj
    if isinstance(obj, dict):
        return {k: _apply_substitutions(v, subs) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_apply_substitutions(i, subs) for i in obj]
    return obj  # int, bool, None — pass through untouched


class SubStepRunnerMixin:
    """
    Mixin for ActionStrategy subclasses that need to dispatch sub-steps
    from workflow JSON at runtime.

    Provides:
      _run_sub_steps() — apply substitutions, evaluate `when` conditions,
                         dispatch each sub-step through the action factory.

    Requires the host class to expose self._factory (ActionFactory).
    """

    async def _run_sub_steps(
        self,
        steps_raw: list[dict],
        page,
        resolver,
        context,
        substitutions: dict | None = None,
        stop_on_failure: bool = False,
        
    ) -> list:
        """
        Run a list of raw step dicts as sub-steps.

        Args:
            steps_raw:       Step dicts from workflow JSON (not yet typed).
            substitutions:   Token → value map; {{token}} is replaced in every
                             string field of each step dict before execution.
            stop_on_failure: When True, stop after the first non-passed result.

        Returns:
            List of StepResult for every sub-step that was attempted.
        """
        from engine.runner.when_eval import evaluate_when

        results = []
        for raw in steps_raw:
            cfg_dict = _apply_substitutions(copy.deepcopy(raw), substitutions or {})
            sub_cfg = _dict_to_step_config(cfg_dict)

            # Evaluate `when` condition before running the sub-step
            if sub_cfg.when:
                try:
                    should_run = await evaluate_when(sub_cfg.when, context, page)
                except Exception as e:
                    logger.warning(
                        "_run_sub_steps when-eval error: %s — sub-step will run", e
                    )
                    should_run = True
                if not should_run:
                    logger.info(
                        "  ○ sub-step skipped (when=false): %s",
                        sub_cfg.description or sub_cfg.action,
                    )
                    continue

            action = self._factory.create(sub_cfg.action)
            result = await action.execute(page, sub_cfg, resolver, context)
            results.append(result)

            if stop_on_failure and result.status != "passed":
                break

        return results
