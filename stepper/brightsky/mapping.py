"""
brightsky/mapping.py — A BrightSky workflow version as strict stepper steps.

`map_version` turns a validated `WorkflowDetail` into a `MappedWorkflow`: a
`navigate` to the workflow's own site, then one `click` or `fill` per BrightSky
step, each with the expectation ticket 05's hook checks. A step it cannot map
raises `UnmappableStep(step_number, reason)`.

It owns two gates:

- The host guard. The navigate host, and every step's `expectedDomain`, must be
  the workflow's `site` or a subdomain of it, so a stored workflow cannot steer
  the headless browser to an arbitrary URL.
- `extra.strict: true` on every acting step, so a miss goes to the heal loop
  instead of a description match clicking the wrong element and passing.

Stored text never reaches the engine's `{{…}}` substitution or its `ENV:`
lookup (`_resolve_input_value`), which would type the runner's own environment
(the bridge token, AI keys) into the page. Nothing in this module does I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from stepper.brightsky.models import WorkflowDetail
from stepper.engine.interfaces import StepConfig

MATCH_MODES = frozenset({"startsWith", "includes", "regex"})
#: Outcome kinds that name an element (`readPlanStepTarget` in bright-sky).
ELEMENT_OUTCOMES = frozenset({"value_set", "element_gone", "element_appears"})
OUTCOME_KINDS = ELEMENT_OUTCOMES | {"url_change"}
FILL_ROLES = frozenset({"textbox", "searchbox", "spinbutton"})
UNSUPPORTED_ROLES = frozenset({"combobox", "listbox", "slider"})

#: Lower-case DNS labels joined by dots, nothing else: no userinfo, port,
#: path, query, fragment, backslash, whitespace or brackets can get through.
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\Z")
#: A last label browsers parse as an IPv4 number (`127.0.0.1`, `2130706433`,
#: `0x7f000001`), so a site ending in one is an IP literal.
_NUMERIC_LABEL = re.compile(r"(?:\d+|0x[0-9a-f]*)\Z")
_ID_SELECTOR = re.compile(r"#[A-Za-z][\w-]*\Z")
#: The first '…' or "…" quoted text. A single quote opens only when no letter
#: precedes it and closes only when none follows, so an apostrophe
#: ("the author's name") is not taken for a quote.
_QUOTED = re.compile(r"(?<!\w)'(.+?)'(?!\w)|\"([^\"]+)\"")
_MAX_SHOWN = 100

_TEMPLATE = "contains a {{…}} template reference"


class UnmappableStep(Exception):
    """A BrightSky step that cannot run as a strict stepper step."""

    def __init__(self, step_number: int, reason: str) -> None:
        super().__init__(f"step {step_number}: {reason}")
        self.step_number = step_number
        self.reason = reason


@dataclass(frozen=True)
class StepExpectation:
    """What ticket 05's hook checks around one acting step."""
    #: The step's `expectedUrl` and `matchMode`, for steps after the first only
    #: (step 1's page is the navigate). A None mode means `startsWith`.
    start_url: str | None
    match_mode: str | None
    #: None when the step has no `expectedOutcome`.
    outcome_kind: str | None
    #: The outcome target's element cfg, for the element outcome kinds.
    outcome_element: dict | None
    #: `urlContains`, for a `url_change` outcome that has one.
    url_contains: str | None


@dataclass(frozen=True)
class MappedWorkflow:
    steps: list[StepConfig]
    #: Step description → BrightSky step number (the navigate is step 1).
    step_numbers: dict[str, int]
    #: Acting step description → its expectation.
    expectations: dict[str, StepExpectation]


def url_matches(pathname: str, expected: str, mode: str | None = None) -> bool:
    """bright-sky's `matchUrl`: `startsWith` by default, and for a bad regex."""
    if mode == "includes":
        return expected in pathname
    if mode == "regex":
        try:
            return re.search(expected, pathname) is not None
        except re.error:
            return pathname.startswith(expected)
    return pathname.startswith(expected)


def map_version(detail: WorkflowDetail) -> MappedWorkflow:
    site = detail.site.lower()
    site_ok = (_HOST.match(site) is not None and "." in site
               and _NUMERIC_LABEL.match(site.rsplit(".", 1)[-1]) is None)

    first = detail.steps[0]
    host = _optional_str(first, "expectedDomain", 1)
    host = detail.site if host is None else host
    if not site_ok or not _on_site(host, site):
        raise UnmappableStep(1, f"navigate host {_shown(host)} is not the "
                                f"workflow's site {_shown(detail.site)}")
    url = f"https://{host.lower()}{_navigate_path(first)}"
    _refuse_template(1, url)

    navigate = StepConfig(action="navigate", description=f"Step 1: open {url}", url=url)
    steps = [navigate]
    step_numbers = {navigate.description: 1}
    expectations: dict[str, StepExpectation] = {}

    for number, raw in enumerate(detail.steps, start=1):
        step, expectation = _map_step(raw, number, detail.site, site)
        if step.description in step_numbers:
            raise UnmappableStep(number, "title repeats the navigate step's description")
        steps.append(step)
        step_numbers[step.description] = number
        expectations[step.description] = expectation

    return MappedWorkflow(steps=steps, step_numbers=step_numbers, expectations=expectations)


