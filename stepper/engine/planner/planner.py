"""
planner/planner.py — AI-powered task planner.

Responsibility (SRP): ONLY turns natural language → structured StepConfig list.
Pattern: Strategy (swappable planner backends: Claude, GPT, static JSON)
DIP: Runner depends on PlannerStrategy interface, not this concrete class.
"""

from __future__ import annotations
import json
import logging
from abc import ABC, abstractmethod

from pathlib import Path

from engine.interfaces import StepConfig
from engine.utils import dict_to_step_config as _dict_to_step

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a browser automation planner.

Given a task, return a JSON array of steps.

Each step:
{
  "action":      "navigate|click|fill|screenshot|wait|store_count|collect_items|for_each_item|assert_count|measure_performance|extract_data|paginate|ensure_login",
  "description": "short label",
  "url":         "expected url or fragment",
  "element": {
    "text":        "visible text",
    "role":        "ARIA role",
    "label":       "aria-label",
    "placeholder": "input placeholder",
    "css":         "CSS selector",
    "xpath":       "XPath",
    "id":          "element id"
  },
  "input_value": "text to type (fill actions)",
  "wait_for":    "selector or url fragment to wait for",
  "extra":       {}   // action-specific keys (selectors, filter, limit, expected, threshold_ms)
}

Return ONLY valid JSON array. No markdown. No explanation.
"""


# ── Strategy interface ─────────────────────────────────────────────────────────

class PlannerStrategy(ABC):
    @abstractmethod
    def plan(self, task: str) -> list[StepConfig]:
        """Convert task description to list of StepConfig."""


# ── Claude planner ─────────────────────────────────────────────────────────────

class ClaudePlanner(PlannerStrategy):
    """Uses Claude to plan steps from natural language."""

    def __init__(self, model: str = "claude-sonnet-4-20250514", max_tokens: int = 2000):
        import anthropic
        self._client    = anthropic.Anthropic()
        self._model     = model
        self._max_tokens = max_tokens

    def plan(self, task: str) -> list[StepConfig]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Task: {task}"}]
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        steps_raw = json.loads(raw)
        return [_dict_to_step(s) for s in steps_raw]


# ── JSON file planner (exam: pre-built workflows) ─────────────────────────────

class JsonFilePlanner(PlannerStrategy):
    """
    Loads a workflow from a pre-built JSON file.

    Supports template variable substitution so the same workflow can run
    against different data without code changes.

    Variable resolution order (later wins):
      1. "variables" block inside the workflow JSON   ← defaults
      2. variables dict passed to __init__            ← caller override

    In the workflow JSON, use {{variable_name}} anywhere in a step value:

        "variables": { "query": "Dune", "max_year": 1980, "limit": 5 }
        "steps": [
          { "action": "collect_items",
            "extra": { "query": "{{query}}", "filter": {"year_max": "{{max_year}}"} } }
        ]

    Pure references like "{{max_year}}" preserve the original type (int stays int).
    Mixed strings like "Search {{query}} results" are substituted as strings.
    """

    def __init__(self, path: str, variables: dict | None = None):
        self._path      = path
        self._variables = variables or {}

    def plan(self, task: str = "") -> list[StepConfig]:
        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)

        # 1. Extract settings (workflow-level defaults)
        settings = data.get("settings", {})
        
        # Support the legacy top-level key for backward compatibility
        if "continue_on_failure" in data:
            settings.setdefault("continue_on_failure", data["continue_on_failure"])

        variables = {
            **data.get("variables", {}),
            **self._variables,
        }

        steps_raw = data.get("steps", data) if isinstance(data, dict) else data
        base_dir = Path(self._path).parent
        steps_raw = _expand_includes(steps_raw, base_dir, variables)

        if variables:
            steps_raw = _substitute(steps_raw, variables)

        # 2. Apply settings to every step if not explicitly overridden by the step
        for step in steps_raw:
            for key, value in settings.items():
                if key not in step:
                    step[key] = value

        return [_dict_to_step(s) for s in steps_raw]


def _substitute(obj, variables: dict):
    """
    Recursively substitute {{key}} placeholders in a parsed JSON structure.

    Pure reference  "{{max_year}}" → typed value (int/bool/etc preserved).
    Mixed string    "query: {{query}}" → string with value interpolated.
    """
    if isinstance(obj, str):
        if obj.startswith("{{") and obj.endswith("}}"):
            key = obj[2:-2].strip()
            if key in variables:
                return variables[key]      # preserves int / bool / float type
        for k, v in variables.items():
            obj = obj.replace(f"{{{{{k}}}}}", str(v))
        return obj
    if isinstance(obj, dict):
        return {k: _substitute(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute(item, variables) for item in obj]
    return obj


def _expand_includes(steps, base_dir: Path, parent_vars: dict, stack: list[Path] | None = None):
    """
    Expand include directives in a workflow step list.

    Include step shape:
      { "include": "workflows/login.json", "vars": { ... } }

    Variable precedence for included workflow:
      included "variables" < parent_vars < include.vars
    """
    if stack is None:
        stack = []

    if not isinstance(steps, list):
        raise ValueError("Workflow steps must be a list to expand includes.")

    expanded: list[dict] = []
    for step in steps:
        if isinstance(step, dict) and "include" in step:
            include_path = Path(step["include"])
            include_vars = step.get("vars", {}) or {}
            if not include_path.is_absolute():
                include_path = (base_dir / include_path).resolve()

            if include_path in stack:
                cycle = " -> ".join(str(p) for p in stack + [include_path])
                raise ValueError(f"Include cycle detected: {cycle}")

            with open(include_path, encoding="utf-8") as f:
                include_data = json.load(f)

            include_steps = (
                include_data.get("steps", include_data)
                if isinstance(include_data, dict) else include_data
            )

            merged_vars = {
                **include_data.get("variables", {}),
                **parent_vars,
                **include_vars,
            }

            nested_base = include_path.parent
            include_steps = _expand_includes(
                include_steps,
                nested_base,
                merged_vars,
                stack=stack + [include_path],
            )

            if merged_vars:
                include_steps = _substitute(include_steps, merged_vars)

            expanded.extend(include_steps)
        else:
            expanded.append(step)

    return expanded


# ── Static planner (testing / deterministic) ──────────────────────────────────

class StaticPlanner(PlannerStrategy):
    """Returns a fixed list of steps. Useful for unit tests."""

    def __init__(self, steps: list[StepConfig]):
        self._steps = steps

    def plan(self, task: str = "") -> list[StepConfig]:
        return self._steps


# _dict_to_step is imported from engine.utils — single source of truth.
