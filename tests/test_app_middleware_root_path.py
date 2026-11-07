# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1958`. Under `--root-path`, the request ceiling and the foreground gate
misread every path.

`app.py`'s request ceiling (`_RequestTimeoutMiddleware`, 45 s) leaves alone
the routes that rightly take longer: uploads, research, model probes, the
memory audit, a step test. Its foreground gate
(`_InteractiveActivityMiddleware`) leaves alone the page's own polls: the
heartbeat, health, a stream's status. Both matched their lists against
`request.url.path`, and uvicorn's `--root-path` (a deployment `docs/setup.md`
documents) puts the prefix on every request's path, so neither list ever
matched: a long upload was cut off with a 504, and every poll stopped the
background work the gate exists to let run.

Both now ask the path Starlette routes by (`get_application_route_path`), as
`AuthMiddleware` does and `SecurityHeadersMiddleware` does since `B1957`.
Driven through the real middleware classes of the real app, out of process: a
small app behind each, asked with and without a prefix.

Reported upstream in Odysseus PR #6179 (4d630e6c).
"""
from __future__ import annotations

import pytest

from tests.helpers.gated_app import gated_app_probe

PREFIXES = ("", "/pantheon")

_PROBE = r'''
import asyncio
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

app_module.REQUEST_HARD_TIMEOUT = 0.2            # the ceiling, at a fifth of a second

async def slow(request):
    await asyncio.sleep(1.0)
    return PlainTextResponse("done")

ceiling = Starlette(routes=[Route(path, slow) for path in CEILING])
ceiling.add_middleware(app_module._RequestTimeoutMiddleware)

stopped = []

async def stop(reason=""):
    stopped.append(reason)

app_module.task_scheduler.stop_background_tasks_for_foreground = stop

async def quick(request):
    await asyncio.sleep(0.05)
    return PlainTextResponse("ok")

gate = Starlette(routes=[Route(path, quick) for path in GATE])
gate.add_middleware(app_module._InteractiveActivityMiddleware)

def ask(app, prefix, path):
    return TestClient(app, root_path=prefix).get(prefix + path)

RESULT["ceiling"], RESULT["stops"] = {}, {}
for prefix in PREFIXES:
    RESULT["ceiling"][prefix] = {path: ask(ceiling, prefix, path).status_code for path in CEILING}
    RESULT["stops"][prefix] = {}
    for path in GATE:
        before = len(stopped)
        ask(gate, prefix, path)
        RESULT["stops"][prefix][path] = len(stopped) - before
'''

#: A route the ceiling leaves alone, and one it does not.
CEILING = {"/api/upload/x": 200, "/api/sessions/x": 504}
#: The page's own polls stop nothing; a person's request stops background work.
GATE = {"/api/activity/heartbeat": 0, "/api/health": 0, "/api/chat/stream_status/c1": 0,
        "/api/sessions": 1}


@pytest.fixture(scope="module")
def asked(tmp_path_factory):
    body = (f"PREFIXES = {PREFIXES!r}\nCEILING = {sorted(CEILING)!r}\nGATE = {sorted(GATE)!r}\n"
            + _PROBE)
    return gated_app_probe(tmp_path_factory.mktemp("b1958"), body,
                           {"BACKGROUND_TASK_FOREGROUND_GATE": "true"}, accounts=False)


def test_the_request_ceiling_leaves_a_long_upload_alone_under_a_prefix(asked):
    for prefix in PREFIXES:
        assert asked["ceiling"][prefix] == CEILING, prefix or "no prefix"


def test_the_page_s_own_polls_stop_no_background_work_under_a_prefix(asked):
    for prefix in PREFIXES:
        assert asked["stops"][prefix] == GATE, prefix or "no prefix"
