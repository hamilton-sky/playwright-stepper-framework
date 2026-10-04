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
            a click with js_click: el.click() reaches a hidden element, a
            hidden dropdown button included, so visibility is not read.
    click_force
            a click with force: Playwright skips its enabled/stable checks but
            still needs a box to click, so visibility is read.
            Both forced modes ignore aria-disabled, whose handler still runs,
            but never accept a native :disabled control — the click returns
            normally and fires nothing. Both need something a click means.

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
  // role is a space-separated fallback list; the first token the browser
  // recognises is the element's role — role="unknown button" is a button,
  // role="switch checkbox" a switch. Read it the same way everywhere below.
  const ARIA = new Set(['alert', 'alertdialog', 'application', 'article', 'banner',
    'blockquote', 'button', 'caption', 'cell', 'checkbox', 'code', 'columnheader',
    'combobox', 'complementary', 'contentinfo', 'definition', 'deletion', 'dialog',
    'directory', 'document', 'emphasis', 'feed', 'figure', 'form', 'generic', 'grid',
    'gridcell', 'group', 'heading', 'img', 'insertion', 'link', 'list', 'listbox',
    'listitem', 'log', 'main', 'mark', 'marquee', 'math', 'menu', 'menubar',
    'menuitem', 'menuitemcheckbox', 'menuitemradio', 'meter', 'navigation', 'none',
    'note', 'option', 'paragraph', 'presentation', 'progressbar', 'radio',
    'radiogroup', 'region', 'row', 'rowgroup', 'rowheader', 'scrollbar', 'search',
    'searchbox', 'separator', 'slider', 'spinbutton', 'status', 'strong',
    'subscript', 'superscript', 'switch', 'tab', 'table', 'tablist', 'tabpanel',
    'term', 'textbox', 'time', 'timer', 'toolbar', 'tooltip', 'tree', 'treegrid',
    'treeitem']);
  // Case-sensitive, as Playwright's get_by_role reads it: role="BUTTON" is none.
  const roleOf = n => (n.getAttribute('role') || '').split(/\s+/)
    .find(t => ARIA.has(t)) || '';
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
  // Playwright's "visible" is a non-empty bounding box and not
  // visibility:hidden; checkVisibility() alone passes a zero-size box.
  const box = el.getBoundingClientRect();
  if (action !== 'click_js' && (!box.width || !box.height
        || (typeof el.checkVisibility === 'function'
            && !el.checkVisibility({visibilityProperty: true})))) {
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
  //
  // Native :disabled refuses every click, forced ones included: el.click() and
  // a forced pointer click both return normally on <button disabled> and fire
  // nothing (checked in a real browser), so the step would report it acted.
  // aria-disabled is application state the page's own handler still receives,
  // so only an ordinary click — which Playwright refuses — is turned away.
  const nativeDisabled = el.closest(
    'button:disabled, input:disabled, select:disabled, textarea:disabled, '
    + 'option:disabled, optgroup:disabled') !== null;
  if (nativeDisabled) return false;
  if (!forced && el.closest('[aria-disabled="true"]') !== null) return false;
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
               && roRoles.includes(roleOf(el));
    return el.isContentEditable && !ro;
  }
  if (action === 'click' || forced) {
    // widgetRoles is DescriptionFallbackResolver.INTERACTIVE_ROLES, passed in
    // so the roles the fallback offers and the roles a click accepts are one list.
    const clickable = 'button, a[href], input, select, textarea, summary, label, [onclick]';
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      if (n.matches(clickable) || widgetRoles.includes(roleOf(n))) return true;
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
