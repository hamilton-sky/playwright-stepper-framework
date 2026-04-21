"""
planner/schema_extractor.py — Extract action metadata from a registry for AI prompts.

Reads each registered ActionStrategy's docstring to build a human-readable
schema dict that AI planners and the AiHealer can embed in their system prompts.
"""

from __future__ import annotations

import inspect


class ActionSchemaExtractor:
    """
    Extracts a schema dict from an ActionRegistry and formats it for LLM prompts.

    Usage:
        schema = ActionSchemaExtractor.extract(registry)
        block  = ActionSchemaExtractor.to_prompt_block(schema)
    """

    @staticmethod
    def extract(registry) -> dict[str, dict]:
        """
        Returns {action_name: {"description": str}} for every registered action.
        Description is the first non-empty line of the class docstring, or the
        action_name itself when no docstring is present.
        """
        schema: dict[str, dict] = {}
        for name, action in registry._registry.items():
            doc = inspect.getdoc(action) or ""
            first_line = next((ln.strip() for ln in doc.splitlines() if ln.strip()), "")
            schema[name] = {"description": first_line or name}
        return schema

    @staticmethod
    def to_prompt_block(schema: dict[str, dict]) -> str:
        """
        Format schema as a numbered list suitable for injection into an AI system prompt.

        Example output:
            1. navigate — Navigate the browser to a URL
            2. click — Click a UI element
        """
        lines: list[str] = []
        for i, (name, meta) in enumerate(schema.items(), 1):
            desc = meta.get("description", "")
            lines.append(f"{i}. {name} — {desc}" if desc and desc != name else f"{i}. {name}")
        return "\n".join(lines)
