# SPDX-License-Identifier: AGPL-3.0-or-later
"""`H21` — a variable the compose files hand the app is one the app reads.

`RESEARCH_LLM_ENDPOINT` was declared in `.env.example` (*"Research service LLM
endpoint"*) and forwarded into the Pantheon container by all three compose
files, and no code read it: an operator who set it believed the research
service would use that endpoint, and nothing changed. `check-env-declared.py`'s
UNREFERENCED rule could not see it — it is loose on purpose and counts any
mention, and a compose forward is a mention.

So the forward itself is held here: every `NAME=${NAME…}` in the environment
of a compose service built from this repository (`build:`) names a variable
some product code reads — a literal read `check-env-declared.literal_reads`
finds, or a mention in a `.py`/`.js`/`.sh` file outside the tests (the
indirect reads, `os.getenv(SOME_CONST)`, which that scan is blind to).
"""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = sorted(ROOT.glob("docker-compose*.yml"))
_FORWARD = re.compile(r"^([A-Z][A-Z0-9_]*)=\$\{\1\b")


def _checker():
    spec = importlib.util.spec_from_file_location(
        "_pantheon_env_declared", ROOT / ".pantheon" / "check-env-declared.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _forwarded_to_the_app() -> dict:
    """`{name: [compose file, ...]}` for the services this repository builds."""
    out: dict = {}
    for path in COMPOSE:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for service in (data.get("services") or {}).values():
            if not isinstance(service, dict) or "build" not in service:
                continue
            env = service.get("environment") or []
            items = env if isinstance(env, list) else [f"{k}={v}" for k, v in env.items()]
            for item in items:
                m = _FORWARD.match(str(item))
                if m:
                    out.setdefault(m.group(1), []).append(path.name)
    return out


def _code_text() -> str:
    files = subprocess.run(["git", "ls-files", "*.py", "*.js", "*.mjs", "*.sh", "*.ps1",
                            "Dockerfile"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    if not files:   # not a checkout: read the tree
        files = [p.relative_to(ROOT).as_posix() for ext in ("py", "js", "sh")
                 for p in ROOT.rglob(f"*.{ext}") if "venv" not in p.parts]
    keep = [f for f in files if not f.startswith(("tests/", ".pantheon/", "venv/"))]
    return "\n".join((ROOT / f).read_text(encoding="utf-8", errors="ignore") for f in keep
                     if (ROOT / f).is_file())


def test_the_app_reads_every_variable_compose_forwards_to_it():
    forwarded = _forwarded_to_the_app()
    assert forwarded, "no compose service built from this repository was found"
    reads = set(_checker().literal_reads())
    code = _code_text()
    unread = {name: where for name, where in forwarded.items()
              if name not in reads and not re.search(rf"\b{name}\b", code)}
    assert unread == {}, unread


def test_the_research_endpoint_is_neither_promised_nor_forwarded():
    """The one the row named, by name: not in `.env.example`, not forwarded."""
    assert "RESEARCH_LLM_ENDPOINT" not in (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "RESEARCH_LLM_ENDPOINT" not in _forwarded_to_the_app()
