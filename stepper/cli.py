"""
cli.py — the command line interface.

main.py owns the run pipeline (RunConfig → prepare_run → build_pipeline →
execute_pipeline); this module owns how a person drives it.

The pipeline module is *passed in* rather than imported. main.py runs as a
script, so importing it back by name would create a second copy of the module —
`run_cli(sys.modules[__name__])` avoids that and keeps the dependency explicit.

Commands
    run         Run a workflow file or a natural-language task
    list        List available workflows, grouped by site
    actions     List every registered action and what it does
    validate    Check a workflow without launching a browser
    heal        Review and apply self-healing suggestions

The pre-subcommand syntax (`main.py --workflow X`) still works — see
normalize_argv.
"""
from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_COMMANDS = ("run", "list", "actions", "validate", "heal")


class CommandError(Exception):
    """A user-facing failure: printed as a message, never as a traceback."""


# ── Output ────────────────────────────────────────────────────────────────────

def _out(text: str = "") -> None:
    """
    Print, surviving Windows consoles that cannot encode the framework's output.

    Same guard as ConsoleReporter._safe_print; duplicated rather than imported
    because that one is private to the reporter module.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


# ── Workflow discovery ────────────────────────────────────────────────────────

def workflow_files(stepper_root: Path, site: str | None = None) -> dict[str, list[Path]]:
    """
    Every workflow JSON on disk, grouped by site directory name.

    `site` matches either the directory name ('sauce') or the action/workflow
    prefix ('sd'), so the same spelling works here and in `actions --site`.
    """
    found: dict[str, list[Path]] = {}
    for path in sorted(stepper_root.glob("sites/*/workflows/*.json")):
        found.setdefault(path.parent.parent.name, []).append(path)

    if not site:
        return found

    term = site.lower()
    return {
        name: paths for name, paths in found.items()
        if name.startswith(term) or any(p.stem.startswith(f"{term}_") for p in paths)
    }


def describe_workflow(path: Path) -> tuple[str, int]:
    """(description, step count) for one workflow, tolerant of a malformed file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"<unreadable: {exc}>", 0

    if isinstance(data, list):
        return "", len(data)

    steps = data.get("steps", [])
    # "name" is the one-line label ("SauceDemo — happy path"); "description" is
    # usually a paragraph, so it is only the fallback. The site prefix is
    # dropped because the site is already the column header.
    text = data.get("name") or data.get("description", "")
    if "—" in text:
        text = text.split("—", 1)[1].strip()
    return text, len(steps) if isinstance(steps, list) else 0


def resolve_workflow(name: str, stepper_root: Path) -> Path:
    """
    Turn a bare workflow name into a path: 'sd_happy_path' → the file on disk.

    An existing path is used as given, so full paths keep working.
    """
    given = Path(name)
    if given.exists():
        return given

    stem = given.stem if given.suffix == ".json" else name
    matches = sorted(stepper_root.glob(f"sites/*/workflows/{stem}.json"))

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        listed = "\n".join(f"  {m}" for m in matches)
        raise CommandError(
            f"'{stem}' matches {len(matches)} workflows — name one by path:\n{listed}"
        )

    known = [p.stem for group in workflow_files(stepper_root).values() for p in group]
    close = difflib.get_close_matches(stem, known, n=3, cutoff=0.5)
    hint = f" — did you mean {', '.join(repr(c) for c in close)}?" if close else ""
    raise CommandError(
        f"No workflow named '{stem}'{hint}\nRun 'list' to see all {len(known)} workflows."
    )


# ── Action discovery ──────────────────────────────────────────────────────────

