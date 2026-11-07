# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1887` / `B1888` — the browser's door to *Test this step* can send what the
steps before it made, and ask only what it would read.

The route takes two optional keys (`routes/workflow/workflow_routes.py`
`test_node`): `outputs` — `{"<step id>": {"data": …, "text": "…"}}` — and
`context_only: true`. `workflowApi.testNode` sends each only when it is given,
so the body the Test panel sends today (`{node, source, input, confirm}`) is
byte for byte what it was; the panel (the UI owner's) is the caller that will
fill them.

Driven: the real `workflowApi.js` over a recording `fetch`.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_the_workflow_data_layer_js import _PREAMBLE, _run, box  # noqa: E402,F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def test_test_node_sends_outputs_and_context_only_only_when_given(box):  # noqa: F811
    o = _run(box, _PREAMBLE + "seed({ ...DOC, id: 'w1' });\n", """
        const calls = [
          () => api.testNode('w1', 'n2', { node: { id: 'n2' }, source: 'last' }),
          () => api.testNode('w1', 'n2', { node: { id: 'n2' }, source: 'last',
                                           outputs: { n1: { data: { greeting: 'goodbye' } }, start: { data: { a: 1 } } } }),
          () => api.testNode('w1', 'n2', { node: { id: 'n2' }, contextOnly: true }),
        ];
        for (const c of calls) { try { await c(); } catch (_) {} }
        out(sent());
    """)
    url = "/api/workflows/w1/nodes/n2/test"
    assert o == [
        ["POST", url, {"node": {"id": "n2"}, "source": "last", "confirm": False}],
        ["POST", url, {"node": {"id": "n2"}, "source": "last", "confirm": False,
                       "outputs": {"n1": {"data": {"greeting": "goodbye"}}, "start": {"data": {"a": 1}}}}],
        ["POST", url, {"node": {"id": "n2"}, "source": "none", "confirm": False, "context_only": True}],
    ]
