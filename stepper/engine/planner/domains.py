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
session.

There are two walks here, and they are deliberately not the same shape:
`sub_step_dicts` reads only the named dispatcher containers, and `_domains_in`
reads any dict carrying an `action`. See `_domains_in` for why the looser one
is right for discovery and wrong for validation.

An action the registry does not know reports domain `None` rather than raising.
Its real problem is that it is unregistered, PlanValidator already says so, and
a second error about its domain would only bury the first.
"""

from __future__ import annotations


#: The `extra` keys a dispatcher reads its body from — the only places a
#: sub-step can live. `for_each_item`, `parallel` and `paginate` use `steps`
#: (flow.py:66, flow.py:400); `ensure_login` uses `login_steps` (flow.py:163).
#:
#: Walking *every* dict under `extra` instead is wrong, and not harmlessly:
#: `run_workflow` passes arbitrary `extra.vars` to the child workflow, so
#: `{"vars": {"action": "archive"}}` reads as a sub-step calling an action
#: named "archive". PlanValidator rejected the workflow over it.
SUB_STEP_KEYS = ("steps", "login_steps")


def sub_step_dicts(extra) -> list[dict]:
    """
    Every raw sub-step dict below this `extra`, depth-first, dispatchers first.

    Descends *through* a sub-step as well as recording it: a `for_each_item`
    nested inside a `parallel` carries its own body one level further down,
    under its own `extra`.
    """
    found: list[dict] = []
    if not isinstance(extra, dict):
        return found
    for key in SUB_STEP_KEYS:
        body = extra.get(key)
        if not isinstance(body, list):
            continue
        for raw in body:
            if isinstance(raw, dict):
                found.append(raw)
                found.extend(sub_step_dicts(raw.get("extra")))
    return found


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

    Deliberately looser than `sub_step_dicts` above, which walks only the
    named containers. The asymmetry is the point, and it is about what each
    answer costs when it is wrong:

        missing a domain here  → no session opens, and the run dies partway
        an extra name here     → unregistered, domain None, ignored

    So discovery guesses wide. Validation cannot afford to: an extra name
    there *rejects a valid workflow*, which is what `extra.vars` did.
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
