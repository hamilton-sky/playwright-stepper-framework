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

So the fallbacks now drop a candidate the action cannot take, in two parts.

Whether the element is visible, enabled and (for a fill) editable is asked of
Playwright itself — locator.is_visible() / is_enabled() / is_editable() — so
the answer is exactly the one the action will meet: its label retargeting, its
role-gated and shadow-crossing aria-disabled, its presentation-role conflicts,
its zero-size boxes. Re-implementing those rules here was tried for fourteen
review rounds and each found another corner; delegating ends that.

What Playwright has no API for stays in one script below:

    fill    the control (a <label> retargets to it) is a native <input> of a
            type fill() can set — not checkbox, radio, file, hidden or a
            button type — a <textarea>, or contenteditable.
    select  the control is a native <select>.
    click   the element or an ancestor is something a click means: a button,
            link, form control, contenteditable editor, summary, a label with
            a control, any interactive ARIA role the accessibility fallback
            offers, or an element with an onclick handler or a pointer cursor.
            A text match inside a <button> is that button.
    hover   visible; anything can be hovered, a disabled tooltip trigger too.
    click_js
            a click with js_click: el.click() reaches a hidden element, so
            visibility is not asked, nor enabledness — aria-disabled is
            application state whose handler still runs.
    click_force
            a click with force: Playwright skips its enabled checks but still
            needs a box, so visibility is asked and enabledness is not.
            Neither forced mode accepts a native :disabled control: both
            clicks return normally on <button disabled> and fire nothing.

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

# is_enabled()/is_editable() wait for the element to attach; a candidate the
# fallback just found is attached, so this only bounds a detached one.
_STATE_TIMEOUT_MS = 2_000

# The shape rules Playwright has no API for. They run in the browser, where the
# DOM is, and return the verdict so the Python side holds no copy to drift.
_FIT_JS = """
(el, [action, widgetRoles]) => {
  // role is a space-separated fallback list; the first token the browser
  // recognises is the element's role — role="unknown button" is a button,
  // role="switch checkbox" a switch. Case-sensitive, as get_by_role reads it.
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
  const roleOf = n => (n.getAttribute('role') || '').split(/\\s+/)
    .find(t => ARIA.has(t)) || '';
  const forced = action === 'click_js' || action === 'click_force';
  // fill() and select_option() retarget anything that is not itself a control
  // through its nearest <label> — <label><span>Username</span><input></label>.
  if ((action === 'fill' || action === 'select')
      && !['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) && !el.isContentEditable) {
    const label = el.closest('label');
    if (label && label.control) el = label.control;
  }
  if (action === 'hover') return true;
  // Forced clicks skip Playwright's enabled check, but a native :disabled
  // control fires nothing under either — the step would report it acted.
  if (forced && el.closest('button:disabled, input:disabled, select:disabled, '
                           + 'textarea:disabled, option:disabled, optgroup:disabled')) {
    return false;
  }
  // A <label> — or text inside one — whose control is disabled activates
  // nothing: <fieldset disabled><label><span>Login</span><input></label>.
  // Unless something from the match up to the label has its own handler,
  // which still runs: <label for="off" onclick="openHelp()">.
  const label = el.closest('label');
  if ((action === 'click' || forced) && label && label.control
      && label.control.matches(':disabled')) {
    let handled = false;
    for (let n = el; n && !handled; n = n === label ? null : n.parentElement) {
      handled = n.matches('[onclick]') || typeof n.onclick === 'function';
    }
    if (!handled) return false;
  }
  const tag = el.tagName;
  if (action === 'select') return tag === 'SELECT';
  if (action === 'fill') {
    if (tag === 'TEXTAREA') return true;
    if (tag === 'INPUT') {
      // The types fill() itself refuses; color, range and the date family it sets.
      const notText = ['submit', 'button', 'reset', 'image', 'checkbox', 'radio',
                       'hidden', 'file'];
      return !notText.includes((el.getAttribute('type') || 'text').toLowerCase());
    }
    return el.isContentEditable;
  }
  if (action === 'click' || forced) {
    // widgetRoles is DescriptionFallbackResolver.INTERACTIVE_ROLES, passed in
    // so the roles the fallback offers and the roles a click accepts are one list.
    const clickable = 'button, a[href], input, select, textarea, summary, [onclick]';
    // Up through shadow roots too: <x-login onclick> hosting a shadow <span>Login.
    const up = n => n.parentElement
      || (n.getRootNode() instanceof ShadowRoot ? n.getRootNode().host : null);
    for (let n = el; n && n.nodeType === 1; n = up(n)) {
      if (n.matches(clickable) || widgetRoles.includes(roleOf(n))) return true;
      // A contenteditable editor is an implicit textbox; a click focuses it.
      if (n.isContentEditable) return true;
      // A label is clickable for the control it activates; an orphan one (for=
      // naming nothing) activates nothing and the click would report it acted.
      if (n.tagName === 'LABEL' && n.control) return true;
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
        # Playwright's own answers: the ones the action itself will meet.
        if action != "click_js" and not await locator.is_visible():
            return False
        if action in ("click", "fill", "select") and not await locator.is_enabled(
            timeout=_STATE_TIMEOUT_MS
        ):
            return False
        if action == "fill":
            try:
                if not await locator.is_editable(timeout=_STATE_TIMEOUT_MS):
                    return False
            except Exception:
                # Playwright raises for an element that is not an input,
                # textarea, select or contenteditable — fill() would too.
                return False
        return bool(await locator.evaluate(_FIT_JS, [action, _WIDGET_ROLES]))
    except Exception as exc:
        logger.debug(f"[action-fit] could not read the candidate ({exc}) — keeping it")
        return True
