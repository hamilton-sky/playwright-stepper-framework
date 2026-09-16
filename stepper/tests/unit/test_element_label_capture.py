"""
What the healer can see of an element, and therefore what it can heal.

DOMSnapshotCascade scores elements by embedding a text description of each one.
An element whose description omits its visible label is invisible to that
scoring no matter how obvious it looks on screen — it never reaches the
shortlist, so the cheap rung cannot heal it and the run falls through to the
expensive one or fails outright.

That is not hypothetical. SauceDemo's login button is:

    <input type="submit" value="Login">

An <input> has no textContent, and `value` was captured only for <option>. The
healer's description of that button was "input login-button submit" — nothing
resembling "Login" — so a step described "Click the Login button to submit
credentials" could not match it. The two text inputs on the same page healed
fine, because a placeholder *was* captured. Two of three, and the missing third
was the one that mattered.
"""
from __future__ import annotations

import pytest

from stepper.engine.healer.dom_snapshot import _ELEMENT_QUERY_JS, DOMSnapshotCascade


def _el(**kw) -> dict:
    base = {
        "tag": "INPUT", "text": "", "role": "input", "aria": None, "id": "",
        "placeholder": None, "name": None, "type": None, "title": None, "value": None,
    }
    base.update(kw)
    return base


# ── The label reaches the description ─────────────────────────────────────────

def test_a_submit_button_s_label_is_in_its_description():
    """The regression. Without `value`, this button reads as 'input submit'."""
    description = DOMSnapshotCascade._describe_element(
        _el(id="login-button", name="login-button", type="submit", value="Login")
    )

    assert "Login" in description


def test_an_option_s_label_still_reaches_the_description():
    """`value` was already captured for <option>; that must keep working."""
    description = DOMSnapshotCascade._describe_element(
        _el(tag="OPTION", role="option", value="Price (low to high)")
    )

    assert "Price (low to high)" in description


def test_an_element_with_no_value_is_described_as_before():
    description = DOMSnapshotCascade._describe_element(
        _el(role="textbox", placeholder="Username", name="user-name", type="text")
    )

    assert "Username" in description
    assert description == description.strip(), "no dangling separator from the empty value"


def test_a_healed_cfg_is_still_produced_for_the_button():
    """
    Seeing the element is only half of it — the cfg has to resolve. An id is
    enough here and is what this element offers.
    """
    cfg = DOMSnapshotCascade._element_to_cfg(
        _el(id="login-button", name="login-button", type="submit", value="Login")
    )

    assert cfg.get("id") == "login-button"


# ── Which values are captured, and which are deliberately not ─────────────────

def test_the_query_captures_value_for_button_shaped_inputs():
    for kind in ("submit", "button", "reset"):
        assert f"'{kind}'" in _ELEMENT_QUERY_JS, f"{kind} inputs should expose their label"


def test_the_query_does_not_capture_value_for_text_or_password_inputs():
    """
    The important limit. `value` on a text or password input is whatever the
    user typed, and this description is embedded and can be sent to an AI
    provider. Capturing it wholesale would put a typed password into a prompt.

    So the capture is restricted by input type, and it is the restriction —
    not the capture — that this test exists to keep.
    """
    assert "'submit', 'button', 'reset'" in _ELEMENT_QUERY_JS, (
        "the value capture is no longer restricted to button-shaped inputs; "
        "a text or password input's value would now be embedded"
    )
    for unsafe in ("'password'", "'text'", "'email'"):
        assert unsafe not in _ELEMENT_QUERY_JS, f"{unsafe} inputs must not expose their value"


# ── The description as a whole ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "element, expected",
    [
        (_el(aria="Close dialog"), "Close dialog"),
        (_el(placeholder="Search products"), "Search products"),
        (_el(tag="BUTTON", role="button", text="Add to cart"), "Add to cart"),
        (_el(title="Remove this item"), "Remove this item"),
        (_el(type="submit", value="Continue"), "Continue"),
    ],
)
def test_every_human_readable_attribute_reaches_the_description(element, expected):
    """
    Each of these is the only visible label on some real element. Dropping any
    one of them makes that whole class of element unhealable.
    """
    assert expected in DOMSnapshotCascade._describe_element(element)


def test_an_element_with_nothing_readable_describes_as_empty():
    """
    _score_elements skips elements with no description rather than scoring noise
    against them.
    """
    assert DOMSnapshotCascade._describe_element(_el(role="")) == ""
