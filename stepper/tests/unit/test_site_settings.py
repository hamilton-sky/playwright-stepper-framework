"""
Engine settings come from the site being run — not always OpenLibrary's.

`load_settings_safe` used to `import poms.openLibrary.config` unconditionally,
so a SauceDemo run took its browser and slow-mo from OpenLibrary. Every site
declares an ENV_MAP, but only one of them reached the engine: SAUCEDEMO_BROWSER
was documented, parsed by its own config module, and then discarded.

Also covers the shared loader those config modules now share.
"""
from __future__ import annotations

import pytest

from bootstrap.settings import RunSettings, load_settings_safe, site_config_module
from poms.shared.config import load_config_data, parse_bool, resolve_path


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """No inherited site config — these tests set exactly what they mean to."""
    for var in (
        "SAUCEDEMO_BROWSER", "SAUCEDEMO_SLOW_MO_MS", "SAUCEDEMO_HEADLESS",
        "OPENLIBRARY_BROWSER", "OPENLIBRARY_SLOW_MO_MS", "OPENLIBRARY_USE_VISUAL_AI",
        "PHPTRAVELS_SLOW_MO", "PHPTRAVELS_HEADLESS",
    ):
        monkeypatch.delenv(var, raising=False)
    # validate_ai_config only warns, but keep the output quiet either way.
    monkeypatch.setenv("GROQ_API_KEY", "test-key")


# ── Which module answers for which site ───────────────────────────────────────

@pytest.mark.parametrize("site,expected", [
    ("saucedemo",   "poms.saucedemo.config"),
    ("openlibrary", "poms.openLibrary.config"),   # directory casing differs
    ("phptravels",  "poms.phpTravels.config"),
    ("OpenLibrary", "poms.openLibrary.config"),   # and the match ignores it
])
def test_a_site_resolves_to_its_own_config_module(site, expected):
    assert site_config_module(site) == expected


@pytest.mark.parametrize("site", ["shared", "nosuchsite", "", None])
def test_a_non_site_resolves_to_nothing(site):
    """`shared` is RunConfig.site for a --task run, and also a real POM package."""
    assert site_config_module(site) is None


def test_the_shared_algorithm_module_is_not_mistaken_for_a_site():
    """poms/shared/config.py holds the loader, not a site's settings."""
    assert site_config_module("shared") is None


# ── The bug: each site's own env vars now reach the engine ────────────────────

def test_saucedemo_env_vars_reach_the_engine(monkeypatch):
    """Regression: SAUCEDEMO_BROWSER was documented and silently ignored."""
    monkeypatch.setenv("SAUCEDEMO_BROWSER", "firefox")
    monkeypatch.setenv("SAUCEDEMO_SLOW_MO_MS", "250")

    settings = load_settings_safe("saucedemo")

    assert settings.browser == "firefox"
    assert settings.slow_mo == 250


def test_openlibrary_env_vars_do_not_leak_into_another_site(monkeypatch):
    monkeypatch.setenv("OPENLIBRARY_BROWSER", "webkit")

    assert load_settings_safe("openlibrary").browser == "webkit"
    assert load_settings_safe("saucedemo").browser == "chromium"


def test_each_site_is_read_independently(monkeypatch):
    monkeypatch.setenv("SAUCEDEMO_BROWSER", "firefox")
    monkeypatch.setenv("OPENLIBRARY_BROWSER", "webkit")

    assert load_settings_safe("saucedemo").browser == "firefox"
    assert load_settings_safe("openlibrary").browser == "webkit"
    assert load_settings_safe("phptravels").browser == "chromium"   # declares none


# ── Fallbacks ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("site", ["shared", "nosuchsite", None])
def test_a_site_without_config_gets_conservative_defaults(site):
    assert load_settings_safe(site) == RunSettings(
        use_visual_ai=False, slow_mo=0, browser="chromium", storage_state_path=None,
    )


def test_the_fallback_slow_mo_is_zero_not_three_hundred():
    """
    The old bare `except` returned slow_mo=300 while OpenLibrary's own default
    was 0, so an unreadable config silently changed a run's timing.
    """
    assert load_settings_safe("nosuchsite").slow_mo == 0


def test_a_broken_config_module_falls_back_and_says_so(monkeypatch, caplog):
    import bootstrap.settings as settings_module

    monkeypatch.setattr(settings_module, "site_config_module",
                        lambda site: "poms.does.not.exist")

    with caplog.at_level("WARNING"):
        result = settings_module.load_settings_safe("saucedemo")

    assert result.browser == "chromium"
    assert any("falling back" in r.getMessage() for r in caplog.records)


def test_a_site_missing_a_field_uses_the_fallback_for_it():
    """phpTravels declares no browser at all; that must not be an error."""
    assert load_settings_safe("phptravels").browser == "chromium"
    assert load_settings_safe("phptravels").use_visual_ai is False


# ── The shared loader ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "y", "on", " on "])
def test_parse_bool_truthy(value):
    assert parse_bool(value) is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe"])
def test_parse_bool_falsy(value):
    assert parse_bool(value) is False


def test_defaults_are_used_when_nothing_overrides_them():
    data = load_config_data({"a": 1, "b": "x"}, {})

    assert data == {"a": 1, "b": "x"}


def test_the_environment_beats_the_defaults(monkeypatch):
    monkeypatch.setenv("MY_A", "9")

    data = load_config_data({"a": 1}, {"MY_A": "a"}, int_fields={"a"})

    assert data["a"] == 9


def test_only_named_fields_are_coerced(monkeypatch):
    monkeypatch.setenv("MY_N", "5")
    monkeypatch.setenv("MY_S", "5")

    data = load_config_data({"n": 0, "s": ""}, {"MY_N": "n", "MY_S": "s"},
                            int_fields={"n"})

    assert data["n"] == 5 and data["s"] == "5"


def test_a_non_integer_in_an_int_field_names_the_variable(monkeypatch):
    monkeypatch.setenv("MY_N", "abc")

    with pytest.raises(ValueError, match="MY_N='abc' is not an integer"):
        load_config_data({"n": 0}, {"MY_N": "n"}, int_fields={"n"})


def test_a_yaml_file_beats_the_defaults_and_loses_to_the_environment(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("a: from_yaml\nb: from_yaml\n", encoding="utf-8")
    monkeypatch.setenv("MY_B", "from_env")

    data = load_config_data({"a": "default", "b": "default"}, {"MY_B": "b"},
                            config_path=config)

    assert data["a"] == "from_yaml"
    assert data["b"] == "from_env"


def test_a_missing_yaml_file_is_fine(tmp_path):
    data = load_config_data({"a": 1}, {}, config_path=tmp_path / "absent.yaml")

    assert data == {"a": 1}


def test_a_yaml_file_that_is_not_a_mapping_is_rejected(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("- just\n- a list\n", encoding="utf-8")

    with pytest.raises(ValueError, match="top-level mapping"):
        load_config_data({}, {}, config_path=config)


def test_relative_paths_resolve_against_the_given_base(tmp_path):
    assert resolve_path("artifacts/x.json", tmp_path) == tmp_path / "artifacts/x.json"


def test_absolute_paths_are_left_alone(tmp_path):
    absolute = tmp_path / "already" / "absolute.json"

    assert resolve_path(absolute, tmp_path / "elsewhere") == absolute
