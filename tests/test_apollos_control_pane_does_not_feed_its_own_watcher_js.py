# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's control pane doesn't wake its own watcher, so the page can't hang.

The owner's test on the dev build (2026-11-25): pressing New chat in Apollo,
to start over from a chat left by an earlier update, "completely locked up the
entire Pantheon system". The machine was fine; Pantheon's page was dead.

The control pane (`apolloDeck.js`) watches the class of the page and of the
sidebar, and on any change puts itself back in place, writing `apollo-docked`
on the page. The DOM writes the class attribute on every `classList.add` and
`classList.remove`, even when nothing changes, and every write is a record the
watcher sees. So placing the pane woke the watcher, which placed the pane,
which woke the watcher, without end: a loop of microtasks the tab never left.

It needed one class write from anywhere else to start, and New chat makes one:
the new chat is Apollo's, so Apollo's page is entered again and writes
`apollo-view` on the page a second time. Opening Apollo the first time didn't,
because that write comes before the watcher exists.

The shim below writes classes the way a browser does (a record on each
`add` and `remove`, none from a `toggle` that asks for what is already there)
and delivers records as microtasks, as a browser does. It stops delivering
after a cap, so a loop shows as `looped` instead of hanging the test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_apollos_control_pane_takes_the_sidebars_place_js import (  # noqa: E402
    DECK, _PREAMBLE, _SHIM, _STUBS, node,
)

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "static" / "js" / "apolloView.js"

_WATCHERS = r"""
export const mo = { delivered: 0, cap: 200, looped: false };
const _all = [];
globalThis.MutationObserver = class {
  constructor(cb) { this.cb = cb; this.q = []; this.on = []; _all.push(this); }
  observe(target, opts) { this.on.push({ target, only: (opts && opts.attributeFilter) || null }); }
  disconnect() { this.on = []; this.q = []; }
  takeRecords() { const q = this.q; this.q = []; return q; }
  _note(target, name) {
    if (!this.on.some((w) => w.target === target && (!w.only || w.only.includes(name)))) return;
    const first = this.q.length === 0;
    this.q.push({ type: 'attributes', target, attributeName: name });
    if (!first) return;
    queueMicrotask(() => {
      const q = this.takeRecords();
      if (!q.length) return;
      mo.delivered += 1;
      if (mo.delivered > mo.cap) { mo.looped = true; return; }
      this.cb(q, this);
    });
  }
};
/** Make `node`'s classList write the way the DOM's does: `add` and `remove`
 *  always rewrite the attribute (a record each), `toggle` with a force that is
 *  already met changes nothing. */
export function browserClasses(node) {
  const base = node.classList;
  const wrote = () => _all.forEach((o) => o._note(node, 'class'));
  node.classList = {
    add(...cs) { base.add(...cs); wrote(); },
    remove(...cs) { base.remove(...cs); wrote(); },
    contains(c) { return base.contains(c); },
    toggle(c, force) {
      const has = base.contains(c);
      if (force !== undefined && !!force === has) return has;
      if (has) this.remove(c); else this.add(c);
      return !has;
    },
  };
  return node;
}
"""

_PRE = (
    "import { document, log, media, settle, page, mo, browserClasses } from './shim.js';\n"
    "const D = await import('./apolloDeck.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "function apolloPage() { const P = page(); browserClasses(document.documentElement);"
    " browserClasses(P.sb); return P; }\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apollowatch"), DECK, _SHIM + _WATCHERS, _STUBS)


@node
def test_a_class_written_again_on_the_page_settles_instead_of_looping(box):
    """New chat's write: `apollo-view` on the page again, while the pane is docked."""
    o = _run(box, _PRE, """
        const P = apolloPage();
        document.documentElement.classList.add('apollo-view');
        D.mountDeck();
        await settle();
        mo.delivered = 0;
        document.documentElement.classList.add('apollo-view');
        await settle();
        out({ looped: mo.looped, delivered: mo.delivered,
              docked: document.documentElement.classList.contains('apollo-docked'),
              inSidebar: document.getElementById('apollo-control').parentNode === P.sb });
        D.unmountDeck();
    """)
    assert o["looped"] is False, "the control pane kept waking its own watcher: the page hangs"
    assert o["delivered"] <= 2
    assert o["docked"] is True and o["inSidebar"] is True


@node
def test_tucking_the_sidebar_moves_the_pane_once_and_settles(box):
    o = _run(box, _PRE, """
        const P = apolloPage();
        D.mountDeck();
        await settle();
        mo.delivered = 0;
        P.sb.classList.add('hidden');
        await settle();
        const deck = document.getElementById('apollo-deck');
        const tucked = { looped: mo.looped, inDeck: document.getElementById('apollo-control').parentNode === deck,
                         docked: document.documentElement.classList.contains('apollo-docked') };
        mo.delivered = 0;
        P.sb.classList.remove('hidden');
        await settle();
        const back = { looped: mo.looped, inSidebar: document.getElementById('apollo-control').parentNode === P.sb,
                       docked: document.documentElement.classList.contains('apollo-docked') };
        out({ tucked, back });
        D.unmountDeck();
    """)
    assert o["tucked"] == {"looped": False, "inDeck": True, "docked": False}
    assert o["back"] == {"looped": False, "inSidebar": True, "docked": True}


@node
def test_on_a_phone_an_unrelated_class_change_settles_too(box):
    """The pane sits in the deck and `apollo-docked` is off; removing it again
    is a write as well."""
    o = _run(box, _PRE, """
        apolloPage();
        media.wide = false;
        D.mountDeck();
        await settle();
        mo.delivered = 0;
        document.documentElement.classList.add('dark');
        await settle();
        out({ looped: mo.looped, delivered: mo.delivered,
              docked: document.documentElement.classList.contains('apollo-docked') });
        media.wide = true;
        D.unmountDeck();
    """)
    assert o["looped"] is False
    assert o["delivered"] <= 2
    assert o["docked"] is False


def test_entering_apollos_page_again_writes_no_class_it_already_has():
    """New chat enters Apollo's page while it is up. Writing `apollo-view` then
    changes nothing on screen and only wakes every class watcher on the page."""
    src = VIEW.read_text(encoding="utf-8")
    start = src.index("export function enterApolloView")
    body = src[start:src.index("\n}\n", start)]
    assert "html.classList.add('apollo-view')" in body
    assert "!html.classList.contains('apollo-view')" in body
