from engine.resolvers.shadow_runner import _make_key


def test_determinism():
    assert _make_key({"css": ".btn"}, "click submit") == _make_key({"css": ".btn"}, "click submit")


def test_different_cfg_different_key():
    assert _make_key({"css": ".btn-a"}, "x") != _make_key({"css": ".btn-b"}, "x")


def test_different_description_different_key():
    assert _make_key({"css": ".btn"}, "click A") != _make_key({"css": ".btn"}, "click B")


def test_key_length_16():
    assert len(_make_key({}, "")) == 16


def test_empty_inputs_no_crash():
    result = _make_key({}, "")
    assert isinstance(result, str)


def test_dict_key_order_invariant():
    assert _make_key({"a": 1, "b": 2}, "x") == _make_key({"b": 2, "a": 1}, "x")
