# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression tests for the configurable LLM connect timeout.

Background: chat uses the streaming path, which (unlike llm_call) does not retry
a connect error -- it marks the host and emits a 503 immediately. With the old
hard-coded connect=3.0s, a brief blip on the first (cold) connect of an idle
chat to an offshore/public endpoint surfaced as an intermittent 503 that cleared
on resend. The connect budget is now LLMConfig.CONNECT_TIMEOUT (env
LLM_CONNECT_TIMEOUT), applied via _call_timeout/_stream_timeout helpers.
"""
import importlib
import httpx
import pytest

from src import llm_core
from src.llm_core import LLMConfig, _call_timeout, _stream_timeout


def test_default_connect_timeout_is_widened_not_three():
    # Regression guard: must not regress to the old too-tight 3.0s default.
    assert LLMConfig.CONNECT_TIMEOUT >= 8.0
    assert LLMConfig.CONNECT_TIMEOUT != 3.0
    assert LLMConfig.CONNECT_TIMEOUT == 10.0


def test_call_timeout_uses_config_connect_and_passes_read():
    t = _call_timeout(45)
    assert isinstance(t, httpx.Timeout)
    assert t.connect == LLMConfig.CONNECT_TIMEOUT
    assert t.read == 45.0
    assert t.write == 10.0
    assert t.pool == 5.0


def test_stream_timeout_uses_config_connect_and_passes_read():
    t = _stream_timeout(300)
    assert isinstance(t, httpx.Timeout)
    assert t.connect == LLMConfig.CONNECT_TIMEOUT
    assert t.read == 300.0
    assert t.write == 30.0
    assert t.pool == 5.0


def test_helpers_are_config_driven(monkeypatch):
    # Helpers read LLMConfig at call time, so ops can tune without code edits.
    monkeypatch.setattr(LLMConfig, "CONNECT_TIMEOUT", 4.5)
    assert _call_timeout(30).connect == 4.5
    assert _stream_timeout(30).connect == 4.5


def test_env_override_is_honoured():
    """`LLM_CONNECT_TIMEOUT` is read at import, so this needs a fresh import —
    and it takes one in a subprocess rather than by reloading the module.

    **The reload this replaces broke four tests in `test_kimi_code_user_agent`**,
    which imports names from `src.llm_core` by value: rebinding them inside the
    module leaves that file holding the old objects, and the `finally` reload
    produced a third set rather than the originals. **A reload is not undoable**
    (`B18`). CI never saw it because `test_kimi…` sorts before this file and so
    ran first — the same accident that hid `B18` for weeks.

    A subprocess is the fresh import this property actually wants, with a blast
    radius of one process.
    """
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = dict(os.environ, LLM_CONNECT_TIMEOUT="6.5")
    out = subprocess.run(
        [sys.executable, "-c",
         "import json, sys; sys.path.insert(0, '.')\n"
         "from src.llm_core import LLMConfig\n"
         "print(json.dumps(LLMConfig.CONNECT_TIMEOUT))"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=120, env=env,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == 6.5
    # And this process was not disturbed: the class the other tests patch is
    # still the one the helpers read.
    assert _call_timeout(30).connect == LLMConfig.CONNECT_TIMEOUT
