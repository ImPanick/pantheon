# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P3-16` — the shape that cost PandaOS its users' API keys, in this codebase.

One shape, two halves, and neither half is wrong on its own::

    def load():                        def save(x):
        try:    return read()              write(x)
        except: return {}              # <- called with what load() returned

`except: return {}` is correct for a loader that runs at startup and must not
take the app down. It becomes data loss the moment a caller does
`s = load(); s[k] = v; save(s)` — which is how almost every setting, key and
preference in this product is written. The read fails quietly, the empty
default is filled in with one edit, and the save persists it over everything
that was really there. Nothing raises. Nothing logs, in the old code.

These tests are the row's `Verify` line — *"no writer persists a value derived
from a read that failed; a failed read aborts the write"* — executed against
each store, by corrupting the file and asserting the bytes are still there
afterwards. They are deliberately written as *outcomes*: what survives on disk,
not which helper was called, so the guard can be reimplemented without
rewriting the evidence that it works.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CONFIG_WRITES = _REPO / ".pantheon" / "check-config-writes.py"

CORRUPT = '{"real": "data", "and then'


# ── the mechanism ─────────────────────────────────────────────────────────────


def test_the_guard_refuses_an_unreadable_target_and_leaves_it_alone(tmp_path):
    from core.atomic_io import UnreadableTargetError, atomic_write_json

    target = tmp_path / "store.json"
    target.write_text(CORRUPT, encoding="utf-8")
    with pytest.raises(UnreadableTargetError):
        atomic_write_json(str(target), {"replacement": True}, preserve_unreadable=True)
    assert target.read_text(encoding="utf-8") == CORRUPT


def test_the_guard_is_about_reading_and_not_about_existing(tmp_path):
    # An absent file is an empty state and creating it is the write's job.
    # Confusing the two would make every first save fail.
    from core.atomic_io import atomic_write_json

    target = tmp_path / "nested" / "store.json"
    atomic_write_json(str(target), {"first": True}, preserve_unreadable=True)
    assert json.loads(target.read_text(encoding="utf-8")) == {"first": True}
    atomic_write_json(str(target), {"second": True}, preserve_unreadable=True)
    assert json.loads(target.read_text(encoding="utf-8")) == {"second": True}


