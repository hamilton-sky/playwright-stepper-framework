"""
The PageModule conventions, checked against what the registry actually holds.

`base_page_module.py` states three rules in a docstring and enforces none of
them. One of them even appears as example code — "Must enforce naming
convention", followed by the `if not action.action_name.startswith(...)` that no
register() implementation actually contains.

The prefix rule is the one with teeth. Action names share a single flat
namespace across every site, so an `sd_` action accidentally registered as
`login` does not collide loudly — it registers fine, and the next site to want
`login` silently overwrites it, or `alias()` refuses for reasons that look
unrelated. Nothing catches it until a workflow runs the wrong site's action.

Rather than add enforcement to every register() — where it would be
copy-pasted and could be forgotten in the next one — the invariant is checked
here, once, against every action the registry ends up holding.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from stepper.engine.actions.factory import build_default_registry
from stepper.engine.interfaces import ActionStrategy
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

_SITES_DIR = Path(__file__).resolve().parents[2] / "sites"

def _owning_page_module(action):
    """The PageModule class an action is nested inside, or None."""
    owner  = type(action).__qualname__.split(".")[0]
    module = importlib.import_module(type(action).__module__)
    return getattr(module, owner, None)


def _action_domain(action) -> str:
    """Which domain's session an action acts on. PageModule defaults to "web"."""
    return getattr(_owning_page_module(action), "domain", "web")


#: Action names that deliberately break the f"{site}_" rule, with the reason.
#: `collect_items` predates the convention; OLSearchPage.register() aliases
#: `ol_collect_books` to the same instance so workflows can use either, and the
#: shipped workflows use the prefixed spelling. See .claude/rules/glue-layer.md.
_PREFIX_EXEMPT = {"collect_items"}


@pytest.fixture(scope="module")
def registries() -> tuple[set[str], dict]:
    """(engine action names, {site action name: action}) from a real startup."""
    registry = build_default_registry()
    engine_names = set(registry.names())

    for register_path in sorted(_SITES_DIR.glob("*/register.py")):
        site = register_path.parent.name
        importlib.import_module(f"stepper.sites.{site}.register").register(registry)

    site_actions = {
        name: registry.create(name)
        for name in registry.names()
        if name not in engine_names
    }
    return engine_names, site_actions


def test_the_sites_actually_register_something(registries):
    _engine, site_actions = registries

    assert site_actions, "no site actions registered; every test below would pass vacuously"


def test_every_site_action_is_prefixed_with_its_site(registries):
    """
    The rule base_page_module documents and nothing enforces. One flat namespace
    across every site means an unprefixed name is a collision waiting for the
    next site that wants it.
    """
    _engine, site_actions = registries

    offenders = []
    for name, action in site_actions.items():
        if name in _PREFIX_EXEMPT:
            continue
        page_module = _owning_page_module(action)
        site = getattr(page_module, "site", None)
        if site and not name.startswith(f"{site}_"):
            offenders.append(f"{name} (declared site={site!r} on {owner})")

    assert not offenders, (
        "These action names do not start with their site prefix:\n  "
        + "\n  ".join(offenders)
        + "\n\nRename them, or add the name to _PREFIX_EXEMPT here with a reason."
    )


def test_the_documented_exemption_is_still_real(registries):
    """
    If `collect_items` is ever renamed, this exemption becomes a lie that quietly
    stops checking a name nobody uses.
    """
    _engine, site_actions = registries

    for name in _PREFIX_EXEMPT:
        assert name in site_actions, (
            f"{name!r} is exempted from the prefix rule but is not registered; "
            "drop it from _PREFIX_EXEMPT"
        )


def test_the_alias_and_its_target_are_the_same_instance(registries):
    """
    `alias()` binds a second name to the *same* object, so an action carrying
    state behaves identically whichever spelling a workflow uses. Two instances
    would diverge the moment one of them stored anything.
    """
    _engine, site_actions = registries

    assert site_actions["collect_items"] is site_actions["ol_collect_books"]


def test_every_web_action_subclasses_glue_action(registries):
    """
    GlueAction is what supplies _build_pom, and _build_pom is what makes
    page=/resolver=/behaviour= keyword-mandatory. Subclassing ActionStrategy
    directly compiles, runs, and silently skips the resolver cascade.

    Web actions only. The rule protects the POM layer, and a domain with no
    selectors has no POM layer to protect — it is Flow → Action, two layers
    rather than three. A PageModule declaring a non-web `domain` is opting out
    of a rule that has nothing to say about it, not evading one that does.
    See docs/universal-runner-plan.md §4.
    """
    _engine, site_actions = registries

    offenders = [
        f"{name} ({type(action).__qualname__})"
        for name, action in site_actions.items()
        if _action_domain(action) == "web" and not isinstance(action, GlueAction)
    ]

    assert not offenders, (
        "These site actions do not subclass GlueAction, so they can construct a "
        "POM without a resolver:\n  " + "\n  ".join(offenders)
    )


def test_a_non_web_action_really_is_declared_non_web(registries):
    """
    The exemption above keys off PageModule.domain, so it is only as honest as
    that attribute. A web action that subclassed ActionStrategy directly and
    then declared domain="something" to quiet the test would be exactly the
    bug the rule exists to catch — so check the opt-out is used by a module
    that genuinely has no POMs behind it.
    """
    _engine, site_actions = registries

    non_web = {
        name: action for name, action in site_actions.items()
        if _action_domain(action) != "web"
    }

    for name, action in non_web.items():
        module = importlib.import_module(type(action).__module__)
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "_build_pom" not in source, (
            f"{name} is declared non-web but its module builds POMs"
        )
        assert "poms." not in source, (
            f"{name} is declared non-web but its module imports from poms/"
        )


def test_every_site_action_has_a_description(registries):
    """`main.py actions` reads the docstring; a bare action lists as blank."""
    _engine, site_actions = registries

    undocumented = [name for name, a in site_actions.items() if not (type(a).__doc__ or "").strip()]

    assert not undocumented, "These site actions have no docstring: " + ", ".join(undocumented)


def test_no_site_action_shadows_an_engine_action(registries):
    """
    register() overwrites by name. A site action called `click` would replace the
    engine's, for every site, for the whole run.
    """
    engine_names, site_actions = registries

    collisions = sorted(set(site_actions) & engine_names)

    assert not collisions, "Site actions shadowing engine actions: " + ", ".join(collisions)


# ── The ABC itself ────────────────────────────────────────────────────────────

def test_a_page_module_cannot_be_instantiated_without_register():
    class Incomplete(PageModule):
        site = "xx"

    with pytest.raises(TypeError):
        Incomplete()      # type: ignore[abstract]


def test_every_page_module_declares_a_site(registries):
    """`site` has no default; a module without one fails at the prefix check
    above with a confusing AttributeError rather than a clear message."""
    _engine, site_actions = registries

    for action in site_actions.values():
        module = importlib.import_module(type(action).__module__)
        owner = getattr(module, type(action).__qualname__.split(".")[0], None)
        if owner is not None:
            assert getattr(owner, "site", None), f"{owner.__name__} declares no site"


def test_glue_action_is_an_action_strategy():
    """The glue layer plugs into the same registry as the engine actions."""
    assert issubclass(GlueAction, ActionStrategy)
