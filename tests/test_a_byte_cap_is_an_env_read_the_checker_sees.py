# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B551` — the byte caps are environment reads, and `check-env-declared.py` sees them.

`literal_reads()` recognised `os.getenv("X")`, `os.environ["X"]`, `env_flag`
and `env_backed`. It had no pattern for `read_byte_limit_env`, the house helper
`src/upload_limits.py` and `routes/backup_routes.py` read the byte caps
through, and inside that helper the name is a parameter. So of the eleven
`PANTHEON_*BYTES` variables the checker saw one — the TTS cache cap, because it
is still a raw `os.getenv` — and every rule that starts from a read (undeclared,
spelling, boundary, the `H06` reachability rule) was blind to the other ten.
`B91` wrote the lesson into the checker about `env_flag`: *a helper that makes
the checker blinder than the code it replaced is a worse defect than the one it
fixed.*

Three spellings are read now, each driven below over a fixture repository and
over the real tree: a literal first argument, `resolve_byte_cap(key, "X", …)`,
and the register — `read_byte_limit_env(*BYTE_LIMITS["key"])`, where the
register is read whole because `resolve_byte_limit_with_source` hands every
entry to `resolve_byte_cap` by key (that is how the chat composer's cap is read,
and no call names it).

**The row's third clause, re-measured (`Law 3`).** It asked that a byte-cap key
flipped from `None` to a truthy default fail the checker's reachability rule.
That rule pairs a `get_setting(K)` with an env read in one scope, and the byte
caps have no such scope: they resolve through `settings.resolve_limit`, which
asks `setting_is_explicit` — so a truthy shipped default does **not** make the
env leg unreachable, and the last test here drives that through the real
resolver. What the rule needed was to be able to see a byte-cap read at all, so
that the shape it exists for — `get_setting(K)` beside
`read_byte_limit_env("PANTHEON_K", …)` — fails when someone writes it; that is
driven too. The shipped `None` itself is pinned by
`tests/test_limits_are_policy.py`.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-env-declared.py"


