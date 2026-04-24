from engine.resolvers.element_resolver import CONFIDENCE_MAP

_DETERMINISTIC = ["role", "label", "placeholder", "text", "id", "css", "xpath"]
_SCORE_BASED   = ["semantic", "visual-ai"]


def test_all_deterministic_keys_present():
    for key in _DETERMINISTIC:
        assert key in CONFIDENCE_MAP, f"Missing key: {key}"


def test_numeric_values_in_range():
    for key, val in CONFIDENCE_MAP.items():
        if val is not None:
            assert 0.0 <= val <= 1.0, f"{key}={val} out of [0,1]"


def test_none_values_for_score_based_strategies():
    for key in _SCORE_BASED:
        assert CONFIDENCE_MAP.get(key) is None, f"{key} should be None"


def test_priority_order():
    # Higher-priority (lower number) = tried first = higher confidence
    assert CONFIDENCE_MAP["role"] > CONFIDENCE_MAP["label"]
    assert CONFIDENCE_MAP["label"] > CONFIDENCE_MAP["placeholder"]
    assert CONFIDENCE_MAP["placeholder"] > CONFIDENCE_MAP["text"]
    assert CONFIDENCE_MAP["text"] > CONFIDENCE_MAP["id"]
    assert CONFIDENCE_MAP["id"] > CONFIDENCE_MAP["css"]
    assert CONFIDENCE_MAP["css"] > CONFIDENCE_MAP["xpath"]
