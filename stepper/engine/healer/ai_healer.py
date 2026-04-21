"""
healer/ai_healer.py — LLM-powered replacement step generator.

Provider cascade (via AIService): Groq → Gemini → Claude Haiku.

Fast path: when DOMSnapshotCascade already resolved a healed_cfg via
embed_direct (unique high-confidence match), no AI call is made — the
healed cfg is applied directly to the failed step. Only ambiguous or
low-confidence DOM snapshots reach the network.
"""

from __future__ import annotations

import json
import logging

from engine.ai.service import AIService
from engine.healer.interfaces import DomPayload, HealerStrategy, HealingError
from engine.interfaces import StepConfig
from engine.planner.schema_extractor import ActionSchemaExtractor
from engine.utils import dict_to_step_config

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

    async def heal(
        self,
        step: StepConfig,
        error: str,
        dom: DomPayload,
    ) -> list[StepConfig]:
        # Fast path: embed resolved uniquely — zero AI tokens
        if dom.healed_cfg is not None:
            logger.info(
                f"[AiHealer] embed_direct heal for '{step.action}' (0 tokens)"
            )
            return [self._apply_healed_cfg(step, dom.healed_cfg)]

        # Slow path: ask the AI
        logger.info(
            f"[AiHealer] calling AI for '{step.action}' "
            f"(strategy={dom.strategy_used}, ~{dom.token_estimate} tokens)"
        )
        user_msg = json.dumps(
            {
                "failed_step": {
                    "action":      step.action,
                    "description": step.description,
                    "element":     step.element,
                    "input_value": step.input_value,
                    "extra":       step.extra,
                },
                "error": error,
                "dom":   dom.content,
            },
            ensure_ascii=False,
        )

        logger.debug(f"[AiHealer] prompt sent to AI:\n{user_msg}")
        raw = await self._ai.chat(user_msg, task_type="heal", system=self._system)
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