def actions_by_site(stepper_root: Path) -> tuple[dict[str, list[str]], dict[str, dict]]:
    """
    Registered action names grouped by owner, plus the schema of descriptions.

    Each site is registered into its own throwaway registry, so which actions
    belong to which site is read from the registration itself rather than
    guessed from name prefixes.
    """
    import importlib

    from bootstrap.infra import register_all_sites
    from engine.actions.factory import build_default_registry
    from engine.actions.strategies import RunWorkflowAction
    from engine.planner.schema_extractor import ActionSchemaExtractor

    def _engine_registry():
        # run_workflow is registered at pipeline-build time rather than in
        # build_default_registry, but workflows do name it — so it belongs here.
        return build_default_registry().register(RunWorkflowAction())

    engine_names = set(_engine_registry().names())
    grouped: dict[str, list[str]] = {"engine": sorted(engine_names)}

    for register_path in sorted((stepper_root / "sites").glob("*/register.py")):
        site = register_path.parent.name
        registry = build_default_registry()
        importlib.import_module(f"sites.{site}.register").register(
            registry, screenshots_dir=None
        )
        grouped[site] = sorted(set(registry.names()) - engine_names)

    full = _engine_registry()
    register_all_sites(full, stepper_root, screenshots_dir=None)
    return grouped, ActionSchemaExtractor.extract(full)


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_list(args, pipeline) -> int:
    root  = pipeline._stepper_root
    found = workflow_files(root, args.site)

    if not found:
        known = ", ".join(sorted(workflow_files(root)))
        raise CommandError(
            f"No site matches '{args.site}'. Known sites: {known} "
            "(a prefix like 'sd' or 'sauce' works too)."
        )

    # One width across every site, so the table reads as one table.
    width = max(len(p.stem) for paths in found.values() for p in paths)
    total = 0

    for site, paths in found.items():
        count = f"{len(paths)} workflow{'s' if len(paths) != 1 else ''}"
        _out(f"\n{site}{count:>{max(1, width + 22 - len(site))}}")
        for path in paths:
            description, steps = describe_workflow(path)
            _out(f"  {path.stem:<{width}}  {steps:>2} steps   {description[:52]}")
        total += len(paths)

    _out(f"\n{total} workflow{'s' if total != 1 else ''}."
         f"  Run one with:  run <name>")
    return 0


def cmd_actions(args, pipeline) -> int:
    all_groups, schema = actions_by_site(pipeline._stepper_root)
    total = sum(len(names) for names in all_groups.values())
    grouped = all_groups

    if args.site:
        wanted = args.site.lower()
        grouped = {
            site: names for site, names in all_groups.items()
            if site.startswith(wanted) or any(n.startswith(f"{wanted}_") for n in names)
        }
        if not grouped:
            raise CommandError(
                f"No site matches '{args.site}'. Use one of: "
                + ", ".join(all_groups)
            )

    shown = 0
    for site, names in grouped.items():
        if not names:
            continue
        _out(f"\n{site}")
        width = max(len(n) for n in names)
        for name in names:
            description = schema.get(name, {}).get("description", "").rstrip(",")
            _out(f"  {name:<{width}}  {description}")
        shown += len(names)

    suffix = "" if shown == total else f" of {total}"
    _out(f"\n{shown}{suffix} actions. Descriptions come from each action's docstring.")
    return 0


def cmd_validate(args, pipeline) -> int:
    from engine.planner.validator import PlanValidationError

    root = pipeline._stepper_root
    if args.workflows:
        targets = [resolve_workflow(w, root) for w in args.workflows]
    else:
        targets = [p for group in workflow_files(root).values() for p in group]
        _out(f"Validating all {len(targets)} workflows...\n")

    width  = max(len(p.stem) for p in targets)
    failed = 0

    # Load settings once: each load re-emits the provider-key warnings, and
    # only storage_state_path varies between workflows.
    base = pipeline.build_settings(pipeline.RunConfig(workflow_path=str(targets[0])))

    for path in targets:
        cfg = pipeline.RunConfig(workflow_path=str(path))
        try:
            steps = pipeline.validate_plan(
                cfg, base._replace(storage_state_path=cfg.storage_state_path)
            )
        except PlanValidationError as exc:
            failed += 1
            _out(f"  FAIL  {path.stem:<{width}}")
            for line in str(exc).split("Registered actions:")[0].strip().splitlines()[1:]:
                _out(f"          {line}")
        except Exception as exc:                      # unreadable JSON, bad variables
            failed += 1
            _out(f"  FAIL  {path.stem:<{width}}  {type(exc).__name__}: {exc}")
        else:
            _out(f"  OK    {path.stem:<{width}}  {len(steps):>2} steps")

    _out(f"\n{len(targets) - failed}/{len(targets)} valid.")
    if failed:
        _out("Run 'actions' to see every registered action name.")
    return 1 if failed else 0


def cmd_heal_apply(args, pipeline) -> int:
    pipeline.apply_heals(resolve_workflow(args.workflow, pipeline._stepper_root), args.yes)
    return 0


