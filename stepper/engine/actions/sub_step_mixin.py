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
import logging

from stepper.engine.utils import dict_to_step_config as _dict_to_step_config
from stepper.engine.runner.interpolation import mapping_lookup, resolve

logger = logging.getLogger(__name__)


def _apply_substitutions(obj, subs: dict):
    """
    Recursively replace {{key}} tokens in a nested dict/list/str structure.

    The walk, the type rules and the JSON embedding all live in
    runner/interpolation.py, shared with the runner's own context pass and the
    db domain's parameter binding — three copies of one idea is how they drift
    apart.

    What is *not* shared is the failure mode. An unknown token here is left
    alone, deliberately: a visible {{typo}} in a log line reads as "the name was
    wrong", where a silent empty string reads as "the value was blank". The
    runner's pass fails the step instead, because a token that reaches an
    action's arguments is not cosmetic — see that module's docstring.
    """
    resolved, _missing = resolve(obj, mapping_lookup(subs))
    return resolved


class SubStepRunnerMixin:
    """
    Mixin for ActionStrategy subclasses that need to dispatch sub-steps
    from workflow JSON at runtime.

    Provides:
      _run_sub_steps() — apply substitutions, evaluate `when` conditions,
                         dispatch each sub-step through the action factory.

    Requires the host class to expose self._factory (ActionFactory). A host may
    also expose self._conditions (ConditionRegistry) to give its sub-steps the
    same `when` vocabulary the run was built with; without one, sub-steps get
    the core conditions only, and self._sessions (SessionSet) to route each
    sub-step to its own domain's session.
    """

    #: Hosts set this in __init__ or through set_conditions(). None means
    #: "core conditions only".
    _conditions = None

    #: Set by the composition root through set_sessions(). None means "hand
    #: every sub-step whatever session the parent received", which is how
    #: dispatch behaved before routing existed.
    _sessions = None

    def set_sessions(self, sessions) -> "SubStepRunnerMixin":
        """
        Late-bind the run's sessions, so sub-steps route like top-level steps.

        Same shape as set_conditions above, and for the same reason: a
        dispatcher is registered once at startup, while the SessionSet belongs
        to one run. build_pipeline sets it once the set exists. Registries are
        built per run, so an instance is never shared between runs.
        """
        self._sessions = sessions
        return self

    async def _session_for(self, action, fallback):
        """
        The session this sub-step's action should act on.

        Falls back to whatever the parent was handed when no set is bound —
        a direct caller or a test double — which is exactly the pre-routing
        behaviour.
        """
        if self._sessions is None:
            return fallback
        return await self._sessions.get(action.domain)

    def set_conditions(self, conditions) -> "SubStepRunnerMixin":
        """
        Late-bind the run's `when` vocabulary.

        A domain's conditions are only knowable once its site has registered,
        and sites register into a registry that already holds these actions —
        so the composition root sets them here afterwards rather than at
        construction. See main.build_action_registry.
        """
        self._conditions = conditions
        return self

    async def _run_sub_steps(
        self,
        steps_raw: list[dict],
        page,
        resolver,
        context,
        substitutions: dict | None = None,
        stop_on_failure: bool = False,
        behaviour=None,
    ) -> list:
        """
        Run a list of raw step dicts as sub-steps.

        Args:
            steps_raw:       Step dicts from workflow JSON (not yet typed).
            substitutions:   Token → value map; {{token}} is replaced in every
                             string field of each step dict before execution.
            stop_on_failure: When True, stop after the first non-passed result.
            behaviour:       HumanBehaviour forwarded to each sub-step, so glue
                             sub-steps get the same humanisation as top-level
                             steps instead of silently running without it.

        Returns:
            List of StepResult for every sub-step that was attempted.
        """
        from stepper.engine.runner.when_eval import evaluate_when

        results = []
        for raw in steps_raw:
            cfg_dict = _apply_substitutions(copy.deepcopy(raw), substitutions or {})
            sub_cfg = _dict_to_step_config(cfg_dict)

            # Evaluate `when` condition before running the sub-step
            if sub_cfg.when:
                try:
                    should_run = await evaluate_when(
                        sub_cfg.when, context, self._sessions or page,
                        conditions=self._conditions,
                    )
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
            target = await self._session_for(action, page)
            result = await action.execute(target, sub_cfg, resolver, context, behaviour)
            result.domain = action.domain
            results.append(result)

            if stop_on_failure and result.status != "passed":
                break

        return results
