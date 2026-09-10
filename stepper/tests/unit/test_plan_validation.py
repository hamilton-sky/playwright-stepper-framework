import pytest

from engine.actions.factory import build_default_registry
from engine.interfaces import StepConfig
from engine.planner.validator import PlanValidator, PlanValidationError
from engine.utils import dict_to_step_config


@pytest.mark.parametrize("action,extra", [
    ("load_test_data", {}), ("extract_data", {}), ("store", {}),
    ("fill", {"press_enter": "false"}), ("extract_data", {"selector": "a", "limit": True}),
    ("parallel", {"steps": "invalid"}), ("paginate", {"extract_config": {"selector": "a"}}),
])
def test_invalid_action_parameters_are_rejected(action, extra):
    with pytest.raises(PlanValidationError):
        PlanValidator.validate([StepConfig(action=action, description="test", extra=extra)], build_default_registry())


def test_nested_unknown_action_has_location():
    step = StepConfig(action="for_each_item", description="loop", extra={"steps": [
        {"action": "missing_action", "description": "nested"}
    ]})
    with pytest.raises(PlanValidationError, match=r"1.extra.steps\[1\]"):
        PlanValidator.validate([step], build_default_registry())


def test_parallel_rejects_write_before_browser_launch():
    step = StepConfig(action="parallel", description="parallel", extra={"steps": [
        {"action": "click", "description": "write"}
    ]})
    with pytest.raises(PlanValidationError, match="read_only"):
        PlanValidator.validate([step], build_default_registry())


@pytest.mark.parametrize("raw", [{"heal": "false"}, {"retry": -1}, {"retry": True}, {"extra": []}, {"element": "#x"}])
def test_raw_types_cannot_be_silently_coerced(raw):
    with pytest.raises(ValueError):
        dict_to_step_config({"action": "click", **raw})


def test_runtime_numeric_template_is_accepted():
    PlanValidator.validate([StepConfig(action="extract_data", description="extract", extra={
        "selector": "a", "limit": "{{limit}}"
    })], build_default_registry())


@pytest.mark.parametrize("field,value", [("when", {"typo": True}), ("heal_assert", {"typo": True}),
    ("when", {"all": [{"context_greater_than": {"key": "n", "value": "bad"}}]})])
def test_invalid_guards_are_rejected(field, value):
    with pytest.raises(PlanValidationError):
        PlanValidator.validate([StepConfig(action="click", description="test", **{field: value})], build_default_registry())


def test_navigate_preserves_input_value_alias():
    PlanValidator.validate([StepConfig(action="navigate", description="open", input_value="https://example.test")],
                           build_default_registry())
