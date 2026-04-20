"""
schema_extractor.py — Introspects the ActionRegistry into an LLM-friendly schema.

Used by the AI planner (to know which actions exist) and by AiHealer (to
constrain replacement steps to registered actions).
"""

from __future__ import annotations

import inspect
from typing import Any


_EXCLUDED_PARAMS = {"self", "page", "step", "resolver", "context", "behaviour"}


class ActionSchemaExtractor:
    """Turn an ActionRegistry into a {action_name: {description, params}} dict."""

    @staticmethod
    def extract(registry: Any) -> dict[str, dict]:
        schema: dict[str, dict] = {}
        for name, action in registry._registry.items():
            doc = inspect.getdoc(action.__class__) or ""
            description = doc.splitlines()[0].strip() if doc else name

            params: list[str] = []
            execute_fn = getattr(action, "_execute", None)
            if execute_fn is not None:
                try:
                    sig = inspect.signature(execute_fn)
                    params = [
                        p for p in sig.parameters.keys()
                        if p not in _EXCLUDED_PARAMS
                    ]
                except (TypeError, ValueError):
                    params = []

            schema[name] = {
                "description": description,
                "params": params,
            }
        return schema

    @staticmethod
    def to_prompt_block(schema: dict[str, dict]) -> str:
        lines: list[str] = []
        for idx, (name, info) in enumerate(schema.items(), start=1):
            desc = info.get("description", "")
            params = info.get("params") or []
            params_str = ", ".join(params) if params else "(no extra params)"
            lines.append(f"{idx}. {name} — {desc} [params: {params_str}]")
        return "\n".join(lines)
