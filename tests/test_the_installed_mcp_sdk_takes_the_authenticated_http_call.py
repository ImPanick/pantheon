# SPDX-License-Identifier: AGPL-3.0-or-later
"""The installed `mcp` SDK accepts the authenticated HTTP call `mcp_manager` makes.

`B626`. `McpManager._connect_http` imports
`mcp.client.streamable_http.streamablehttp_client` inside the function and
calls it `streamablehttp_client(url, auth=provider)`, where `provider` is the
`OAuthClientProvider` `src/mcp_oauth.py` builds. Measured 2026-09-18: under
`mcp` 2.2.0 that symbol is gone (it is `streamable_http_client`) and its
replacement has no `auth` parameter (`(url, *, http_client,
terminate_on_close)`) — two hard breaks on the only remote transport OAuth runs
on, and no test failed on either, because the import is lazy and the one test
that fakes the symbol takes `**k`.

So the call is read out of `src/mcp_manager.py` — the module and symbol it
imports, and the arguments it passes — rather than written down here, and
bound against the installed SDK's own signature. A rename or a dropped keyword
on either side is a red case naming which.
"""
import ast
import importlib
import inspect
import types
import typing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_MANAGER = ROOT / "src" / "mcp_manager.py"


def _the_call():
    """`(module, symbol, positional count, keyword names)` from `_connect_http`."""
    tree = ast.parse(_MANAGER.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_connect_http")
    imported = next(n for n in ast.walk(fn)
                    if isinstance(n, ast.ImportFrom)
                    and (n.module or "").startswith("mcp.client.streamable_http"))
    symbol = imported.names[0]
    local = symbol.asname or symbol.name
    call = next(n for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == local)
    return imported.module, symbol.name, len(call.args), [k.arg for k in call.keywords]


def _problems(module, symbol, positional, keywords) -> list:
    """What stops the call `_connect_http` makes from binding on `module`."""
    fn = getattr(module, symbol, None)
    if fn is None:
        return [f"{module.__name__} has no `{symbol}` (it exports "
                f"{sorted(n for n in dir(module) if 'client' in n)})"]
    sig = inspect.signature(fn)
    out = []
    try:
        sig.bind(*(["https://mcp.example/mcp"] * positional), **{k: None for k in keywords})
    except TypeError as e:
        out.append(f"`{symbol}{sig}` does not take the call: {e}")
    if "auth" in keywords and "auth" in sig.parameters:
        import httpx
        annotation = sig.parameters["auth"].annotation
        if httpx.Auth not in (typing.get_args(annotation) or (annotation,)):
            out.append(f"`auth` is annotated {annotation!r}, not an httpx.Auth")
    return out


def test_the_call_is_read_from_the_manager():
    module, symbol, positional, keywords = _the_call()
    assert module == "mcp.client.streamable_http"
    assert "auth" in keywords, "the OAuth provider is passed by keyword"
    assert positional == 1


def test_the_installed_sdk_takes_the_call_the_manager_makes():
    module_name, symbol, positional, keywords = _the_call()
    module = importlib.import_module(module_name)
    assert _problems(module, symbol, positional, keywords) == []


def test_the_provider_the_manager_passes_is_what_auth_takes():
    import httpx
    from mcp.client.auth import OAuthClientProvider

    assert issubclass(OAuthClientProvider, httpx.Auth)


@pytest.mark.parametrize("shape", ["renamed", "no_auth"])
def test_the_check_fails_on_the_2_2_0_shape(shape):
    """The SDK this row measured, as a stand-in: the check is not a tautology."""
    _, symbol, positional, keywords = _the_call()
    fake = types.ModuleType("mcp.client.streamable_http")

    def streamable_http_client(url, *, http_client=None, terminate_on_close=True):
        raise AssertionError("never called")

    fake.streamable_http_client = streamable_http_client
    if shape == "no_auth":
        setattr(fake, symbol, streamable_http_client)
    found = _problems(fake, symbol, positional, keywords)
    assert found, shape
    assert (symbol in found[0]) if shape == "renamed" else ("auth" in found[0]), found
