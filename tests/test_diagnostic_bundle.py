# SPDX-License-Identifier: AGPL-3.0-or-later
"""The bug report is redacted, readable, and goes nowhere on its own.

`P16-14`. Two claims are being tested, and they pull in opposite directions:

  1. Nothing identifying survives — username, endpoints, mail addresses, LAN
     addresses, credentials.
  2. Enough survives to be worth reading. A bundle redacted into uselessness is
     the same as no bundle, and it fails silently, because it still looks like
     a bug report.

Most redaction tests only check (1), which is why over-redaction ships. Several
below check (2) on purpose: model names, short SHAs and loopback must come out
the other side intact.
"""
import getpass
import json
import re
from pathlib import Path

import pytest

from src.diagnostic_bundle import (
    SHOW_VALUE, build_bundle, collect_settings, redact, render_markdown,
)

ROOT = Path(__file__).resolve().parent.parent


# --- 1. nothing identifying survives ---------------------------------------

@pytest.mark.parametrize("raw,gone", [
    ("/home/josep/Projects/odysseus/app.py", "josep"),
    (r"C:\Users\josep\Projects\odysseus", "josep"),
    ("mail from someone@example.com failed", "someone@example.com"),
    ("peer 192.168.1.42 unreachable", "192.168.1.42"),
    ("https://user:hunter2@ollama.lan:11434/v1?api_key=abc", "hunter2"),
    ("https://api.github.com/x?token=ghp_ABCDEFGHIJKLMNOP1234", "ghp_ABCDEFGHIJKLMNOP1234"),
    ("OPENAI_API_KEY=sk-proj-AAAABBBBCCCCDDDDEEEEFFFF", "sk-proj-AAAABBBBCCCCDDDDEEEEFFFF"),
    ("api_key=abc123def456", "abc123def456"),
    ("session 9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d6c", "9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d6c"),
])
def test_redact_removes(raw, gone):
    assert gone not in redact(raw)


def test_the_running_users_name_is_removed_even_outside_a_path():
    """A username turns up in hostnames and 'logged in as' lines too."""
    user = getpass.getuser()
    if len(user) <= 2:
        pytest.skip("username too short to match on safely")
    assert user not in redact(f"workstation {user}-desktop reported an error")


def test_credential_inside_a_url_path_still_goes():
    """redact_url keeps the path, so a token in the path needs the next pass."""
    assert "ghp_" not in redact("https://host/callback/ghp_ABCDEFGHIJKLMNOP1234/done")


# --- 2. enough survives to be useful ---------------------------------------

def test_useful_things_survive():
    """The failure mode nobody tests for. A bundle redacted to mush is not safe,
    it is useless, and it fails while still looking like a bug report."""
    keep = "loaded model qwen2.5-coder-7b-instruct-q4_K_M at commit 4f973fa in 812ms"
    out = redact(keep)
    assert "qwen2.5-coder-7b-instruct-q4_K_M" in out
    assert "4f973fa" in out
    assert "812ms" in out


def test_loopback_is_not_redacted():
    """Almost every report about a local model server names 127.0.0.1.
    Redacting it costs the report and buys no privacy."""
    out = redact("bound 127.0.0.1:8000, peer 10.1.2.3")
    assert "127.0.0.1" in out
    assert "10.1.2.3" not in out


def test_traceback_shape_survives_redaction():
    trace = ('Traceback (most recent call last):\n'
             '  File "/home/josep/pantheon/src/llm_core.py", line 412, in stream\n'
             '    raise ConnectionError(msg)\n'
             'ConnectionError: endpoint refused')
    out = redact(trace)
    assert "llm_core.py" in out and "line 412" in out
    assert "ConnectionError: endpoint refused" in out
    assert "josep" not in out


# --- 3. settings are allowlisted, not denylisted ---------------------------

def test_settings_show_values_only_for_the_allowlist():
    from src.settings import DEFAULT_SETTINGS
    collected = collect_settings()
    shapes = {"not set", "set", "number", "empty", "on", "off"}
    for key, value in collected.items():
        if key in SHOW_VALUE or key.startswith("_"):
            continue
        assert isinstance(value, str), f"{key} leaked a raw {type(value).__name__}"
        assert value in shapes or re.fullmatch(r"\d+ (item|key)\(s\)", value), \
            f"{key} reported {value!r}, which is a value and not a shape"


def test_no_credential_setting_value_appears_anywhere_in_the_bundle(monkeypatch):
    """The end-to-end version. Set every credential-ish setting to a marker and
    assert the marker is nowhere in the rendered report."""
    from src import settings as settings_mod
    marker = "ZZTOPSECRETVALUE"
    creds = [k for k in settings_mod.DEFAULT_SETTINGS
             if re.search(r"key|token|secret|password", k, re.I)
             and isinstance(settings_mod.DEFAULT_SETTINGS[k], str)]
    assert creds, "no credential-shaped settings found — the test would be vacuous"

    real = settings_mod.get_setting

    def fake(key, default=None):
        return marker if key in creds else real(key, default)

    monkeypatch.setattr("src.settings.get_setting", fake)
    text = render_markdown(build_bundle(note="x", log_limit=5))
    assert marker not in text


