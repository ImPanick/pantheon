# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1520`. What a model endpoint that cannot be reached answers — without reaching for it.

`src.model_context` asks a model's endpoint for its context window
(`/v1/models`, llama.cpp's `/slots`) on the way into every agent round. A test
whose endpoint is `https://selected.example/v1` or `http://192.168.1.20:8080/v1`
made those requests for real, and passed because they failed: through the
agent proxy here, by DNS in CI. `tests/conftest.py` now refuses such a connect
and names the test; this is the stand-in that makes the lookup fail the way it
did, with no socket opened — so the code under test takes exactly the branch it
took before (the known table, or the default window).
"""
import httpx


class _Unreachable:
    """`httpx` as `src.model_context` uses it, with `get` failing as an
    unreachable host does. Every other name is the real module's."""

    def __getattr__(self, name):
        return getattr(httpx, name)

    @staticmethod
    def get(url, *args, **kwargs):
        raise httpx.ConnectError(f"{url}: no endpoint answers in this test (B1520)")


def no_endpoint_answers(monkeypatch) -> None:
    """Make the context-window lookups fail as with no network, and start each
    test from an empty cache of windows."""
    import src.model_context as model_context

    monkeypatch.setattr(model_context, "httpx", _Unreachable())
    monkeypatch.setattr(model_context, "_context_cache", {})
