"""
Tests for the command-line interface.

Covers the pure parts — argv normalization, workflow-name resolution, workflow
description reading, and the parser's wiring — without touching a browser or
the run pipeline. The pipeline is a stub, which is the point of run_cli taking
it as an argument.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cli
from cli import (
    CommandError,
    build_parser,
    describe_workflow,
    normalize_argv,
    resolve_workflow,
    workflow_files,
)


@pytest.fixture
def stepper_root(tmp_path):
    """A miniature stepper/ tree: two sites, three workflows."""
    def write(site, stem, payload):
        path = tmp_path / "sites" / site / "workflows" / f"{stem}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    write("saucedemo", "sd_happy_path", {
        "name": "SauceDemo — happy path",
        "description": "A much longer paragraph that should not win.",
        "steps": [{"action": "sd_login"}, {"action": "sd_checkout"}],
    })
    write("saucedemo", "sd_smoke_test", {"name": "SauceDemo — smoke test", "steps": []})
    write("openlibrary", "ol_smoke_test", {"name": "OpenLibrary — smoke test",
                                           "steps": [{"action": "navigate"}]})
    return tmp_path


# ── Backwards compatibility ───────────────────────────────────────────────────

def test_bare_workflow_flag_becomes_a_run_command():
    argv, note = normalize_argv(["--workflow", "sd_happy_path", "--show"])

    assert argv == ["run", "--workflow", "sd_happy_path", "--show"]
    assert note is not None


def test_equals_form_of_the_workflow_flag_is_recognised():
    argv, _ = normalize_argv(["--workflow=sd_happy_path"])
    assert argv[0] == "run"


def test_bare_task_flag_becomes_a_run_command():
    argv, note = normalize_argv(["--task", "add Dune to my list"])

    assert argv == ["run", "--task", "add Dune to my list"]
    assert note is not None


def test_apply_heals_becomes_the_heal_apply_command():
    argv, note = normalize_argv(["--apply-heals", "sd_full_heal_flow", "--yes"])

    assert argv == ["heal", "apply", "sd_full_heal_flow", "--yes"]
    assert note is not None


def test_apply_heals_without_yes_does_not_invent_it():
    argv, _ = normalize_argv(["--apply-heals", "sd_full_heal_flow"])
    assert argv == ["heal", "apply", "sd_full_heal_flow"]


@pytest.mark.parametrize("argv", [
    ["run", "sd_happy_path"],
    ["list"],
    ["actions", "--site", "sd"],
    ["validate"],
    ["heal", "apply", "x"],
    ["--help"],
    ["-h"],
    [],
])
def test_explicit_commands_are_left_alone(argv):
    rewritten, note = normalize_argv(list(argv))

    assert rewritten == argv
    assert note is None


def test_an_unrecognised_first_argument_is_left_for_argparse():
    argv, note = normalize_argv(["bogus", "--show"])

    assert argv == ["bogus", "--show"]
    assert note is None


# ── Workflow discovery ────────────────────────────────────────────────────────

def test_workflows_are_grouped_by_site(stepper_root):
    found = workflow_files(stepper_root)

    assert sorted(found) == ["openlibrary", "saucedemo"]
    assert [p.stem for p in found["saucedemo"]] == ["sd_happy_path", "sd_smoke_test"]


@pytest.mark.parametrize("term", ["sauce", "saucedemo", "sd", "SD"])
def test_site_filter_accepts_a_directory_name_or_a_workflow_prefix(term, stepper_root):
    """`--site sd` must mean the same thing here as it does for actions."""
    assert sorted(workflow_files(stepper_root, term)) == ["saucedemo"]


def test_site_filter_returns_nothing_for_an_unknown_site(stepper_root):
    assert workflow_files(stepper_root, "nope") == {}


def test_description_prefers_the_short_name_over_the_long_description(stepper_root):
    path = stepper_root / "sites/saucedemo/workflows/sd_happy_path.json"

    description, steps = describe_workflow(path)

    assert description == "happy path"          # site prefix dropped
    assert steps == 2


def test_description_survives_an_unreadable_file(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    description, steps = describe_workflow(broken)

    assert description.startswith("<unreadable:")
    assert steps == 0


def test_a_bare_list_workflow_still_reports_its_step_count(tmp_path):
    path = tmp_path / "steps_only.json"
    path.write_text(json.dumps([{"action": "click"}, {"action": "fill"}]), encoding="utf-8")

    assert describe_workflow(path) == ("", 2)


# ── Name resolution ───────────────────────────────────────────────────────────

def test_a_bare_name_resolves_across_sites(stepper_root):
    resolved = resolve_workflow("sd_happy_path", stepper_root)

    assert resolved.stem == "sd_happy_path"
    assert resolved.exists()


def test_an_existing_path_is_used_as_given(stepper_root):
    path = stepper_root / "sites/openlibrary/workflows/ol_smoke_test.json"

    assert resolve_workflow(str(path), stepper_root) == path


def test_a_name_with_the_json_suffix_still_resolves(stepper_root):
    assert resolve_workflow("sd_happy_path.json", stepper_root).stem == "sd_happy_path"


def test_an_unknown_name_suggests_close_matches(stepper_root):
    with pytest.raises(CommandError) as excinfo:
        resolve_workflow("sd_happy", stepper_root)

    message = str(excinfo.value)
    assert "sd_happy_path" in message
    assert "did you mean" in message


def test_an_unknown_name_with_nothing_close_still_points_at_list(stepper_root):
    with pytest.raises(CommandError, match="Run 'list'"):
        resolve_workflow("zzzzzzzz", stepper_root)


def test_an_ambiguous_name_lists_every_match(tmp_path):
    for site in ("saucedemo", "openlibrary"):
        path = tmp_path / "sites" / site / "workflows" / "shared_name.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"steps": []}', encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        resolve_workflow("shared_name", tmp_path)

    message = str(excinfo.value)
    assert "matches 2 workflows" in message
    assert "saucedemo" in message and "openlibrary" in message


# ── Parser ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("command", ["run", "list", "actions", "validate", "heal"])
def test_every_advertised_command_parses(command):
    """The commands named in the module docstring and help are all wired up."""
    assert command in cli._COMMANDS
    build_parser().parse_args([command] if command != "heal" else ["heal"])


def test_run_accepts_a_positional_workflow():
    args = build_parser().parse_args(["run", "sd_happy_path", "--show", "--heal", "2"])

    assert args.workflow == "sd_happy_path"
    assert args.show is True
    assert args.heal == 2


def test_run_still_accepts_the_workflow_flag():
    args = build_parser().parse_args(["run", "--workflow", "sd_happy_path"])

    assert args.workflow_flag == "sd_happy_path"
    assert args.workflow is None


def test_run_defaults_are_conservative():
    args = build_parser().parse_args(["run", "sd_happy_path"])

    assert args.show is False
    assert args.heal == 0
    assert args.ci is False
    assert args.shadow is False


def test_validate_takes_any_number_of_workflows():
    assert build_parser().parse_args(["validate"]).workflows == []
    assert build_parser().parse_args(["validate", "a", "b"]).workflows == ["a", "b"]


def test_read_only_commands_are_marked_quiet():
    parser = build_parser()
    for command in (["list"], ["actions"], ["validate"], ["heal", "apply", "x"]):
        assert parser.parse_args(command).quiet is True, command
    assert parser.parse_args(["run", "x"]).quiet is False


# ── Dispatch ──────────────────────────────────────────────────────────────────

def test_no_command_prints_help_and_succeeds(capsys):
    pipeline = SimpleNamespace(load_env=lambda: None, _stepper_root=Path("."))

    assert cli.run_cli(pipeline, argv=[]) == 0
    assert "Commands" in capsys.readouterr().out


def test_a_command_error_is_reported_without_a_traceback(capsys):
    called: list = []
    pipeline = SimpleNamespace(
        load_env=lambda: None,
        _stepper_root=Path("/nowhere"),
        apply_heals=lambda *a: called.append(a),
    )

    code = cli.run_cli(pipeline, argv=["heal", "apply", "does_not_exist"])

    assert code == 1
    assert "error:" in capsys.readouterr().err
    assert called == []          # failed before touching the pipeline


def test_run_rejects_both_a_workflow_and_a_task():
    pipeline = SimpleNamespace(load_env=lambda: None, _stepper_root=Path("."))

    args = build_parser().parse_args(["run", "sd_happy_path", "--task", "do a thing"])

    with pytest.raises(CommandError, match="exactly one"):
        cli.cmd_run(args, pipeline)


def test_run_rejects_neither_a_workflow_nor_a_task():
    pipeline = SimpleNamespace(load_env=lambda: None, _stepper_root=Path("."))

    args = build_parser().parse_args(["run"])

    with pytest.raises(CommandError, match="exactly one"):
        cli.cmd_run(args, pipeline)
