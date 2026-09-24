"""
Strict resolution — the mode in which an assertion means something.

`ElementResolver.resolve()` is forgiving by design. When a cfg matches nothing it
falls through to the zero-selector path, where `KeywordFuzzyResolver` matches
against the step's *description* instead. For an action that acts, that is the
whole point: a click should still land after a redesign renames a class.

For an action that checks, it removes the only property the check had. This
really happened, in this repo, in CI:

    { "action": "assert_visible",
      "description": "Inventory page rendered",
      "element": { "css": ".app_logo" } }

passed on a page with no `.app_logo` anywhere, by matching some other element
against the words "Inventory page rendered". The workflow reported 0 failed
while the login it existed to verify had never happened.

`strict=True` stops at the deterministic strategies: either the cfg names
something on the page, or the answer is not-found.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.interfaces import StepConfig
from stepper.engine.resolvers.element_resolver import ElementResolver


@pytest.fixture(autouse=True)
def _allow_building_a_resolver(monkeypatch):
    """
    ElementResolver.__init__ builds a SemanticResolver, and the suite-wide guard
    in conftest refuses that — rightly, since it would load an embedding model.
    These tests need a real ElementResolver but never its scoring, so neutralise
    the constructor rather than lifting the guard.
    """
    monkeypatch.setattr(
        "stepper.engine.resolvers.strategies.SemanticResolver.__init__",
        lambda self, *a, **kw: None,
    )


def _strategy(name: str, priority: int, candidates: list):
    """A deterministic strategy double that returns a fixed candidate list."""
    s = MagicMock()
    s.name = name
    s.priority = priority
    s.collect = AsyncMock(return_value=candidates)
    return s


def _resolver(*strategies) -> ElementResolver:
    r = ElementResolver(list(strategies))
    # Any of these firing in strict mode is the bug; make that loud rather than
    # silently returning a plausible answer.
    def _forbidden(name):
        async def boom(*a, **kw):
            raise AssertionError(f"strict resolve reached {name} — it must not")
        return boom

    r._zero_selector_path = _forbidden("_zero_selector_path")       # type: ignore[assignment]
    r._visual_fallback = _forbidden("_visual_fallback")             # type: ignore[assignment]
    r._semantic_filter = _forbidden("_semantic_filter")             # type: ignore[assignment]
    return r


# ── Strict finds what is really there ─────────────────────────────────────────

async def test_a_unique_deterministic_match_resolves():
    locator = MagicMock()
    r = _resolver(_strategy("css", 60, [locator]))

    result = await r.resolve(MagicMock(), {"css": ".app_logo"}, "anything", strict=True)

    assert result.found is True
    assert result.locator is locator
    assert result.method == "css"


async def test_strategies_are_still_tried_in_priority_order():
    """Strict narrows which phases run, not how Phase 1 picks."""
    role_loc, css_loc = MagicMock(), MagicMock()
    r = _resolver(
        _strategy("css", 60, [css_loc]),
        _strategy("role", 10, [role_loc]),
    )

    result = await r.resolve(MagicMock(), {"role": "button", "css": ".b"}, "", strict=True)

    assert result.locator is role_loc, "the more durable identifier should win"


async def test_several_matches_take_the_first_rather_than_narrowing_by_description():
    """
    An ambiguous selector is a different problem from a missing one — the cfg
    did match real elements. Playwright's own `.first` has these semantics.
    Narrowing by description is precisely what strict mode exists to prevent.
    """
    first, second = MagicMock(), MagicMock()
    r = _resolver(_strategy("css", 60, [first, second]))

    result = await r.resolve(MagicMock(), {"css": ".row"}, "the second row", strict=True)

    assert result.found is True
    assert result.locator is first


# ── Strict fails when the cfg names nothing ───────────────────────────────────

async def test_no_match_is_not_found_rather_than_a_description_match():
    """The regression this whole mode exists for."""
    r = _resolver(_strategy("css", 60, []))

    result = await r.resolve(
        MagicMock(), {"css": ".app_logo"}, "Inventory page rendered", strict=True
    )

    assert result.found is False
    assert result.method == "not-found"


async def test_a_cfg_with_no_element_keys_is_not_found():
    """
    Without strict this is the zero-selector path, which resolves purely from the
    description. An assertion naming no element cannot be checking anything.
    """
    r = _resolver(_strategy("css", 60, []))

    result = await r.resolve(MagicMock(), {}, "some description", strict=True)

    assert result.found is False


async def test_a_strategy_that_throws_does_not_become_a_fuzzy_match():
    """A broken strategy must degrade to not-found, not to the fallback path."""
    bad = _strategy("css", 60, [])
    bad.collect = AsyncMock(side_effect=RuntimeError("selector engine error"))
    r = _resolver(bad)

    with pytest.raises(RuntimeError):
        await r.resolve(MagicMock(), {"css": ".x"}, "desc", strict=True)


# ── The default is unchanged ──────────────────────────────────────────────────

async def test_the_cascade_still_falls_through_by_default():
    """
    Acting actions keep their forgiveness — that is why strict is opt-in rather
    than the new default.
    """
    r = ElementResolver([_strategy("css", 60, [])])
    sentinel = object()

    async def fallback(page, description):
        return sentinel

    r._zero_selector_path = fallback   # type: ignore[assignment]

    assert await r.resolve(MagicMock(), {"css": ".gone"}, "click login") is sentinel


async def test_strict_is_off_unless_asked_for():
    import inspect

    sig = inspect.signature(ElementResolver.resolve)
    assert sig.parameters["strict"].default is False
    assert sig.parameters["strict"].kind is inspect.Parameter.KEYWORD_ONLY, (
        "strict should be keyword-only so a positional description cannot land in it"
    )


# ── The actions that opt in ───────────────────────────────────────────────────

@pytest.mark.parametrize("action_name", ["assert_visible", "assert_text", "store"])
async def test_the_checking_actions_resolve_strictly(action_name):
    """
    assert_* verifies a fact about the page. `store` reads a value that every
    later `when:` clause and assertion then reasons about — a value taken off the
    wrong element is wrong everywhere downstream and announces nothing.
    """
    from stepper.engine.actions.factory import build_default_registry

    action = build_default_registry().create(action_name)

    resolver = MagicMock()
    resolver.resolve = AsyncMock(
        return_value=MagicMock(found=False, confidence=0.0, method="not-found")
    )
    # Both of these return early on a missing field and would never reach
    # resolve(): `store` without extra.key, `assert_text` without extra.expected.
    step = StepConfig(action=action_name, description="d",
                      element={"css": ".x"}, extra={"key": "k", "expected": "v"})

    await action.execute(MagicMock(), step, resolver, None, None)

    assert resolver.resolve.await_args is not None, f"{action_name} never resolved"
    assert resolver.resolve.await_args.kwargs.get("strict") is True, (
        f"{action_name} resolves leniently — it can pass against the wrong element"
    )


@pytest.mark.parametrize("action_name", ["click", "fill", "hover"])
async def test_the_acting_actions_do_not_resolve_strictly(action_name):
    """
    The other half of the contract. Making these strict would remove the
    resilience the resolver cascade exists to provide.
    """
    from stepper.engine.actions.factory import build_default_registry

    action = build_default_registry().create(action_name)

    resolver = MagicMock()
    resolver.resolve = AsyncMock(
        return_value=MagicMock(found=False, confidence=0.0, method="not-found")
    )
    step = StepConfig(action=action_name, description="d",
                      element={"css": ".x"}, input_value="v")

    await action.execute(MagicMock(), step, resolver, None, None)

    assert resolver.resolve.await_args.kwargs.get("strict") in (None, False), (
        f"{action_name} became strict — a click should still land after a redesign"
    )


# ── Shadow mode must not change what an assertion means ───────────────────────

async def test_shadow_runner_passes_strict_through(tmp_path):
    """
    --shadow wraps the resolver to compare strategies. If it dropped the flag, an
    assertion would silently go back to matching on description under that flag.
    """
    from stepper.engine.resolvers.shadow_runner import DriftLog, ShadowRunner

    inner = MagicMock()
    inner.resolve = AsyncMock(
        return_value=MagicMock(found=False, confidence=0.0, method="not-found")
    )
    runner = ShadowRunner(inner, strategies=[], drift_log=DriftLog(tmp_path / "drift.json"))

    await runner.resolve(MagicMock(), {"css": ".x"}, "desc", strict=True)

    assert inner.resolve.await_args.kwargs.get("strict") is True