def test_without_the_flag_nothing_changes(tmp_path):
    # The guard is opt-in per store, and it has to stay that way: a rebuildable
    # file is repaired *by* being overwritten, and guarding one would wedge it.
    from core.atomic_io import atomic_write_json

    target = tmp_path / "state.json"
    target.write_text(CORRUPT, encoding="utf-8")
    atomic_write_json(str(target), {"rebuilt": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"rebuilt": True}


def test_an_unreadable_target_is_not_a_bad_write_request(tmp_path):
    from core.atomic_io import UnreadableTargetError

    # An OSError, because callers around this already handle filesystem
    # refusals and a store that cannot be read is not a complaint about the
    # data being written.
    assert issubclass(UnreadableTargetError, OSError)


# ── auth.json: the user database ──────────────────────────────────────────────


def test_an_unreadable_auth_file_is_not_an_empty_user_database(tmp_path):
    # The whole chain, because each link alone looks survivable: unreadable
    # file -> `_config = {}` -> `is_configured` False -> first-run setup opens
    # -> `create_user` -> `_save()` writes one admin over everybody.
    from core.auth import AuthManager

    auth_path = tmp_path / "auth.json"
    real = AuthManager(str(auth_path))
    assert real.setup("alice", "correct horse battery staple") is True
    good = auth_path.read_text(encoding="utf-8")
    assert "alice" in good

    auth_path.write_text('{"users": {"alice"', encoding="utf-8")
    broken = AuthManager(str(auth_path))

    assert broken.users == {}, "the in-memory view is empty, which is the trap"
    assert broken.is_configured is True, (
        "False is the permissive answer everywhere this is read — it opens "
        "setup, lets loopback callers through unauthenticated, and hands out "
        "note admin. An unreadable file must never produce it."
    )
    assert broken.setup("mallory", "hunter2hunter2") is False
    assert auth_path.read_text(encoding="utf-8") == '{"users": {"alice"'


def test_a_process_that_could_not_read_auth_never_writes_it(tmp_path):
    # Even after the operator repairs the file: this process still holds the
    # empty config the failed load produced, so a write-time readability check
    # on its own would happily persist it over the repair.
    from core.atomic_io import UnreadableTargetError
    from core.auth import AuthManager

    auth_path = tmp_path / "auth.json"
    seed = AuthManager(str(auth_path))
    seed.setup("alice", "correct horse battery staple")
    good = auth_path.read_text(encoding="utf-8")

    auth_path.write_text("not json at all", encoding="utf-8")
    broken = AuthManager(str(auth_path))
    auth_path.write_text(good, encoding="utf-8")  # the operator fixes it

    with pytest.raises(UnreadableTargetError):
        broken.create_user("bob", "another long enough password")
    assert auth_path.read_text(encoding="utf-8") == good
    assert "alice" in auth_path.read_text(encoding="utf-8")


def test_a_healthy_auth_file_still_takes_writes(tmp_path):
    from core.auth import AuthManager

    mgr = AuthManager(str(tmp_path / "auth.json"))
    assert mgr.setup("alice", "correct horse battery staple") is True
    assert mgr.create_user("bob", "another long enough password") is True
    assert sorted(mgr.users) == ["alice", "bob"]


# ── api_keys.json: the store the row is named after ───────────────────────────


def test_one_unreadable_keystore_does_not_cost_every_other_providers_key(tmp_path):
    from core.atomic_io import UnreadableTargetError
    from src.api_key_manager import APIKeyManager

    mgr = APIKeyManager(str(tmp_path))
    mgr.save("openai", "sk-openai-secret")
    mgr.save("anthropic", "sk-anthropic-secret")
    store = tmp_path / "api_keys.json"
    assert sorted(mgr.load()) == ["anthropic", "openai"]

    store.write_text('{"openai": "enc:truncat', encoding="utf-8")
    with pytest.raises(UnreadableTargetError):
        mgr.save("groq", "sk-groq-secret")
    assert store.read_text(encoding="utf-8") == '{"openai": "enc:truncat'


def test_reading_the_keystore_still_degrades_quietly(tmp_path):
    # `load()` runs at startup. It must keep answering "no keys" rather than
    # taking the app down — the fix is on the write side only.
    from src.api_key_manager import APIKeyManager

    mgr = APIKeyManager(str(tmp_path))
    (tmp_path / "api_keys.json").write_text(CORRUPT, encoding="utf-8")
    assert mgr.load() == {}


# ── settings.json ─────────────────────────────────────────────────────────────


def _run_in_subprocess(body: str, tmp_path: Path) -> str:
    """settings.py binds its paths at import, so each case gets a fresh one."""
    script = (
        "import sys, json, pathlib\n"
        f"sys.path.insert(0, {str(_REPO)!r})\n"
        f"import src.constants as C\n"
        f"C.SETTINGS_FILE = {str(tmp_path / 'settings.json')!r}\n"
        f"C.FEATURES_FILE = {str(tmp_path / 'features.json')!r}\n"
        "import src.settings as S\n"
        f"S.SETTINGS_FILE = {str(tmp_path / 'settings.json')!r}\n"
        f"S.FEATURES_FILE = {str(tmp_path / 'features.json')!r}\n"
        + body
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_a_corrupt_settings_file_is_never_replaced_by_defaults(tmp_path):
    # The read-modify-write every settings caller performs, against a file that
    # cannot be read. `load_settings` hands back defaults so the app keeps
    # working; the save must refuse rather than make the defaults permanent.
    settings = tmp_path / "settings.json"
    settings.write_text('{"github_token": "ghp_real", "agent_email', encoding="utf-8")
    out = _run_in_subprocess(
        """
from core.atomic_io import UnreadableTargetError
s = S.load_settings()
print("defaults" if s.get("github_token") == "" else "read-through")
try:
    s["agent_email_confirm"] = False
    S.save_settings(s)
    print("WROTE")
except UnreadableTargetError:
    print("REFUSED")
""",
        tmp_path,
    )
    assert out.splitlines() == ["defaults", "REFUSED"]
    assert settings.read_text(encoding="utf-8") == '{"github_token": "ghp_real", "agent_email'


def test_a_failed_settings_read_is_not_cached(tmp_path):
    # There is a 2s TTL cache in front of `load_settings`. Caching the defaults
    # a failed read produced gives a two-second window in which the operator
    # can repair the file and the next save will still write the defaults into
    # the repaired one — the guard would not catch that, because by then the
    # file reads perfectly.
    settings = tmp_path / "settings.json"
    settings.write_text("{ broken", encoding="utf-8")
    out = _run_in_subprocess(
        """
import json, pathlib
first = S.load_settings()
pathlib.Path(S.SETTINGS_FILE).write_text(json.dumps({"github_token": "ghp_repaired"}))
second = S.load_settings()
print(second.get("github_token"))
""",
        tmp_path,
    )
    assert out == "ghp_repaired", "the failed read was cached and outlived the repair"


def test_a_healthy_settings_file_still_saves(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"github_token": "ghp_real"}), encoding="utf-8")
    out = _run_in_subprocess(
        """
s = S.load_settings()
s["github_token"] = "ghp_new"
S.save_settings(s)
print(S.load_settings()["github_token"])
""",
        tmp_path,
    )
    assert out == "ghp_new"


