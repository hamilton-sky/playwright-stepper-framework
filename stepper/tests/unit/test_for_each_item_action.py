"""
ForEachItemAction — where the items come from, and what {{tokens}} they expose.

The loop is how a workflow fans one collected list into many steps, and its
token substitution is the only contract between a collect step and the steps
that consume it. Both were untested.

No browser — the page is a stub.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.actions.strategies import ForEachItemAction
from engine.interfaces import ActionFactory, ActionStrategy, ExecutionContext, StepConfig, StepResult


# ── Doubles ───────────────────────────────────────────────────────────────────

class SpyAction(ActionStrategy):
    """Records the fully-substituted step it was handed."""

    action_name = "spy"
    read_only = True

    def __init__(self):
        self.seen: list[StepConfig] = []

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.seen.append(step)
        return StepResult(step=step, status="passed")


class ExplodingAction(ActionStrategy):
    action_name = "exploding"
    read_only = True

    def __init__(self):
        self.calls = 0

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.calls += 1
        raise RuntimeError(f"item {self.calls} blew up")


class FakeFactory(ActionFactory):
    def __init__(self, mapping):
        self._mapping = mapping

    def create(self, action_name):
        return self._mapping[action_name]


@pytest.fixture
def page():
    p = MagicMock()
    p.screenshot = AsyncMock()
    # Attributes the action falls back to must be absent unless a test sets them.
    del p._collected_items
    del p._collected_books
    return p


def run_loop(page, items, sub_steps, tmp_path, factory_map, context=None):
    ctx = context or ExecutionContext()
    if items is not None:
        ctx.collected_items = items
    action = ForEachItemAction(FakeFactory(factory_map), screenshots_dir=tmp_path)
    step = StepConfig(action="for_each_item", description="loop",
                      extra={"steps": sub_steps})
    result = asyncio.run(action.execute(page, step, MagicMock(), ctx))
    return result, ctx


# ── Where items come from ─────────────────────────────────────────────────────

def test_iterates_context_collected_items(page, tmp_path):
    spy = SpyAction()

    result, _ = run_loop(page, ["/a", "/b", "/c"],
                         [{"action": "spy", "description": "visit {{item_url}}"}],
                         tmp_path, {"spy": spy})

    assert result.status == "passed"
    assert [s.description for s in spy.seen] == ["visit /a", "visit /b", "visit /c"]


def test_falls_back_to_the_legacy_page_attribute(page, tmp_path):
    """Older flows stashed the list on the page; that path is still live."""
    spy = SpyAction()
    page._collected_books = ["/legacy"]

    run_loop(page, None, [{"action": "spy", "description": "visit {{item_url}}"}],
             tmp_path, {"spy": spy})

    assert [s.description for s in spy.seen] == ["visit /legacy"]


def test_an_empty_list_runs_nothing_and_still_passes(page, tmp_path):
    spy = SpyAction()

    result, _ = run_loop(page, [], [{"action": "spy"}], tmp_path, {"spy": spy})

    assert result.status == "passed"
    assert spy.seen == []


# ── Token substitution ────────────────────────────────────────────────────────

def test_item_url_and_book_url_are_both_available(page, tmp_path):
    """book_url is the backwards-compatible spelling of item_url."""
    spy = SpyAction()

    run_loop(page, ["/works/OL1W"],
             [{"action": "spy", "description": "{{item_url}} and {{book_url}}"}],
             tmp_path, {"spy": spy})

    assert spy.seen[0].description == "/works/OL1W and /works/OL1W"


def test_index_is_one_based(page, tmp_path):
    spy = SpyAction()

    run_loop(page, ["/a", "/b"],
             [{"action": "spy", "description": "item {{index}}"}],
             tmp_path, {"spy": spy})

    assert [s.description for s in spy.seen] == ["item 1", "item 2"]


@pytest.mark.parametrize("url_key", ["url", "href", "link"])
def test_a_dict_item_can_name_its_url_three_ways(url_key, page, tmp_path):
    spy = SpyAction()

    run_loop(page, [{url_key: "/works/OL1W"}],
             [{"action": "spy", "description": "visit {{item_url}}"}],
             tmp_path, {"spy": spy})

    assert spy.seen[0].description == "visit /works/OL1W"


def test_dict_keys_are_exposed_as_item_dot_key(page, tmp_path):
    spy = SpyAction()

    run_loop(page, [{"url": "/a", "title": "Dune", "year": 1965}],
             [{"action": "spy", "description": "{{item.title}} ({{item.year}})"}],
             tmp_path, {"spy": spy})

    assert spy.seen[0].description == "Dune (1965)"


def test_a_pure_token_reference_preserves_the_original_type(page, tmp_path):
    """"{{item.year}}" alone stays an int rather than becoming "1965"."""
    spy = SpyAction()

    run_loop(page, [{"url": "/a", "year": 1965}],
             [{"action": "spy", "description": "x", "extra": {"year": "{{item.year}}"}}],
             tmp_path, {"spy": spy})

    assert spy.seen[0].extra["year"] == 1965


def test_a_dict_item_with_no_url_key_substitutes_empty(page, tmp_path):
    spy = SpyAction()

    run_loop(page, [{"title": "Dune"}],
             [{"action": "spy", "description": "visit '{{item_url}}'"}],
             tmp_path, {"spy": spy})

    assert spy.seen[0].description == "visit ''"


def test_substitution_does_not_mutate_the_original_step_dicts(page, tmp_path):
    """Each iteration must start from the template, not the previous result."""
    spy = SpyAction()
    sub_steps = [{"action": "spy", "description": "visit {{item_url}}"}]

    run_loop(page, ["/a", "/b"], sub_steps, tmp_path, {"spy": spy})

    assert sub_steps[0]["description"] == "visit {{item_url}}"
    assert [s.description for s in spy.seen] == ["visit /a", "visit /b"]


# ── Multiple sub-steps ────────────────────────────────────────────────────────

def test_every_sub_step_runs_for_every_item(page, tmp_path):
    spy = SpyAction()

    run_loop(page, ["/a", "/b"],
             [{"action": "spy", "description": "one {{index}}"},
              {"action": "spy", "description": "two {{index}}"}],
             tmp_path, {"spy": spy})

    assert [s.description for s in spy.seen] == ["one 1", "two 1", "one 2", "two 2"]


# ── Failure handling ──────────────────────────────────────────────────────────

def test_one_failing_item_does_not_stop_the_loop(page, tmp_path):
    """The loop is best-effort: item 2 blowing up must not skip item 3."""
    boom = ExplodingAction()

    result, _ = run_loop(page, ["/a", "/b", "/c"], [{"action": "exploding"}],
                         tmp_path, {"exploding": boom})

    assert result.status == "passed"
    assert boom.calls == 3


def test_a_failing_item_is_screenshotted(page, tmp_path):
    boom = ExplodingAction()

    run_loop(page, ["/a", "/b"], [{"action": "exploding"}],
             tmp_path, {"exploding": boom})

    assert page.screenshot.await_count == 2
    shots = [c.kwargs["path"] for c in page.screenshot.await_args_list]
    assert shots[0].endswith("error_book_1.png")
    assert shots[1].endswith("error_book_2.png")