def cmd_run(args, pipeline) -> int:
    target = args.workflow or args.workflow_flag
    if bool(target) == bool(args.task):
        raise CommandError("Provide exactly one of a workflow or --task.")

    workflow_path = str(resolve_workflow(target, pipeline._stepper_root)) if target else None

    cli_vars: dict[str, Any] = {}
    if args.vars:
        try:
            cli_vars = json.loads(args.vars)
        except json.JSONDecodeError as exc:
            raise CommandError(f"--vars is not valid JSON: {exc}") from exc
        if not isinstance(cli_vars, dict):
            raise CommandError(
                '--vars must be a JSON object, e.g. \'{"query":"Dune"}\''
            )

    cfg = pipeline.RunConfig(
        workflow_path=workflow_path,
        task=args.task,
        headless=not args.show,
        allure_serve=args.allure_serve,
        record_video=args.video,
        variables=cli_vars or None,
        max_heal_attempts=args.heal,
        shadow=args.shadow,
        ci=args.ci,
        ci_output=args.ci_output,
    )

    if args.data:
        data_path = Path(args.data)
        if not data_path.exists():
            raise CommandError(f"--data file not found: {data_path}")
        rows = json.loads(data_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise CommandError("--data file must contain a JSON array of objects")
        asyncio.run(pipeline.run_data_rows(cfg, rows, cli_vars))
        if args.allure_serve:
            pipeline.serve_allure(pipeline._stepper_root)
        return 0

    results = asyncio.run(pipeline.run(**{
        "workflow_path":     cfg.workflow_path,
        "task":              cfg.task,
        "headless":          cfg.headless,
        "allure_serve":      cfg.allure_serve,
        "record_video":      cfg.record_video,
        "variables":         cfg.variables,
        "max_heal_attempts": cfg.max_heal_attempts,
        "shadow":            cfg.shadow,
        "ci":                cfg.ci,
        "ci_output":         cfg.ci_output,
    }))
    # A failing workflow is a failing command — CI depends on the exit code.
    return 1 if any(r.status == "failed" for r in results) else 0


# ── Parser ────────────────────────────────────────────────────────────────────

_EPILOG = """\
Examples
  list                             show every workflow
  run sd_happy_path --show         run one with a visible browser
  run sd_happy_path --heal 2       let the healer fix broken selectors
  validate                         check every workflow, no browser
  actions --site sd                what SauceDemo can do
  heal apply sd_full_heal_flow     review and apply heal suggestions

Workflows are named, not pathed: 'sd_happy_path' resolves across all sites.
Full paths still work everywhere a name is accepted.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stepper",
        description="Stepper — JSON-driven browser automation on Playwright.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(title="Commands", metavar="<command>", dest="command")

    # ── run ───────────────────────────────────────────────────────────────────
    run_p = sub.add_parser(
        "run", help="Run a workflow file or a natural-language task",
        description="Run a workflow, or plan one from a natural-language task.",
        epilog="Examples\n"
               "  run sd_happy_path\n"
               "  run ol_search_and_add --vars '{\"query\":\"Dune\"}'\n"
               "  run ol_data_driven --data testdata.json\n"
               "  run --task 'log in and add Dune to my reading list'\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_p.add_argument("workflow", nargs="?", metavar="WORKFLOW",
                       help="Workflow name (sd_happy_path) or path to a JSON file")
    run_p.add_argument("--workflow", dest="workflow_flag", help=argparse.SUPPRESS)
    run_p.add_argument("--task", metavar="TEXT",
                       help="Natural-language task for the AI planner instead of a workflow")

    browser = run_p.add_argument_group("Browser")
    browser.add_argument("--show", action="store_true",
                         help="Show the browser window (default: headless)")
    browser.add_argument("--video", action="store_true",
                         help="Record video into the run's report directory")

    data = run_p.add_argument_group("Data")
    data.add_argument("--vars", metavar="JSON",
                      help='Variable overrides, e.g. \'{"query":"Dune"}\'')
    data.add_argument("--data", metavar="FILE",
                      help="JSON array of variable objects; runs the workflow once per row")

    healing = run_p.add_argument_group("Healing")
    healing.add_argument("--heal", type=int, default=0, metavar="N",
                         help="Max heal attempts per failed step (default 0, capped at 3). "
                              "Needs GROQ_API_KEY, GEMINI_API_KEY or ANTHROPIC_API_KEY")

    output = run_p.add_argument_group("Output")
    output.add_argument("--ci", action="store_true",
                        help="Print a structured JSON run summary to stdout")
    output.add_argument("--ci-output", metavar="FILE",
                        help="Also write that summary to FILE")
    output.add_argument("--allure-serve", action="store_true",
                        help="Open the Allure report when the run finishes")

    diagnostics = run_p.add_argument_group("Diagnostics")
    diagnostics.add_argument("--shadow", action="store_true",
                             help="Run every resolver strategy in the background and log drift")
    run_p.set_defaults(func=cmd_run, quiet=False)

    # ── list ──────────────────────────────────────────────────────────────────
    list_p = sub.add_parser(
        "list", help="List available workflows, grouped by site",
        description="List every workflow on disk with its step count and description.",
    )
    list_p.add_argument("--site", metavar="SITE",
                        help="Only this site, by name (saucedemo) or prefix (sd)")
    list_p.set_defaults(func=cmd_list, quiet=True)

    # ── actions ───────────────────────────────────────────────────────────────
    actions_p = sub.add_parser(
        "actions", help="List every registered action and what it does",
        description="List the actions a workflow's \"action\" field can name. "
                    "Descriptions come from each action class's docstring.",
    )
    actions_p.add_argument("--site", metavar="SITE",
                           help="Only this site's actions, by name (saucedemo) or prefix (sd)")
    actions_p.set_defaults(func=cmd_actions, quiet=True)

    # ── validate ──────────────────────────────────────────────────────────────
    validate_p = sub.add_parser(
        "validate", help="Check a workflow without launching a browser",
        description="Check that every step names a registered action and carries a "
                    "description. Launches nothing and writes nothing. Exits 1 if "
                    "any workflow is invalid, so it works as a CI gate.",
        epilog="Examples\n"
               "  validate                    every workflow\n"
               "  validate sd_happy_path      just this one\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    validate_p.add_argument("workflows", nargs="*", metavar="WORKFLOW",
                            help="Workflow names or paths (default: all of them)")
    validate_p.set_defaults(func=cmd_validate, quiet=True)

    # ── heal ──────────────────────────────────────────────────────────────────
    heal_p = sub.add_parser(
        "heal", help="Review and apply self-healing suggestions",
        description="Work with the heal suggestions a --heal run produced.",
    )
    heal_sub = heal_p.add_subparsers(title="Subcommands", metavar="<subcommand>",
                                     dest="heal_command")
    apply_p = heal_sub.add_parser(
        "apply", help="Apply heal_suggestions.json to a workflow",
        description="Show each suggested selector change and, once confirmed, "
                    "write it into the workflow JSON.",
    )
    apply_p.add_argument("workflow", metavar="WORKFLOW",
                         help="Workflow name or path to patch")
    apply_p.add_argument("--yes", action="store_true",
                         help="Skip the confirmation prompt")
    apply_p.set_defaults(func=cmd_heal_apply, quiet=True)
    heal_p.set_defaults(func=lambda a, p: (heal_p.print_help(), 0)[1])

    return parser


# ── Backwards compatibility ───────────────────────────────────────────────────

def normalize_argv(argv: list[str]) -> tuple[list[str], str | None]:
    """
    Accept the flag-only syntax that predates these commands.

    `--workflow X` becomes `run X`, `--apply-heals X` becomes `heal apply X`.
    Returns the rewritten argv and a note to show once, or None when the caller
    already used a command.
    """
    if not argv or argv[0] in _COMMANDS or argv[0] in ("-h", "--help"):
        return argv, None

    if "--apply-heals" in argv:
        i = argv.index("--apply-heals")
        if i + 1 >= len(argv):
            return argv, None                      # let argparse report it
        rewritten = ["heal", "apply", argv[i + 1]]
        if "--yes" in argv:
            rewritten.append("--yes")
        return rewritten, "'--apply-heals X' is now 'heal apply X'"

    legacy_run = any(a in ("--workflow", "--task") or
                     a.startswith(("--workflow=", "--task=")) for a in argv)
    if legacy_run:
        return ["run", *argv], "'--workflow X' is now 'run X'"

    return argv, None


# ── Entry point ───────────────────────────────────────────────────────────────

def run_cli(pipeline, argv: list[str] | None = None) -> int:
    """
    Parse argv and dispatch. `pipeline` is the main module holding the run API.

    Returns the process exit code: 0 for success, 1 for a failed run or an
    invalid workflow, 2 for a usage error (argparse's own convention).
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    argv, deprecation = normalize_argv(argv)

    parser = build_parser()
    args   = parser.parse_args(argv)

    if not getattr(args, "func", None):
        parser.print_help()
        return 0

    # Read-only commands print their own complete output, so the pipeline's
    # per-step INFO logging is noise there; a run wants to see it.
    logging.basicConfig(
        level=logging.WARNING if getattr(args, "quiet", False) else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    pipeline.load_env()

    if deprecation:
        print(f"note: {deprecation} — the old form still works.", file=sys.stderr)

    try:
        return args.func(args, pipeline)
    except CommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