def test_features_are_guarded_the_same_way(tmp_path):
    features = tmp_path / "features.json"
    features.write_text('{"rag": false, "gall', encoding="utf-8")
    out = _run_in_subprocess(
        """
from core.atomic_io import UnreadableTargetError
f = S.load_features()
try:
    f["rag"] = True
    S.save_features(f)
    print("WROTE")
except UnreadableTargetError:
    print("REFUSED")
""",
        tmp_path,
    )
    assert out == "REFUSED"
    assert features.read_text(encoding="utf-8") == '{"rag": false, "gall'


# ── integrations.json: the decrypt that used to be on the write path ──────────


def test_a_rotated_key_does_not_re_encrypt_empty_strings_over_the_credentials(tmp_path, monkeypatch):
    # The closest thing in this codebase to the failure the row cites, and it
    # fired at *load* time. `decrypt()` returns "" on failure by design — right
    # for a read, "degrade to unconfigured rather than 500". The migration then
    # saved the decrypted rows back, so with a rotated `secret.key` every row
    # became "" and was re-encrypted as "". One hand-edited plaintext row is
    # all it takes to trigger the migration.
    import src.integrations as I

    data_file = tmp_path / "integrations.json"
    monkeypatch.setattr(I, "DATA_FILE", str(data_file))
    monkeypatch.setattr(I, "_ensure_data_dir", lambda: None)
    # A key nobody can decrypt any more, beside one somebody typed in plain.
    data_file.write_text(json.dumps([
        {"id": "a", "api_key": "enc:gAAAAA-cannot-be-decrypted"},
        {"id": "b", "api_key": "plaintext-key"},
    ]), encoding="utf-8")

    monkeypatch.setattr(I, "decrypt", lambda v: "" if str(v).startswith("enc:") else v)
    monkeypatch.setattr(I, "encrypt", lambda v: v if str(v).startswith("enc:") else "enc:" + str(v))

    I.load_integrations()

    stored = {row["id"]: row["api_key"] for row in json.loads(data_file.read_text(encoding="utf-8"))}
    assert stored["a"] == "enc:gAAAAA-cannot-be-decrypted", (
        "the undecryptable row was rewritten; that is the credential gone for good"
    )
    assert stored["b"] == "enc:plaintext-key", "the plaintext row is the one this migration exists for"


def test_integrations_are_not_overwritten_when_the_file_cannot_be_read(tmp_path, monkeypatch):
    from core.atomic_io import UnreadableTargetError
    import src.integrations as I

    data_file = tmp_path / "integrations.json"
    monkeypatch.setattr(I, "DATA_FILE", str(data_file))
    monkeypatch.setattr(I, "_ensure_data_dir", lambda: None)
    monkeypatch.setattr(I, "safe_chmod", lambda *a, **k: None)
    data_file.write_text('[{"id": "a", "api_key": "enc:real', encoding="utf-8")

    assert I.load_integrations() == []
    with pytest.raises(UnreadableTargetError):
        I.save_integrations([{"id": "new", "api_key": "sk-new"}])
    assert data_file.read_text(encoding="utf-8") == '[{"id": "a", "api_key": "enc:real'


# ── every user's preferences in one file ──────────────────────────────────────


def test_one_users_preference_change_cannot_erase_everyones(tmp_path, monkeypatch):
    from core.atomic_io import UnreadableTargetError
    import routes.prefs_routes as P

    prefs = tmp_path / "user_prefs.json"
    monkeypatch.setattr(P, "PREFS_FILE", str(prefs))
    prefs.write_text('{"_users": {"alice": {"vision_model": "m"}, "bob"', encoding="utf-8")

    assert P._load() == {}, "the tolerant read is what makes this dangerous"
    with pytest.raises(UnreadableTargetError):
        P._save({"_users": {"carol": {"vision_model": "n"}}})
    assert "alice" in prefs.read_text(encoding="utf-8")


# ── the uploads index: guarded by a strict read, not by the writer ────────────