# ── one step ─────────────────────────────────────────────────────────────────

def _map_step(raw: dict, n: int, shown_site: str, site: str) -> tuple[StepConfig, StepExpectation]:
    title: str = raw["title"]
    explanation = _optional_str(raw, "explanation", n) or ""
    domain = _optional_str(raw, "expectedDomain", n)
    if n > 1 and domain is not None and not _on_site(domain, site):
        raise UnmappableStep(n, f"expected domain {_shown(domain)} is not the "
                                f"workflow's site {_shown(shown_site)}")
    expected_url = _optional_str(raw, "expectedUrl", n)
    mode = raw.get("matchMode")
    if mode is not None and mode not in MATCH_MODES:
        raise UnmappableStep(n, f"unknown matchMode {_shown(mode)}")

    target = raw.get("target")
    role, element = _element(target, n) if target is not None else ("", {})
    if not element:
        raise UnmappableStep(n, "step has no target")
    if role.lower() in UNSUPPORTED_ROLES:
        raise UnmappableStep(n, f"role {_shown(role)} is not supported yet")

    kind, outcome_element, url_contains = _outcome(raw.get("expectedOutcome"), n)

    extra: dict[str, Any] = {"strict": True}
    input_value = ""
    if role.lower() in FILL_ROLES or kind == "value_set":
        action = "fill"
        input_value = _quoted(title) or _quoted(explanation) or ""
        if not input_value.strip():
            raise UnmappableStep(n, "no value to type: quote it in the title")
        if input_value.lstrip().startswith(("ENV:", "${ENV:")):
            raise UnmappableStep(n, "value names an environment variable")
        if kind == "url_change":
            extra["press_enter"] = True
    else:
        action = "click"

    description = f"Step {n}: {title}"
    _refuse_template(n, description, input_value, url_contains or "",
                     *element.values(), *(outcome_element or {}).values())

    step = StepConfig(
        action=action, description=description, element=element,
        input_value=input_value, extra=extra,
        heal_assert={"url_contains": url_contains} if url_contains else None,
    )
    expectation = StepExpectation(
        start_url=expected_url if n > 1 else None,
        match_mode=mode if n > 1 else None,
        outcome_kind=kind, outcome_element=outcome_element, url_contains=url_contains,
    )
    return step, expectation


def _element(target: Any, n: int) -> tuple[str, dict]:
    """(role, element cfg) for a BrightSky target. The role alone is never in the cfg."""
    if not isinstance(target, dict):
        raise UnmappableStep(n, "target must be an object")
    role = (_optional_str(target, "role", n) or "").strip()
    name = (_optional_str(target, "accessibleName", n) or "").strip()
    selectors = target.get("selectors", [])
    if not isinstance(selectors, list) or not all(isinstance(s, str) for s in selectors):
        raise UnmappableStep(n, "target selectors must be a list of strings")

    element: dict = {}
    if role and name:
        element = {"role": role, "name": name}
    elif name:
        element = {"text": name}
    selector = next((s.strip() for s in selectors if s.strip()), "")
    if selector.startswith(("//", "(/")):
        element["xpath"] = selector
    elif _ID_SELECTOR.match(selector):
        element["id"] = selector[1:]
    elif selector:
        element["css"] = selector
    return role, element


def _outcome(outcome: Any, n: int) -> tuple[str | None, dict | None, str | None]:
    if outcome is None:
        return None, None, None
    if not isinstance(outcome, dict):
        raise UnmappableStep(n, "expectedOutcome must be an object")
    kind = outcome.get("kind")
    if kind not in OUTCOME_KINDS:
        raise UnmappableStep(n, f"outcome kind {_shown(kind)} is not supported")
    if kind == "url_change":
        return kind, None, _optional_str(outcome, "urlContains", n) or None
    target = outcome.get("target")
    _, element = _element(target, n) if target is not None else ("", {})
    if not element:
        raise UnmappableStep(n, f"outcome {kind} has no target")
    return kind, element, None


# ── helpers ──────────────────────────────────────────────────────────────────

def _on_site(host: str, site: str) -> bool:
    host = host.lower()
    return _HOST.match(host) is not None and (host == site or host.endswith("." + site))


def _navigate_path(step: dict) -> str:
    path = _optional_str(step, "expectedUrl", 1)
    mode = step.get("matchMode")
    if path is not None and path.startswith("/") and mode in (None, "startsWith"):
        return path
    return "/"


def _quoted(text: str) -> str | None:
    found = _QUOTED.search(text)
    if found is None:
        return None
    return found.group(1) if found.group(1) is not None else found.group(2)


def _refuse_template(n: int, *texts: Any) -> None:
    if any(isinstance(t, str) and "{{" in t for t in texts):
        raise UnmappableStep(n, _TEMPLATE)


def _optional_str(obj: dict, key: str, n: int) -> str | None:
    value = obj.get(key)
    if value is not None and not isinstance(value, str):
        raise UnmappableStep(n, f"{key} must be a string")
    return value


def _shown(value: Any) -> str:
    """Stored text as it may appear in a reason: escaped and cut short."""
    text = str(value).encode("unicode_escape").decode("ascii")
    return text if len(text) <= _MAX_SHOWN else text[:_MAX_SHOWN - 1] + "…"
