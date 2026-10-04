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

    fill    a field fill() accepts: a native <input> of a type it can set
            (not checkbox, radio, file, hidden or a button type) or a
            <textarea>, not readOnly; or a contenteditable element not
            aria-readonly (on a role that supports it, as Playwright reads it).
    select  a native <select>.
    click   the element or an ancestor is something a click means: a button,
            link, form control, summary, label, any interactive ARIA role the
            accessibility fallback offers, or an element with an onclick
            handler or a pointer cursor. A text match
            inside a <button> is that button.

    fill, select and click also need the element visible and not disabled —
    by a disabled control anywhere above it, or aria-disabled. For fill and
    select, anything inside a <label> is first retargeted to the control that
    label names, as Playwright does, and that control is what is checked.
    hover   not hidden. Anything can be hovered; a tooltip trigger can be
            disabled.
    click_js
            a click with js_click: el.click() reaches anything, a hidden
            dropdown button included, so visibility and disabled state are
            not read — but the element must still be something a click means.
    click_force
            a click with force: Playwright skips its enabled/stable checks but
            still needs a box to click, so visibility is read and disabled
            state is not — and the element must be something a click means.

Any other action is not modelled and every candidate is kept.

One known limit, kept on purpose: a click handler added with addEventListener
cannot be seen from the page — and with React-style delegation it lives on
the root, so not even the DevTools protocol could pin it to the element. A
<div> with such a handler, no role, no onclick and the default cursor is
therefore indistinguishable from a heading, and is refused. That turns a
possible wrong click that reports passed into a visible not-found, which the
healer and the AI pick still get to try; a cfg that names the element directly
is never filtered at all.

An element the check cannot read (detached, a cross-frame handle) is kept: the
filter narrows a guess, it does not get to veto one on missing evidence.
"""
from __future__ import annotations

import logging

from stepper.engine.resolvers.strategies import DescriptionFallbackResolver

logger = logging.getLogger(__name__)

MODELLED_ACTIONS = frozenset({"fill", "select", "click", "click_js", "click_force", "hover"})

# Every role the accessibility fallback offers as a candidate is one a click may
# land on — a custom slider or listbox with an addEventListener handler and the
# default cursor is still the widget the step named.
_WIDGET_ROLES = sorted(DescriptionFallbackResolver.INTERACTIVE_ROLES)

# One evaluate per candidate. The rule is in the browser, where the DOM is, and
# returns the verdict so the Python side holds no copy of it to drift.
_FIT_JS = """
(el, [action, widgetRoles]) => {
  // Playwright's own order: visibility is read on the element it was handed,
  // then fill() and select_option() retarget anything that is not itself a
  // control through its nearest <label> — a <span> inside
  // <label><span>Username</span><input></label> fills the input — and the
  // enabled and editable checks read that control. (Checked in a real browser:
  // a visible label for a hidden input fills; a hidden label never does.)
  // A js_click (el.click()) reaches anything, a hidden dropdown button included;
  // a force click skips Playwright's enabled checks but still needs a box to
  // click. Both must still land on something a click means, or a heading
  // reading "Login" would be force-clicked and pass.
  const forced = action === 'click_js' || action === 'click_force';
  if (action !== 'click_js' && (typeof el.checkVisibility === 'function'
        ? !el.checkVisibility({visibilityProperty: true})
        : !(el.offsetWidth || el.offsetHeight || el.getClientRects().length))) {
    return false;
  }
  if ((action === 'fill' || action === 'select')
      && !['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) && !el.isContentEditable) {
    const label = el.closest('label');
    if (label && label.control) el = label.control;
  }
  if (action === 'hover') return true;
  // A disabled control anywhere above the match disables it too: a text match
  // inside <button disabled> is that button, and the browser swallows the click.
  // (Not fieldset: its descendant controls match :disabled themselves, and a
  // link inside one stays live.)
  const disabled = el.closest(
    'button:disabled, input:disabled, select:disabled, textarea:disabled, '
    + 'option:disabled, optgroup:disabled, [aria-disabled="true"]') !== null;
  if (disabled && !forced) return false;
  // A <label> — or text inside one — whose control is disabled activates
  // nothing: <fieldset disabled><label><span>Login</span><input></label>. The
  // click lands, and the step would report it did something.
  const label = el.closest('label');
  if ((action === 'click' || forced) && label && label.control && label.control.matches(':disabled')) {
    return false;
  }
  const tag = el.tagName;
  if (action === 'select') return tag === 'SELECT';
  if (action === 'fill') {
    if (tag === 'TEXTAREA') return !el.readOnly;
    if (tag === 'INPUT') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      // The types fill() itself refuses; color, range and the date family it sets.
      const notText = ['submit', 'button', 'reset', 'image', 'checkbox', 'radio',
                       'hidden', 'file'];
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
  if (action === 'click' || forced) {
    // widgetRoles is DescriptionFallbackResolver.INTERACTIVE_ROLES, passed in
    // so the roles the fallback offers and the roles a click accepts are one list.
    const clickable = ['button', 'a[href]', 'input', 'select', 'textarea', 'summary',
                       'label', '[onclick]']
      .concat(widgetRoles.map(r => `[role="${r}"]`)).join(', ');
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      if (n.matches(clickable)) return true;
      // el.onclick = handler sets the property, not the attribute [onclick].
      if (typeof n.onclick === 'function') return true;
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
        return bool(await locator.evaluate(_FIT_JS, [action, _WIDGET_ROLES]))
    except Exception as exc:
        logger.debug(f"[action-fit] could not read the candidate ({exc}) — keeping it")
        return True
