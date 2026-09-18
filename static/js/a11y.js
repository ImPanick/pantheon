// SPDX-License-Identifier: AGPL-3.0-or-later
// Accessibility enhancements for keyboard + screen-reader users.
//
// Several primary controls in Pantheon are authored as click-only <div>s
// (most notably the whole sidebar navigation: New Chat, Search, Brain,
// Calendar, Compare, Forge, Deep Research, Gallery, Library, Notes,
// Tasks, Theme, plus the account row). <div>s are not in the tab order and
// are not announced as buttons, so keyboard and screen-reader users cannot
// reach or operate them.
//
// This module enhances those rows in place — making them focusable
// (tabindex=0), announcing them as buttons when it's safe to do so, and
// activating them with Enter / Space — without changing how they look or
// how they behave for mouse users. The visible focus ring already exists in
// style.css (`.list-item:focus-visible`); it simply never fired because the
// rows were never focusable.

(function () {
  'use strict';

  // Click-as-button rows we want reachable by keyboard.
  var ROW_SELECTOR = ['#sidebar .list-item', '#user-bar-profile'].join(',');

  // Native interactive descendants. If a row contains one of these we must
  // NOT give the row role="button" — a button inside a button is invalid
  // (axe "nested-interactive") and confuses screen readers. Such rows still
  // become focusable + Enter/Space-activatable, just without the role.
  var NESTED_INTERACTIVE =
    'a[href],button,input,select,textarea,[contenteditable="true"],[tabindex]:not([tabindex="-1"])';

  function enhanceRow(el) {
    if (!el || el.nodeType !== 1 || el.dataset.a11yEnhanced === '1') return;
    var tag = el.tagName;
    // Leave genuine native controls alone.
    if (tag === 'BUTTON' || tag === 'A' || tag === 'INPUT' ||
        tag === 'SELECT' || tag === 'TEXTAREA') return;

    el.dataset.a11yEnhanced = '1';
    if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
    el.setAttribute('data-a11y-activatable', '1');

    if (!el.querySelector(NESTED_INTERACTIVE) && !el.hasAttribute('role')) {
      el.setAttribute('role', 'button');
    }

    // Guarantee an accessible name. Visible text normally supplies it; fall
    // back to the title attribute for icon-only rows.
    if (!el.getAttribute('aria-label') &&
        !(el.textContent || '').trim() &&
        el.getAttribute('title')) {
      el.setAttribute('aria-label', el.getAttribute('title'));
    }
  }

  function enhanceAll(root) {
    (root || document).querySelectorAll(ROW_SELECTOR).forEach(enhanceRow);
  }

  // ---- The icon rail, as a toolbar ---------------------------------------
  // `P10-06`. Every button in the rail is a real `<button>`, so every one of
  // them is already in the tab order — which is the problem. Eighteen launchers
  // sit between the page's first control and the sidebar, so a keyboard user
  // pays eighteen Tab presses to get past a strip a mouse user skips by not
  // looking at it. That is the failure `role="toolbar"` and a roving tabindex
  // exist for: the rail becomes ONE tab stop, and the arrow keys move inside
  // it.
  //
  // Vertical, so Up/Down and Home/End — the axis `aria-orientation` declares.
  // Left/Right are deliberately not bound: the rail can be moved to the right
  // side of the window (`.right-side`), and a horizontal binding would then
  // read backwards, which is the bug `P10-03` had to answer for the resize
  // separators. An axis that is always true is better than one that is true
  // half the time.
  //
  // Visibility is read off the inline `display`, because that is how this
  // product hides these buttons: `applyUIVis()` in `app.js` writes
  // `el.style.display = 'none'` for every Customize-UI key, and the two
  // `.rail-dynamic` launchers ship that way in the markup. A hidden button is
  // not focusable, so the ring must not be able to land on one.
  var RAIL_ID = 'icon-rail';
  var RAIL_ITEM = '.icon-rail-btn';
  var RAIL_KEYS = ['ArrowDown', 'ArrowUp', 'Home', 'End'];

  /** `Element.closest`, written out — see the note in `init()`. */
  function up(el, sel) {
    for (var n = el; n; n = n.parentNode) {
      if (n.matches && n.matches(sel)) return n;
    }
    return null;
  }

  function railVisible(btn) {
    return !btn.disabled
      && (btn.style ? btn.style.display !== 'none' : true)
      && btn.getAttribute('hidden') == null;
  }

  function railItems(rail) {
    return Array.prototype.filter.call(rail.querySelectorAll(RAIL_ITEM), railVisible);
  }

  /**
   * Leave exactly one tab stop in the rail.
   *
   * Every button is written, not just the visible ones: a hidden button that
   * kept `tabindex="0"` becomes a second tab stop the moment Customize UI
   * turns it back on, and two tab stops in a toolbar is the defect this
   * function exists to prevent, arriving later and from a settings panel.
   */
  function setRailTabStop(rail, preferred) {
    var all = rail.querySelectorAll(RAIL_ITEM);
    var visible = railItems(rail);
    var stop = null;
    if (preferred && visible.indexOf(preferred) >= 0) stop = preferred;
    if (!stop) {
      for (var i = 0; i < visible.length; i++) {
        if (visible[i].className && visible[i].className.split(/\s+/).indexOf('active') >= 0) {
          stop = visible[i];
          break;
        }
      }
    }
    if (!stop) stop = visible[0] || null;
    Array.prototype.forEach.call(all, function (b) {
      b.setAttribute('tabindex', b === stop ? '0' : '-1');
    });
    return stop;
  }

  function enhanceRail(rail) {
    if (!rail || rail.dataset.a11yToolbar === '1') return;
    rail.dataset.a11yToolbar = '1';
    if (rail.getAttribute('role') == null) rail.setAttribute('role', 'toolbar');
    if (rail.getAttribute('aria-orientation') == null) {
      rail.setAttribute('aria-orientation', 'vertical');
    }
    if (rail.getAttribute('aria-label') == null) {
      rail.setAttribute('aria-label', 'Tools');
    }
    setRailTabStop(rail, null);
  }

  /** Move the rail's focus. Returns the button focused, or null. */
  function moveRailFocus(rail, from, key) {
    var items = railItems(rail);
    var i = items.indexOf(from);
    if (i < 0 || !items.length) return null;
    var next;
    if (key === 'ArrowDown') next = items[(i + 1) % items.length];
    else if (key === 'ArrowUp') next = items[(i - 1 + items.length) % items.length];
    else if (key === 'Home') next = items[0];
    else if (key === 'End') next = items[items.length - 1];
    else return null;
    setRailTabStop(rail, next);
    next.focus();
    return next;
  }

  // ---- Modal dialogs -----------------------------------------------------
  // Pantheon modals are plain <div class="modal-content"> boxes. Marking
  // them as ARIA dialogs lets screen readers announce them as dialogs and
  // exempts their content from the "all content in landmarks" rule. We also
  // normalize the modal title to heading level 2 (one below the page <h1>)
  // so heading order stays valid no matter which tag the markup uses.
  var titleSeq = 0;
  // Each modal "kind" is a container selector plus where to find its title
  // heading. Standard modals use .modal-content/.modal-header; the docked
  // Notes pane uses its own markup.
  var MODAL_KINDS = [
    {
      sel: '.modal-content',
      heading: '.modal-header h1, .modal-header h2, .modal-header h3, ' +
               '.modal-header h4, .modal-header h5, .modal-header h6'
    },
    { sel: '.notes-pane', heading: '.notes-pane-title' }
  ];
  var MODAL_SEL = MODAL_KINDS.map(function (k) { return k.sel; }).join(',');

  function enhanceModal(mc, headingSel) {
    if (!mc || mc.nodeType !== 1 || mc.dataset.a11yDialog === '1') return;
    mc.dataset.a11yDialog = '1';
    if (!mc.hasAttribute('role')) mc.setAttribute('role', 'dialog');
    if (!mc.hasAttribute('aria-modal')) mc.setAttribute('aria-modal', 'true');

    var heading = headingSel && mc.querySelector(headingSel);
    if (heading) {
      if (!heading.id) heading.id = 'a11y-modal-title-' + (++titleSeq);
      if (!mc.hasAttribute('aria-labelledby')) {
        mc.setAttribute('aria-labelledby', heading.id);
      }
      // Modal titles sit one level below the page <h1>; normalize so heading
      // order stays valid regardless of the tag the markup happens to use.
      if (!heading.hasAttribute('aria-level')) heading.setAttribute('aria-level', '2');
    }
  }

  function enhanceModals(root) {
    var scope = root || document;
    MODAL_KINDS.forEach(function (k) {
      scope.querySelectorAll(k.sel).forEach(function (mc) { enhanceModal(mc, k.heading); });
    });
  }

  function headingSelFor(el) {
    for (var i = 0; i < MODAL_KINDS.length; i++) {
      if (el.matches(MODAL_KINDS[i].sel)) return MODAL_KINDS[i].heading;
    }
    return null;
  }

  // Delegated keyboard activation. We only act when the focused element is
  // itself an enhanced row (keydown targets the focused element), so a press
  // on a nested native button is left to the browser's own handling.
  document.addEventListener('keydown', function (e) {
    var el = e.target;
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
      if (!el || !el.matches || !el.matches('[data-a11y-activatable]')) return;
      e.preventDefault(); // Space would otherwise scroll the page
      el.click();
      return;
    }
    // `P10-06`. The rail's arrows ride the SAME delegated listener rather than
    // one of their own. Two keydown listeners on `document` is two places to
    // discover that a key is already taken, and this module exists because the
    // first one was not enough on its own.
    if (RAIL_KEYS.indexOf(e.key) < 0) return;
    if (!el) return;
    var btn = up(el, RAIL_ITEM);
    if (!btn) return;
    var rail = up(btn, '#' + RAIL_ID);
    if (!rail) return;
    if (moveRailFocus(rail, btn, e.key)) e.preventDefault();
  });

  // Focus entering the rail from outside (a Tab press, or a script) decides
  // where the single tab stop sits next, so Shift+Tab back into the rail
  // returns to the button the user left rather than to the top of the strip.
  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (!el) return;
    var btn = up(el, RAIL_ITEM);
    if (!btn) return;
    var rail = up(btn, '#' + RAIL_ID);
    if (rail) setRailTabStop(rail, btn);
  });

  function init() {
    enhanceAll(document);
    enhanceModals(document);
    enhanceRail(document.getElementById(RAIL_ID));

    // Sidebar content is re-rendered as the user navigates (session lists,
    // tool sub-rows, etc.). Watch for new rows and enhance them too.
    var sidebar = document.getElementById('sidebar');
    if (sidebar && 'MutationObserver' in window) {
      new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var added = muts[i].addedNodes;
          for (var j = 0; j < added.length; j++) {
            var n = added[j];
            if (n.nodeType !== 1) continue;
            if (n.matches && n.matches(ROW_SELECTOR)) enhanceRow(n);
            if (n.querySelectorAll) enhanceAll(n);
          }
        }
      }).observe(sidebar, { childList: true, subtree: true });
    }

    // Customize UI hides rail launchers by writing `style.display`, and the
    // one holding the tab stop can be among them — which would leave the rail
    // with no way in at all. Watching `style` on the rail's own subtree is 18
    // elements and one attribute, and it re-picks the stop the moment one
    // disappears. `setRailTabStop` writes `tabindex`, never `style`, so this
    // cannot observe its own work.
    var _rail = document.getElementById(RAIL_ID);
    if (_rail && 'MutationObserver' in window) {
      new MutationObserver(function () {
        setRailTabStop(_rail, null);
      }).observe(_rail, { attributes: true, subtree: true, attributeFilter: ['style'] });
    }

    // Some modals (Notes, Tasks, …) are injected at runtime, usually as
    // direct children of <body>. Catch those without paying for a deep
    // subtree observer over the whole document.
    if ('MutationObserver' in window) {
      new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var added = muts[i].addedNodes;
          for (var j = 0; j < added.length; j++) {
            var n = added[j];
            if (n.nodeType !== 1) continue;
            if (n.matches && n.matches(MODAL_SEL)) enhanceModal(n, headingSelFor(n));
            if (n.querySelector && n.querySelector(MODAL_SEL)) enhanceModals(n);
          }
        }
      }).observe(document.body, { childList: true });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