def test_a_new_secret_named_nothing_like_a_secret_is_still_hidden(monkeypatch):
    """The reason this is an allowlist. A denylist keyed on `key|token|secret`
    sails straight past a credential someone calls `openrouter_thing`."""
    from src import settings as settings_mod
    real = settings_mod.get_setting
    monkeypatch.setattr("src.settings.get_setting",
                        lambda k, d=None: "MYSECRETBEARER" if k == "search_provider_extra"
                        else real(k, d))
    monkeypatch.setitem(settings_mod.DEFAULT_SETTINGS, "search_provider_extra", "")
    assert "search_provider_extra" not in SHOW_VALUE
    assert "MYSECRETBEARER" not in json.dumps(collect_settings())


def test_the_allowlist_is_not_empty_and_does_not_contain_credentials():
    assert len(SHOW_VALUE) > 5
    for key in SHOW_VALUE:
        assert not re.search(r"api_key|_token$|secret|password", key, re.I), key


# --- 4. it is assembled, never transmitted ---------------------------------

def test_the_bundle_module_makes_no_outbound_call():
    """`build_bundle` reads local state. If an upload ever appears here, the
    whole design has quietly become telemetry."""
    src = (ROOT / "src" / "diagnostic_bundle.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    for banned in ("httpx", "requests", "urllib.request", "aiohttp", "socket."):
        assert banned not in code, f"{banned} in a module that must only read local state"


def test_the_route_does_not_post_the_bundle_anywhere():
    src = (ROOT / "routes" / "diagnostics_routes.py").read_text(encoding="utf-8")
    i = src.index("/api/diagnostics/bundle")
    block = src[i:src.index("/api/diagnostics/logs", i)]
    for banned in ("httpx", "post(", "requests.", "urlopen"):
        assert banned not in block, f"{banned} in the bundle route"


def test_frontend_never_sends_the_report():
    """The panel fetches FROM this origin and copies to the clipboard. The
    issue-tracker control is an <a>, so navigating is the person's click."""
    js = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    i = js.index("function setupBugReport()")
    block = js[i:js.index("async function loadLogs", i)]
    assert "method: 'POST'" not in block and 'method: "POST"' not in block
    fetches = re.findall(r"fetch\(\s*['\"]([^'\"]+)", block) + \
        re.findall(r"fetch\(\s*\n?\s*'(/[^']+)", block)
    assert fetches, "no fetch found — the test would be vacuous"
    for url in fetches:
        assert url.startswith("/api/"), f"the panel fetches {url}"


def test_issue_tracker_default_is_empty_so_the_env_layer_is_reachable():
    """A truthy default here would make PANTHEON_ISSUE_TRACKER_URL dead code —
    `get_setting` merges DEFAULT_SETTINGS on every read (`H06`, `B20`)."""
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["issue_tracker_url"] == ""
    src = (ROOT / "routes" / "diagnostics_routes.py").read_text(encoding="utf-8")
    assert "PANTHEON_ISSUE_TRACKER_URL" in src


def test_issue_tracker_url_is_registered_in_all_five_places():
    assert "issue_tracker_url" in (ROOT / "src" / "settings.py").read_text(encoding="utf-8")
    assert "PANTHEON_ISSUE_TRACKER_URL" in (ROOT / ".env.example").read_text(encoding="utf-8")
    for f in ("docker-compose.yml", "docker-compose.gpu-amd.yml", "docker-compose.gpu-nvidia.yml"):
        assert "PANTHEON_ISSUE_TRACKER_URL" in (ROOT / f).read_text(encoding="utf-8"), f


# --- 5. the report is worth reading ----------------------------------------

def test_rendered_report_has_the_sections_a_maintainer_opens_first():
    text = render_markdown(build_bundle(note="it broke", log_limit=5))
    for heading in ("What happened", "Environment", "Self-checks", "Settings", "Recent logs"):
        assert f"### {heading}" in text or heading in text, heading
    assert "it broke" in text
    # The disclosure is part of the deliverable: the person is being asked to
    # trust that reading it is enough, and the report should say so on its face.
    assert "Nothing was sent anywhere" in text


def test_the_users_own_note_is_redacted_too():
    """They will paste a path into it without thinking. A redactor that trusts
    one field is a redactor with a hole in it."""
    text = render_markdown(build_bundle(note="broke at /home/josep/thing.py", log_limit=5))
    assert "josep" not in text


# --- P4-27: a receipt you can hand to someone ------------------------------

def _seeded_run(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import core.database as core_db
    from core.database import Base
    from src import events as ev

    engine = create_engine(f"sqlite:///{tmp_path}/r.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal",
                        sessionmaker(autocommit=False, autoflush=False, bind=engine))
    monkeypatch.setattr(ev, "_last_prune", 0.0)
    ev._turn_started.set(None)
    ev._run_id.set(None)
    ev.mark_turn_start()
    rid = ev.current_run_id()
    ev.record_run_config(sampling={"temperature": 0.7},
                         tools=[{"function": {"name": "shell"}}],
                         skills=[{"name": "deploy", "confidence": 0.8}],
                         session_id="s1")
    ev.record_llm_round("s1", {"input_tokens": 900, "output_tokens": 120,
                               "model": "qwen",
                               "endpoint_label": "http://user:hunter2@llm.lan:8000/v1"})
    ev.record_event("tool_call", name="shell", outcome="error")
    return rid


def test_the_receipt_section_carries_what_a_reader_needs(tmp_path, monkeypatch):
    """"It did something weird" becomes a report someone can act on: the model,
    the sampling, the tools it was offered, the skills it was following."""
    rid = _seeded_run(tmp_path, monkeypatch)
    text = render_markdown(build_bundle(note="x", log_limit=0, run_id=rid))
    assert "### The run" in text
    for expected in ("qwen", "temperature=0.7", "shell", "deploy (0.8)", "1 failed"):
        assert expected in text, f"{expected!r} missing from the receipt section"


def test_the_run_id_survives_redaction(tmp_path, monkeypatch):
    """A run_id is 32 hex characters — exactly the shape the opaque-string rule
    catches. The first version redacted the one field that makes a receipt
    usable as a bug report, producing a document whose subject was <redacted>.

    Over-redaction is not the safe failure: it leaves the thing looking correct
    and worth nothing."""
    rid = _seeded_run(tmp_path, monkeypatch)
    text = render_markdown(build_bundle(log_limit=0, run_id=rid))
    assert rid in text, "the receipt cannot be referred to"


def test_a_path_in_a_skill_name_is_stripped(tmp_path, monkeypatch):
    """The other half: exempting identifiers must not exempt everything.

    Asserted on a SKILL NAME rather than an endpoint label, and the difference
    matters. Endpoint labels are already sanitised at write by
    `events._safe_label`, so a test using one passes with this module's
    redaction removed entirely — it proves the earlier layer, not this one.
    A skill name is operator-supplied free text that nothing else touches.
    """
    from src import events as ev
    rid = _seeded_run(tmp_path, monkeypatch)
    ev.record_run_config(skills=[{"name": "/home/josep/secret-playbook",
                                  "confidence": 0.5}], session_id="s1")
    text = render_markdown(build_bundle(log_limit=0, run_id=rid))
    assert "/home/josep" not in text, "operator free text reached the export unredacted"
    assert "secret-playbook" in text, "over-redacted — the name is the useful part"


def test_a_credential_in_an_endpoint_label_never_reaches_the_export(tmp_path, monkeypatch):
    """Belt and braces, and honest about which layer does the work: the label
    is stripped at write (`events._safe_label`), so this holds even if the
    export's own redaction changes."""
    rid = _seeded_run(tmp_path, monkeypatch)
    text = render_markdown(build_bundle(log_limit=0, run_id=rid))
    assert "hunter2" not in text
    assert "llm.lan" in text, "over-redacted — the host is the useful part"


def test_no_receipt_section_when_none_was_asked_for(tmp_path, monkeypatch):
    _seeded_run(tmp_path, monkeypatch)
    text = render_markdown(build_bundle(note="x", log_limit=0))
    assert "### The run" not in text


def test_an_unknown_run_does_not_break_the_bundle(tmp_path, monkeypatch):
    _seeded_run(tmp_path, monkeypatch)
    text = render_markdown(build_bundle(note="x", log_limit=0, run_id="nope"))
    assert "### The run" in text
    assert "Environment" in text


def test_the_export_reuses_this_renderer_rather_than_a_second_one():
    """`Law 14`. "Make something a person can hand over, with nothing of theirs
    in it" already had an owner."""
    src = (ROOT / "routes" / "diagnostics_routes.py").read_text(encoding="utf-8")
    i = src.index("/api/diagnostics/receipt/{run_id}/export")
    block = src[i:i + 1400]
    assert "render_markdown" in block and "build_bundle" in block
    assert "text/markdown" in block


def test_bundle_survives_a_missing_log_file(tmp_path, monkeypatch):
    monkeypatch.setattr("core.constants.DATA_DIR", str(tmp_path))
    bundle = build_bundle(log_limit=10)
    assert isinstance(bundle["recent_logs"], list)
    assert render_markdown(bundle)
