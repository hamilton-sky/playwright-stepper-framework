"""
healer/ai_healer.py — LLM-powered replacement step generator.

Rungs (named by tier_for, given the rungs already `tried` for the step):
  embed_direct  free: DOMSnapshotCascade resolved a healed_cfg (unique
                high-confidence match), applied with no AI call
  cheap         AIService "heal" chain: Groq → Gemini → Claude Haiku
  big           AIService "heal_big" chain, only after two cheap rungs failed

With no `tried` (the default) the routing is the old one: a healed_cfg is
applied directly, anything else goes to the cheap chain. Only ambiguous or
low-confidence DOM snapshots reach the network.
"""

from __future__ import annotations

import json
import logging

from stepper.engine.ai.service import AIService
from stepper.engine.healer.interfaces import (FREE_TIER, DomPayload, HealerStrategy,
                                              HealingError)
from stepper.engine.interfaces import StepConfig
from stepper.engine.planner.schema_extractor import ActionSchemaExtractor
from stepper.engine.utils import dict_to_step_config

logger = logging.getLogger(__name__)

_SYSTEM_TEMPLATE = """\
You are a browser automation healer. A workflow step failed because its element \
selector no longer matches the page. Fix it using the live DOM context provided.

Rules:
1. Keep the SAME action as the failed step unless it is fundamentally wrong.
2. Only change the "element" field to a locator that matches a real element in the DOM.
3. Prefer {{"placeholder":"..."}} or {{"role":"...","name":"..."}} over CSS — more resilient.
4. Copy all other fields (input_value, url, description, extra) from the failed step unchanged.
5. Return a JSON array with exactly ONE replacement step.
6. Use ONLY these registered actions:
{action_block}
7. If workflow_context is provided, use nearby_steps to infer which page/phase the \
automation is in — this narrows which element to target.

Example:
  failed: {{"action":"fill","element":{{"css":".broken"}},"input_value":"hello","description":"fill username"}}
  healed: [{{"action":"fill","element":{{"placeholder":"Username"}},"input_value":"hello","description":"fill username"}}]

Return ONLY valid JSON array. No markdown. No explanation.\
"""


class AiHealer(HealerStrategy):
    """
    Implements HealerStrategy using a multi-provider LLM cascade.

    Construct with an action_schema (from ActionSchemaExtractor.extract()) so the
    system prompt always reflects the current registry — no stale hardcoded lists.

    Args:
        action_schema: dict[action_name, {description}] from ActionSchemaExtractor
        ai_service:    AIService instance; a default one is created if None
    """

    def __init__(
        self,
        action_schema: dict,
        ai_service: AIService | None = None,
    ) -> None:
        self._schema = action_schema
        self._ai = ai_service or AIService()
        self._system = _SYSTEM_TEMPLATE.format(
            action_block=ActionSchemaExtractor.to_prompt_block(action_schema)
        )

    # ── HealerStrategy contract ───────────────────────────────────────────────

    def tier_for(self, dom: DomPayload, tried: tuple[str, ...]) -> str:
        """embed_direct while its cfg is untried; big after two cheap misses; else cheap."""
        if dom.healed_cfg is not None and FREE_TIER not in tried:
            return FREE_TIER
        if tried.count("cheap") >= 2:
            return "big"
        return "cheap"

    async def heal(
        self,
        step: StepConfig,
        error: str,
        dom: DomPayload,
        *,
        all_steps: list | None = None,
        current_index: int | None = None,
        context_vars: dict | None = None,
        tried: tuple[str, ...] = (),
    ) -> list[StepConfig]:
        tier = self.tier_for(dom, tried)

        # Fast path: embed resolved uniquely — zero AI tokens
        if tier == FREE_TIER:
            assert dom.healed_cfg is not None
            logger.info(
                f"[AiHealer] embed_direct heal for '{step.action}' (0 tokens)"
            )
            return [self._apply_healed_cfg(step, dom.healed_cfg)]

        # Build workflow context when caller provides step list + position
        workflow_context: dict | None = None
        if all_steps is not None and current_index is not None:
            lo = max(0, current_index - 3)
            hi = current_index + 4
            nearby = [
                {"action": s.action, "description": s.description}
                for s in all_steps[lo:hi]
            ]
            workflow_context = {
                "current_index": current_index,
                "total_steps":   len(all_steps),
                "nearby_steps":  nearby,
                "context_vars":  context_vars or {},
            }
            logger.info(
                f"[AiHealer] calling AI for '{step.action}' "
                f"with workflow context (step {current_index + 1}/{len(all_steps)}, "
                f"strategy={dom.strategy_used}, ~{dom.token_estimate} tokens)"
            )
        else:
            logger.info(
                f"[AiHealer] calling AI for '{step.action}' "
                f"(no context, strategy={dom.strategy_used}, ~{dom.token_estimate} tokens)"
            )

        payload: dict = {
            "failed_step": {
                "action":      step.action,
                "description": step.description,
                "element":     step.element,
                "input_value": step.input_value,
                "extra":       step.extra,
            },
            "error": error,
            "dom":   dom.content,
        }
        if workflow_context:
            payload["workflow_context"] = workflow_context

        user_msg = json.dumps(payload, ensure_ascii=False)

        logger.debug(f"[AiHealer] prompt sent to AI:\n{user_msg}")
        task_type = "heal_big" if tier == "big" else "heal"
        raw = await self._ai.chat(user_msg, task_type=task_type, system=self._system)
        logger.debug(f"[AiHealer] raw AI reply: {raw}")
        return self._parse(raw, step.action)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _apply_healed_cfg(step: StepConfig, healed_cfg: dict) -> StepConfig:
        """Build a replacement StepConfig with the healed element cfg."""
        return StepConfig(
            action=step.action,
            description=step.description,
            url=step.url,
            element=healed_cfg,
            input_value=step.input_value,
            wait_for=step.wait_for,
            extra=step.extra,
            when=step.when,
            retry=step.retry,
            retry_delay_ms=step.retry_delay_ms,
            continue_on_failure=step.continue_on_failure,
            skip_screenshot=step.skip_screenshot,
        )

    def _parse(self, raw: str, action_name: str) -> list[StepConfig]:
        """Parse and validate the AI response into a list of StepConfig."""
        known = set(self._schema.keys())

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise HealingError(
                f"AI returned invalid JSON for '{action_name}': {e} — raw: {raw[:300]}"
            )

        # Tolerate a single dict (AI forgot the outer array)
        if isinstance(data, dict):
            data = [data]

        if not isinstance(data, list) or not data:
            raise HealingError(
                f"AI returned empty or non-list response for '{action_name}'"
            )

        steps: list[StepConfig] = []
        for i, raw_step in enumerate(data, 1):
            if not isinstance(raw_step, dict):
                raise HealingError(f"Replacement step {i} is not a dict")
            act = raw_step.get("action", "")
            if act not in known:
                raise HealingError(
                    f"Replacement step {i} uses unknown action '{act}' "
                    f"(known: {sorted(known)})"
                )
            steps.append(dict_to_step_config(raw_step))

        return steps