def test_the_uploads_index_writers_read_strictly():
    # This file protects itself the other way round — `_load_upload_index`
    # raises when asked to, and keeps a `.bak` sibling to recover from — so the
    # rule here is that every writer asks for the strict read. Two call sites
    # already did and three did not, which is the whole finding: the guard
    # existed in this very file and was not used.
    import ast

    src = (_REPO / "src" / "upload_handler.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    def _calls(node, name):
        return [n for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == name]

    tolerant = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _calls(fn, "_atomic_write_json"):
            continue
        for call in _calls(fn, "_load_upload_index"):
            strict = any(kw.arg == "fail_on_error" for kw in call.keywords)
            if not strict:
                tolerant.append(f"{fn.name}:{call.lineno}")
    assert tolerant == [], (
        "these read the uploads index tolerantly inside a function that writes "
        f"it back, so an unreadable index becomes an erased one: {tolerant}"
    )


def test_the_strict_read_actually_refuses(tmp_path):
    # Without this, the test above is a claim about a keyword argument.
    from src.upload_handler import UploadHandler

    handler = UploadHandler.__new__(UploadHandler)
    handler.upload_dir = str(tmp_path)
    handler._index_cache = None
    handler._index_signature = None
    (tmp_path / "uploads.json").write_text(CORRUPT, encoding="utf-8")

    assert handler._load_upload_index() == {}, "tolerant by default, for startup"
    with pytest.raises(ValueError):
        handler._load_upload_index(fail_on_error=True)


# ── the classification itself ─────────────────────────────────────────────────


def test_every_config_write_in_the_tree_is_classified():
    proc = subprocess.run(
        [sys.executable, str(_REPO / ".pantheon" / "check-config-writes.py")],
        cwd=str(_REPO), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PROBLEMS 0" in proc.stdout


# ── driving the checker without editing the tree it is checking ───────────────
#
# `B270`, and `B221` before it. The three tests below prove `check-config-
# writes.py` bites by showing it a defect. They used to do that by writing the
# defect into `src/settings.py` and `.pantheon/check-config-writes.py` and
# putting the originals back in a `finally:` — and a `finally:` does not run
# when the process is killed. Two of those three windows were open over a
# SHIPPED module, and the third removed `preserve_unreadable=True` from the real
# `atomic_write_json(SETTINGS_FILE, …)` call: a kill inside that window leaves
# the settings-clobbering defect `P3-16` closed sitting in the working tree,
# with nothing to say it is there. This container has killed this suite twice
# for memory (exit 137, one silent death at 38%), so the window is not
# theoretical, and `Law 19` says a suite run is evidence about the tree it
# started with.
#
# The remedy is `B221`'s and is lifted rather than re-invented (`Law 14`):
# patch the LOADED MODULE, never the file on disk. Where the defect has to be
# in source — the checker parses Python with `ast`, so a string will not do —
# the source it parses is a MIRROR of the tree in `tmp_path`, built once and
# copied per test. `tmp_path` is outside the repository, so a kill there costs
# nothing.


@pytest.fixture(autouse=True)
def _the_tree_under_test_is_never_written_to(monkeypatch):
    """No test in this file may write into the repository it is measuring.

    Two halves, because they catch different failures: the intercept stops the
    window existing at all, and the digest comparison afterwards catches any
    route the intercept does not know about — a `subprocess`, an `os.replace`.
    That is the honest limit of an intercept written against three methods.
    """
    watched = {p: p.read_bytes() for p in
               (_REPO / "src" / "settings.py", _CONFIG_WRITES)}
    real_write_text = Path.write_text
    real_write_bytes = Path.write_bytes
    real_open = Path.open

    # TRACKED files, not everything under the repository root. Several tests in
    # this file legitimately write runtime artefacts into `data/`, which is
    # ignored and is not evidence about anything. What a kill must not be able
    # to leave behind is a modified file that `git status` would report.
    tracked = {
        (_REPO / rel).resolve()
        for rel in subprocess.run(["git", "ls-files"], cwd=str(_REPO),
                                  capture_output=True, text=True,
                                  check=True).stdout.split()
    }

    def _inside_repo(path) -> bool:
        try:
            return Path(path).resolve() in tracked
        except OSError:  # pragma: no cover - unresolvable path
            return False

    def _refuse(path):
        raise AssertionError(
            f"B270: a test tried to write {path} — a TRACKED file in the tree "
            "this suite is evidence about. A kill does not run a `finally:`, so "
            "a write-then-restore leaves the repository mutated. Drive the "
            "mirror in `tmp_path`, or patch the loaded module through "
            "`monkeypatch`.")

    def _guarded_write_text(self, *args, **kwargs):
        if _inside_repo(self):
            _refuse(self)
        return real_write_text(self, *args, **kwargs)

    def _guarded_write_bytes(self, *args, **kwargs):
        if _inside_repo(self):
            _refuse(self)
        return real_write_bytes(self, *args, **kwargs)

    def _guarded_open(self, mode="r", *args, **kwargs):
        if any(c in mode for c in "wxa+") and _inside_repo(self):
            _refuse(self)
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _guarded_write_text)
    monkeypatch.setattr(Path, "write_bytes", _guarded_write_bytes)
    monkeypatch.setattr(Path, "open", _guarded_open)
    yield
    monkeypatch.undo()
    for path, before in watched.items():
        assert path.read_bytes() == before, (
            f"B270: {path.relative_to(_REPO)} is not what this test started "
            f"with. A test rewrote it and the restore did not hold.")


def _load_checker(root: Path):
    """The real checker, pointed at `root`. No subprocess, no second copy."""
    spec = importlib.util.spec_from_file_location("config_writes_checker",
                                                  _CONFIG_WRITES)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    return module


def _run(module) -> tuple:
    """`(exit code, stdout)` from `main()`, in process."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = module.main()
    return code, buffer.getvalue()


@pytest.fixture(scope="module")
def _mirror_source(tmp_path_factory):
    """A git repo in `tmp_path` holding every Python file the checker reads.

    Built once: `git ls-files` plus 361 small files is cheap, but not 361 files
    three times.
    """
    base = tmp_path_factory.mktemp("config_writes_mirror") / "tree"
    listed = subprocess.run(["git", "ls-files", "*.py"], cwd=str(_REPO),
                            capture_output=True, text=True, check=True).stdout.split()
    for rel in listed:
        src = _REPO / rel
        if not src.exists():
            continue
        dst = base / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    subprocess.run(["git", "init", "-q"], cwd=str(base), check=True,
                   capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(base), check=True,
                   capture_output=True)
    return base


@pytest.fixture()
def mirror(_mirror_source, tmp_path):
    """A private copy of the mirror, so one test's defect is not another's."""
    tree = tmp_path / "tree"
    shutil.copytree(_mirror_source, tree)
    return tree


def test_the_mirror_is_the_tree_and_the_checker_passes_on_it(mirror):
    """The control. Every assertion below is `the mirror plus one defect`, and
    that is only evidence if the mirror without the defect is clean."""
    code, out = _run(_load_checker(mirror))
    assert code == 0, out
    assert "PROBLEMS 0" in out
    real = subprocess.run(
        [sys.executable, str(_CONFIG_WRITES)], cwd=str(_REPO),
        capture_output=True, text=True, timeout=120)
    assert real.stdout.split("·")[0] == out.split("·")[0], (
        "the mirror holds a different set of write sites from the tree")


def test_a_new_config_file_nobody_has_thought_about_fails_the_check(mirror):
    # The rule that makes this a checker rather than a list. Adding a store and
    # forgetting the question is exactly how the ten guarded files below got
    # into the state this row found them in.
    target = mirror / "src" / "settings.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\n\ndef _p3_16_probe(data):\n"
          "    from core.atomic_io import atomic_write_json\n"
          "    atomic_write_json(A_FILE_NOBODY_CLASSIFIED, data)\n",
        encoding="utf-8",
    )
    code, out = _run(_load_checker(mirror))
    assert code == 1
    assert "nothing has classified" in out


def test_a_classification_with_no_write_behind_it_fails_the_check(mirror):
    # A map that outlives the code it describes reads as coverage and is not.
    # `STORES` is data on the loaded module, so this one needs no source at all.
    module = _load_checker(mirror)
    module.STORES[("src/settings.py", "A_FILE_THAT_WENT_AWAY")] = (
        module.GUARDED, "left behind")
    code, out = _run(module)
    assert code == 1
    assert "no write there any more" in out


def test_the_checker_fails_on_a_guarded_store_that_drops_its_guard(mirror):
    # A checker nobody has watched fail is a checker that might not check.
    target = mirror / "src" / "settings.py"
    original = target.read_text(encoding="utf-8")
    hobbled = original.replace(
        "atomic_write_json(SETTINGS_FILE, settings, indent=2, preserve_unreadable=True)",
        "atomic_write_json(SETTINGS_FILE, settings, indent=2)",
        1,
    )
    assert hobbled != original, "the real write no longer looks like this"
    target.write_text(hobbled, encoding="utf-8")
    code, out = _run(_load_checker(mirror))
    assert code == 1
    assert "does not pass preserve_unreadable=True" in out


def test_the_repository_copy_of_settings_still_carries_the_guard():
    """The assertion the three tests above used to make by accident, now made
    on purpose: whatever they do to a mirror, the shipped file is guarded."""
    source = (_REPO / "src" / "settings.py").read_text(encoding="utf-8")
    assert ("atomic_write_json(SETTINGS_FILE, settings, indent=2, "
            "preserve_unreadable=True)") in source
