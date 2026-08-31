import asyncio
import importlib.util
from pathlib import Path
import subprocess
import sys
import types


ROOT = Path(__file__).resolve().parent.parent


def _load_builtin_mcp(monkeypatch):
    core = types.ModuleType("core")
    core.__path__ = []
    platform_compat = types.ModuleType("core.platform_compat")
    platform_compat.IS_WINDOWS = False
    platform_compat.which_tool = lambda name: None
    monkeypatch.setitem(sys.modules, "core", core)
    monkeypatch.setitem(sys.modules, "core.platform_compat", platform_compat)

    spec = importlib.util.spec_from_file_location(
        "builtin_mcp_under_test",
        ROOT / "src" / "builtin_mcp.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_npx_package_from_args_prefers_package_after_y_flag(monkeypatch):
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp._npx_package_from_args(
        ["-y", "@playwright/mcp@latest", "--headless"]
    ) == "@playwright/mcp@latest"


def test_a_fresh_install_does_not_fetch_from_npm_at_boot(monkeypatch):
    """`Law 16` at its sharpest point.

    This test previously asserted the opposite -- that requiring a cached
    package was opt-IN, so the default path ran `npx -y @playwright/mcp@latest`
    about three seconds after every startup. That meant a fresh install with no
    account, no key and no user action reached registry.npmjs.org before anyone
    had clicked anything, and re-checked the `@latest` dist-tag on every boot
    thereafter.

    Reversed deliberately on 2026-08-31, on the owner's directive that nothing
    routes anywhere until a person links it. The capability is unchanged:
    browser automation still starts the moment the package is on disk. What is
    gone is Pantheon going to get it uninvited.
    """
    monkeypatch.delenv("PANTHEON_BROWSER_MCP_REQUIRE_CACHE", raising=False)
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp.BROWSER_MCP_REQUIRE_CACHE is True, (
        "the default boot path installs from the npm registry before the user has acted"
    )


def test_the_fetch_can_still_be_opted_into(monkeypatch):
    """Deliberate is fine. Silent is not. Both directions must be reachable."""
    monkeypatch.setenv("PANTHEON_BROWSER_MCP_REQUIRE_CACHE", "0")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp.BROWSER_MCP_REQUIRE_CACHE is False


def test_an_explicit_1_still_means_cache_only(monkeypatch):
    monkeypatch.setenv("PANTHEON_BROWSER_MCP_REQUIRE_CACHE", "1")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    assert builtin_mcp.BROWSER_MCP_REQUIRE_CACHE is True


def test_browser_mcp_args_use_configured_browser_executable(monkeypatch):
    monkeypatch.setenv("PANTHEON_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args(["-y", "@playwright/mcp@latest", "--headless"])

    assert "--executable-path" in args
    assert "/usr/bin/chromium" in args
    assert "--isolated" in args
    assert "--no-sandbox" in args


def test_browser_mcp_args_can_use_persistent_profile_when_requested(monkeypatch):
    monkeypatch.setenv("PANTHEON_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    monkeypatch.setenv("PANTHEON_BROWSER_ISOLATED", "0")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args(["-y", "@playwright/mcp@latest", "--headless"])

    assert "--executable-path" in args
    assert "--isolated" not in args


def test_browser_mcp_args_respect_explicit_user_data_dir(monkeypatch):
    monkeypatch.setenv("PANTHEON_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args([
        "-y", "@playwright/mcp@latest", "--headless", "--user-data-dir", "/tmp/profile",
    ])

    assert "--user-data-dir" in args
    assert "--isolated" not in args


def test_browser_mcp_args_can_keep_sandbox(monkeypatch):
    monkeypatch.setenv("PANTHEON_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    monkeypatch.setenv("PANTHEON_BROWSER_NO_SANDBOX", "0")
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    args = builtin_mcp._browser_mcp_args(["-y", "@playwright/mcp@latest", "--headless"])

    assert "--executable-path" in args
    assert "--no-sandbox" not in args


def test_npx_cache_check_detects_scoped_package_in_npx_cache(monkeypatch, tmp_path):
    builtin_mcp = _load_builtin_mcp(monkeypatch)
    package_json = (
        tmp_path
        / ".npm"
        / "_npx"
        / "9833c18b2d85bc59"
        / "node_modules"
        / "@playwright"
        / "mcp"
        / "package.json"
    )
    package_json.parent.mkdir(parents=True)
    package_json.write_text('{"name":"@playwright/mcp","version":"0.0.76"}', encoding="utf-8")

    async def unexpected_exec(*args, **kwargs):
        raise AssertionError("cache hit should not shell out to npx")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("npm_config_cache", raising=False)
    monkeypatch.setattr(builtin_mcp.asyncio, "create_subprocess_exec", unexpected_exec)

    assert asyncio.run(
        builtin_mcp._is_npx_package_cached(
            "npx",
            "@playwright/mcp@latest",
            timeout_s=2,
        )
    ) is True


def test_npx_cache_check_falls_back_when_async_subprocess_is_unsupported(monkeypatch, tmp_path):
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    async def unsupported_exec(*args, **kwargs):
        raise NotImplementedError("subprocess transport unavailable")

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout=b"1.2.3\n", stderr=b"")

    monkeypatch.setattr(builtin_mcp.asyncio, "create_subprocess_exec", unsupported_exec)
    monkeypatch.setattr(builtin_mcp.subprocess, "run", fake_run)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("npm_config_cache", raising=False)

    assert asyncio.run(
        builtin_mcp._is_npx_package_cached(
            "npx.cmd",
            "@playwright/mcp@latest",
            timeout_s=2,
        )
    ) is True
    assert captured["args"] == [
        "npx.cmd",
        "--no-install",
        "@playwright/mcp@latest",
        "--version",
    ]
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["timeout"] == 2


def test_npx_cache_check_fallback_treats_timeout_as_cache_miss(monkeypatch, tmp_path):
    builtin_mcp = _load_builtin_mcp(monkeypatch)

    async def unsupported_exec(*args, **kwargs):
        raise NotImplementedError("subprocess transport unavailable")

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(builtin_mcp.asyncio, "create_subprocess_exec", unsupported_exec)
    monkeypatch.setattr(builtin_mcp.subprocess, "run", fake_run)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("npm_config_cache", raising=False)

    assert asyncio.run(
        builtin_mcp._is_npx_package_cached(
            "npx.cmd",
            "@playwright/mcp@latest",
            timeout_s=2,
        )
    ) is False
