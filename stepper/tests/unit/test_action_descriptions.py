"""
The first line of every action docstring is user-facing copy.

`stepper/main.py actions` renders ActionSchemaExtractor output, and the AiHealer
embeds the same schema in its prompt. Both take the *first non-empty line* of the
class docstring, so a docstring that wraps mid-clause prints a fragment ending in
a comma — and gives the healer a truncated description to reason about.

These tests are the contract that keeps that line readable on its own.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_STEPPER_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def schema():
    """Every registered action's description, sites included."""
    from bootstrap.infra import register_all_sites
    from engine.actions.factory import build_default_registry
    from engine.actions.strategies import RunWorkflowAction
    from engine.planner.schema_extractor import ActionSchemaExtractor

    # run_workflow is bound at pipeline-build time but is a real action name.
    registry = build_default_registry().register(RunWorkflowAction())
    register_all_sites(registry, _STEPPER_ROOT, screenshots_dir=None)
    return ActionSchemaExtractor.extract(registry)


def test_the_registry_is_not_empty(schema):
    assert len(schema) > 30, "site registration probably failed"


def test_every_action_has_a_description(schema):
    missing = [name for name, meta in schema.items()
               if not meta.get("description") or meta["description"] == name]

    assert not missing, (
        "These actions have no docstring, so `actions` prints their bare name:\n  "
        + "\n  ".join(missing)
    )


def test_no_description_ends_mid_clause(schema):
    """
    A first line that wraps into the second reads as a fragment.

    Write the docstring so line one is a whole sentence, then elaborate below:

        \"\"\"
        Add every collected book to the want-to-read shelf.

        Iterates over context.collected_items, opening each book page...
        \"\"\"
    """
    fragments = [
        f"{name:<24} {meta['description']}"
        for name, meta in sorted(schema.items())
        if not meta["description"].rstrip().endswith((".", "!", "?", ")"))
    ]

    assert not fragments, (
        "These descriptions do not end as a complete sentence, so the CLI prints "
        "a fragment. Put a whole sentence on the docstring's first line:\n  "
        + "\n  ".join(fragments)
    )


def test_descriptions_fit_a_terminal_line(schema):
    """Two columns of an 80-column terminal go to the name; the rest is the text."""
    too_long = [
        f"{name} ({len(meta['description'])} chars)"
        for name, meta in sorted(schema.items())
        if len(meta["description"]) > 100
    ]

    assert not too_long, (
        "These descriptions are too long to read in a terminal listing:\n  "
        + "\n  ".join(too_long)
    )