def _load_checker(root: Path | None = None):
    spec = importlib.util.spec_from_file_location("_b551_env_checker", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if root is not None:
        module.ROOT = root
        module.ENV_EXAMPLE = root / ".env.example"
        module.SETTINGS_SOURCE = root / "src" / "settings.py"
        module._corpus.cache_clear()
    return module


def _repo(tmp_path: Path, files: dict):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (tmp_path / ".env.example").touch()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    return _load_checker(tmp_path)


LIMITS = '''\
import os
CHAT_ENV = "PANTHEON_CHAT_MAX_BYTES"

def read_byte_limit_env(name, default):
    raw = os.getenv(name)
    return int(raw) if raw else default

def resolve_byte_cap(key, env_name, default, owner=None):
    return read_byte_limit_env(env_name, default), env_name

REGISTER: dict = {
    "a_max_bytes": ("PANTHEON_A_MAX_BYTES", 1),
    "chat_max_bytes": (CHAT_ENV, 2),
}

A = read_byte_limit_env(*REGISTER["a_max_bytes"])
B = read_byte_limit_env("PANTHEON_B_MAX_BYTES", 3)

def tts():
    return resolve_byte_cap("c_max_bytes", "PANTHEON_C_MAX_BYTES", 4)
'''


def test_every_spelling_of_a_byte_cap_read_is_seen(tmp_path):
    """The register's entries — including one spelled as a module constant and
    one no call names — the literal first argument, and the literal second
    argument of `resolve_byte_cap`. The parameter inside the helper is not a
    name and is not invented as one."""
    mod = _repo(tmp_path, {"src/limits.py": LIMITS})
    reads = mod.literal_reads()
    assert {n for n in reads if n.endswith("_MAX_BYTES")} == {
        "PANTHEON_A_MAX_BYTES", "PANTHEON_CHAT_MAX_BYTES",
        "PANTHEON_B_MAX_BYTES", "PANTHEON_C_MAX_BYTES"}, sorted(reads)
    assert reads["PANTHEON_CHAT_MAX_BYTES"] == {"src/limits.py"}


def test_the_real_tree_reads_every_byte_cap_it_ships():
    """The row's `Verify`, against the register that owns the fact: every name
    in `BYTE_LIMITS`, plus the two caps owned by the modules that enforce them,
    is a read the checker sees — and none of them is undeclared."""
    import src.upload_limits as UL
    expected = {env for env, _default in UL.BYTE_LIMITS.values()} | {
        "PANTHEON_BACKUP_IMPORT_MAX_BYTES", "PANTHEON_TTS_CACHE_MAX_BYTES"}
    mod = _load_checker()
    reads = mod.literal_reads()
    seen = {n for n in reads if n.startswith("PANTHEON_") and "BYTES" in n}
    assert seen == expected, (sorted(expected - seen), sorted(seen - expected))
    assert expected <= set(mod.declared()), sorted(expected - set(mod.declared()))


SETTINGS = '''\
DEFAULT_SETTINGS = {
    "d_max_bytes": %s,
}
'''

UNREACHABLE_SHAPE = '''\
from src.settings import get_setting
from src.limits import read_byte_limit_env

def cap():
    return get_setting("d_max_bytes") or read_byte_limit_env("PANTHEON_D_MAX_BYTES", 5)
'''


def test_the_reachability_rule_fires_on_a_byte_cap_read_beneath_a_truthy_default(tmp_path):
    """`H06`'s shape with the house helper: `get_setting(K)` merges the shipped
    default on every read, so with a truthy default the env read beneath it
    cannot run. Before `B551` the rule could not see the env half."""
    mod = _repo(tmp_path, {"src/limits.py": LIMITS,
                           "src/settings.py": SETTINGS % "1024",
                           "src/cap.py": UNREACHABLE_SHAPE})
    found = mod.unreachable(mod.shipped_defaults())
    assert any("PANTHEON_D_MAX_BYTES is read beneath d_max_bytes, which ships 1024" in f
               for f in found), found


def test_a_falsy_default_leaves_the_byte_cap_read_reachable(tmp_path):
    """`H06`'s own distinction, kept: a falsy literal default has nothing to
    flatten, so the same shape is not reported."""
    mod = _repo(tmp_path, {"src/limits.py": LIMITS,
                           "src/settings.py": SETTINGS % "0",
                           "src/cap.py": UNREACHABLE_SHAPE})
    assert mod.unreachable(mod.shipped_defaults()) == []


@pytest.fixture
def store(tmp_path, monkeypatch):
    import src.settings as S
    path = tmp_path / "settings.json"
    monkeypatch.setattr(S, "SETTINGS_FILE", str(path))

    def _store(**kw):
        path.write_text(json.dumps(kw), encoding="utf-8")
        S._invalidate_caches()

    _store()
    yield _store
    S._invalidate_caches()


def test_a_truthy_shipped_byte_cap_does_not_make_its_env_unreachable(store, monkeypatch):
    """Why the real tree's byte caps are not reported even with a shipped
    number: `resolve_limit` asks `setting_is_explicit`, not `get_setting`, so
    the env leg answers both before a save and after one materialises every
    default. Driven through the real resolver."""
    import src.settings as S
    import src.upload_limits as UL
    key = "gallery_upload_max_bytes"
    env_name, _default = UL.BYTE_LIMITS[key]
    monkeypatch.setitem(S.DEFAULT_SETTINGS, key, 10 * 1024 * 1024)
    monkeypatch.setenv(env_name, "4242")
    store()
    assert UL.resolve_byte_limit_with_source(key) == (4242, env_name)
    store(**{key: 10 * 1024 * 1024})          # one admin save, materialised
    assert S.get_setting(key) == 10 * 1024 * 1024
    assert UL.resolve_byte_limit_with_source(key) == (4242, env_name)
