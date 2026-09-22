"""
planner/domains.py — which domains a plan needs, read before anything opens.

Every action declares the domain it acts on (M1), and every step names an
action. Walking that mapping before the run starts answers two questions the
runner previously answered only by failing partway through:

    which sessions will this workflow open?   `domains_used` — what validate prints
    does this run have all of them?           PlanValidator, given the registered names

Sub-steps count. `for_each_item`, `parallel` and `paginate` hold theirs as raw
dicts inside `extra`, so a loop body is the easiest place for a second domain to
hide — and since M4 it is a place the runner genuinely routes to a different
session. The walk here has the same shape as the validator's `when`-clause walk,
for the same reason: a nested step is a step.

An action the registry does not know reports domain `None` rather than raising.
Its real problem is that it is unregistered, PlanValidator already says so, and
a second error about its domain would only bury the first.
"""

from __future__ import annotations


def domains_in_step(step, registry) -> list[tuple[str, str | None]]:
    """
    Every (action_name, domain) this step will reach, its sub-steps included.

    Order is the step's own action first, then sub-steps depth-first, so an
    error message built from this reads in the order a person would look.
    """
    found: list[tuple[str, str | None]] = []
    if step.action:
        found.append((step.action, _domain_of(step.action, registry)))
    found.extend(_domains_in(step.extra, registry))
    return found


def domains_used(steps, registry) -> list[str]:
    """
    Sorted, unique domains the plan needs a session for.

    Session-agnostic actions contribute nothing — they are handed `None` at
    runtime and must not cause a domain to open on their behalf.
    """
    seen = {domain
            for step in steps
            for _action, domain in domains_in_step(step, registry)
            if domain}
    return sorted(seen)


def _domain_of(action_name: str, registry) -> str | None:
    try:
        action = registry.create(action_name)
    except Exception:
        return None            # unregistered — PlanValidator reports it properly
    return getattr(action, "domain", None)


def _domains_in(node, registry) -> list[tuple[str, str | None]]:
    """
    Walk raw sub-step dicts looking for `action` keys.

    Descends *through* a sub-step as well as recording it: a `for_each_item`
    nested inside a `parallel` carries its own body one level further down.
    """
    found: list[tuple[str, str | None]] = []
    if isinstance(node, dict):
        action = node.get("action")
        if isinstance(action, str) and action:
            found.append((action, _domain_of(action, registry)))
        for key, value in node.items():
            if key != "action":
                found.extend(_domains_in(value, registry))
    elif isinstance(node, list):
        for item in node:
            found.extend(_domains_in(item, registry))
    return found
