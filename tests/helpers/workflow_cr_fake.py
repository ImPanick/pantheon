# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract C-R (wf-rules), faked where it is absent — `P22-13` … `P22-18` (wf-effects).

`/work/notes/SLICE-CD-DESIGN.md` § 3 splits wave D into four packages that start
together. `src/workflow_effects.py` (wf-effects) consumes wf-rules' contract C-R:
`workflow_slots.RenderedCall` (`kind, tool, content, value_paths, missing`),
`render_call`, `NODE_SLOTS`, `classify_argument`, `Slot`, `workflow_refs.
flatten_fields`/`format_ref`, `workflow_document.ports_of`/`upstream_of`/
`WorkflowResources`, and `workflow_logic.OPERATORS`. None of it was on this
branch when these tests were written, so `install(monkeypatch)` puts a module
with exactly the contract's names into `sys.modules` **only when the real one
cannot be imported** — once wf-rules merges, every test here runs against the
real module and this file installs nothing.

Where the contract names a function and not its exact answer, the fake answers
the way § 1.1–1.2 of the design describe it, and the handoff note
(`/work/notes/wf-effects.md`) lists each such choice as a merge point:

  * ``render(kind, tool, payload)`` builds a call the way § 1.2 says
    `render_call` does — the call as a dict, then `json.dumps` — so a value is
    a JSON value and never JSON structure. It is NOT `render_call`: the tests
    that use it prove the EXECUTOR's half (it dispatches what it is handed,
    verbatim); `render_call`'s half is wf-rules' tests.

Nothing here is the product.
"""
import importlib
import json
import sys
import types
from typing import Any, NamedTuple


class RenderedCall(NamedTuple):
    """C-R's `RenderedCall(kind, tool, content, value_paths, missing)`."""
    kind: str
    tool: str
    content: str
    value_paths: tuple
    missing: tuple


def _real(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def install(monkeypatch) -> dict:
    """Install the fakes that are needed; answer `{module: "real"|"fake"}`."""
    said = {}
    slots = _real("src.workflow_slots")
    if slots is None:
        slots = types.ModuleType("src.workflow_slots")
        slots.RenderedCall = RenderedCall
        monkeypatch.setitem(sys.modules, "src.workflow_slots", slots)
        said["src.workflow_slots"] = "fake"
    else:
        said["src.workflow_slots"] = "real"
    return said


def rendered_call_type():
    """The `RenderedCall` the executors will accept (the real one when present)."""
    return sys.modules["src.workflow_slots"].RenderedCall


def render(kind: str, tool: str, payload: Any, *, missing=()) -> Any:
    """A call as § 1.2 says `render_call` builds one: a dict, `json.dumps`ed."""
    return rendered_call_type()(kind, tool, json.dumps(payload), (), tuple(missing))
