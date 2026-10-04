"""
resolvers/action_fit.py — can a fuzzy match take the action at all?

The deterministic strategies resolve what the cfg names. The fuzzy fallbacks
(keyword-fuzzy, accessibility-semantic) resolve what the step's *description*
sounds like, and until this module they did so without knowing what was about
to happen to the element. "Type username into the username field" keyword-matched
a text node reading "username", and the fill then died on

    Element is not an <input>, <textarea>, <select> or [contenteditable]

A click was worse: keyword-matching "Click the Login button" against a heading
reading "Login" clicked the heading, and the step reported passed.

So the fallbacks now drop a candidate the action cannot take. The rules follow
what Playwright itself will accept — they reject the impossible, not the merely
unusual:

    fill    an editable text field: a native text-like <input> or <textarea>
            that is not readOnly, or a contenteditable element that is not
            aria-readonly (on a role that supports it, as Playwright reads it). Not hidden, not disabled. A <label> counts as the
            control it labels, as it does for Playwright.
    select  a native <select> (or its <label>), not hidden, not disabled —
            select_option() drives nothing else.
    click   not hidden, not disabled, and the element or an ancestor is
            something a click means: a button, link, form control, summary,
            label, an ARIA widget role, or an element with an onclick handler
            or a pointer cursor. A text match inside a <button> is that button.
    hover   not hidden. Anything can be hovered; a tooltip trigger can be
            disabled.

Any other action is not modelled and every candidate is kept.

An element the check cannot read (detached, a cross-frame handle) is kept: the
filter narrows a guess, it does not get to veto one on missing evidence.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MODELLED_ACTIONS = frozenset({"fill", "select", "click", "hover"})

# One evaluate per candidate. The rule is in the browser, where the DOM is, and
# returns the verdict so the Python side holds no copy of it to drift.
_FIT_JS = """
(el, action) => {
  if (typeof el.checkVisibility === 'function'
        ? !el.checkVisibility({visibilityProperty: true})
        : !(el.offsetWidth || el.offsetHeight || el.getClientRects().length)) {
    return false;
  }
  if (action === 'hover') return true;
  // fill() and select_option() retarget a <label> to the control it labels.
  if ((action === 'fill' || action === 'select') && el.tagName === 'LABEL' && el.control) {
    el = el.control;
  }
  const disabled = el.matches(':disabled') || el.closest('[aria-disabled="true"]') !== null;
  if (disabled) return false;
  const tag = el.tagName;
  if (action === 'select') return tag === 'SELECT';
  if (action === 'fill') {
    if (tag === 'TEXTAREA') return !el.readOnly;
    if (tag === 'INPUT') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      const notText = ['submit', 'button', 'reset', 'image', 'checkbox', 'radio',
                       'hidden', 'file', 'range', 'color'];
      return !notText.includes(type) && !el.readOnly;
    }
    // Playwright honours aria-readonly only on a role that supports it.
    const roRoles = ['textbox', 'searchbox', 'combobox', 'spinbutton', 'slider',
                     'gridcell', 'grid', 'listbox', 'radiogroup', 'checkbox',
                     'switch', 'menuitemcheckbox', 'menuitemradio', 'columnheader',
                     'rowheader', 'treegrid'];
    const ro = el.getAttribute('aria-readonly') === 'true'
               && roRoles.includes((el.getAttribute('role') || '').toLowerCase());
    return el.isContentEditable && !ro;
  }
  if (action === 'click') {
    const clickable = 'button, a[href], input, select, textarea, summary, label, '
      + '[onclick], [role="button"], [role="link"], [role="menuitem"], '
      + '[role="menuitemcheckbox"], [role="menuitemradio"], [role="tab"], '
      + '[role="checkbox"], [role="radio"], [role="switch"], [role="option"], '
      + '[role="treeitem"], [role="combobox"]';
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      if (n.matches(clickable)) return true;
      if (getComputedStyle(n).cursor === 'pointer') return true;
    }
    return false;
  }
  return true;
}
"""


async def fits(locator, action: str | None) -> bool:
    """Whether `locator`'s element can take `action`. True for unmodelled actions."""
    if action not in MODELLED_ACTIONS:
        return True
    try:
        return bool(await locator.evaluate(_FIT_JS, action))
    except Exception as exc:
        logger.debug(f"[action-fit] could not read the candidate ({exc}) — keeping it")
        return True


async def keep_fitting(candidates: list, action: str | None, *, source: str,
                       locator_of=lambda c: c) -> list:
    """
    The candidates that can take `action`, in their original order.

    `locator_of` pulls the locator out of a candidate that is not one itself —
    the accessibility shortlist holds (locator, desc, score) tuples.
    """
    if action not in MODELLED_ACTIONS or not candidates:
        return candidates
    kept = [c for c in candidates if await fits(locator_of(c), action)]
    dropped = len(candidates) - len(kept)
    if dropped:
        logger.info(
            f"[{source}] dropped {dropped} of {len(candidates)} candidate(s) "
            f"that cannot take a {action}"
        )
    return kept
