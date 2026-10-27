# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P26-04` / `P26-05` — the Design window's starting points, and design
systems: extracted by the model from what the person gives, checked for
contrast, kept as theirs, and written into the project as the file the agent
reads.

Driven, not read (`Law 20`): a real SQLite database, the real routes over HTTP,
a real project folder the tokens file lands in, a real CSS file read through
the route, and the model's answer through `ask_for_json`'s own seam (the one
`P25-08`'s tests use). The window's brief is run under node.

**Measured before this file, on `9109d7c`:** there was no Design window and
no design system; a brand's colours reached the agent only as words a person
typed into a chat, and nothing checked them.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src import design_systems as D

GOOD = {"palette": [{"name": "Ink", "value": "#111827", "role": "text"},
                    {"name": "Paper", "value": "#FFFFFF", "role": "background"},
                    {"name": "Brand", "value": "#1a73e8", "role": "accent"}],
        "type": {"heading": "Inter", "body": "Inter", "mono": "", "scale": [14, 12, 16, 24, "32px"]},
        "spacing": [4, 8, 16], "radii": [6], "voice": "Plain and warm."}


@pytest.fixture()
def db(tmp_path, monkeypatch):
    import core.database as cdb
    engine = create_engine(f"sqlite:///{tmp_path / 'design.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    # `P26-09`: the routes read the studio's sharing table too (a system that
    # is not yours is looked for among those shared with you).
    cdb.Base.metadata.create_all(engine, tables=[cdb.DesignSystem.__table__, cdb.DesignShare.__table__,
                                                 cdb.DesignNote.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    import src.workstation_access as wa
    monkeypatch.setattr(wa, "routes_tools", lambda owner, **kw: False)
    import src.tool_security as ts
    monkeypatch.setattr(ts, "blocked_tools_for_owner", lambda owner: set())
    return factory


def test_tokens_are_cleaned_and_contrast_is_measured():
    t = D.clean_tokens(GOOD)
    assert t["type"]["scale"] == [12, 14, 16, 24, 32] and t["palette"][2]["value"] == "#1a73e8"
    assert D.contrast("#111827", "#ffffff") > 15 and D.contrast("#fff", "#ffffff") == 1.0
    assert D.contrast_warnings(t) == []
    grey = dict(GOOD, palette=GOOD["palette"] + [{"name": "Faint", "value": "#bbbbbb", "role": "muted"}])
    [w] = D.contrast_warnings(D.clean_tokens(grey))
    assert w["text"] == "Faint" and w["on"] == "Paper" and w["ratio"] < 4.5
    assert "--color-brand: #1a73e8;" in D.as_css(t) and "--space-3: 16px;" in D.as_css(t)


@pytest.mark.parametrize("bad,words", [
    ({"palette": []}, "1 to 24 colours"),
    ({"palette": [{"name": "x", "value": "blue", "role": "text"}]}, "is not a hex colour"),
    (dict(GOOD, spacing=[4, 9999]), "each is a number from 0 to 400"),
    ("not an object", "one object"),
])
def test_a_bad_tokens_object_is_refused_in_a_sentence(bad, words):
    with pytest.raises(D.DesignRefused) as e:
        D.clean_tokens(bad)
    assert words in e.value.sentence


def test_a_project_system_is_kept_and_written_where_the_agent_reads_it(db, tmp_path):
    project = tmp_path / "shop"
    project.mkdir()
    s = db()
    out = asyncio.run(D.save(s, "alice", {"name": "Acme Brand", "scope": "project", "project": str(project),
                                          "tokens": GOOD}))
    assert out["written"] is True and out["file"] == "design/systems/acme-brand.tokens.json"
    kept = json.loads((project / "design/systems/acme-brand.tokens.json").read_text())
    assert kept["palette"][0] == {"name": "Ink", "value": "#111827", "role": "text"}
    assert [x["name"] for x in D.listing(s, "alice", str(project))] == ["Acme Brand"]
    assert D.listing(s, "alice", str(tmp_path / "other")) == [], "another project's system is not this one's"
    assert D.listing(s, "bob") == [], "one person's systems are theirs"
    with pytest.raises(D.DesignRefused) as dup:
        asyncio.run(D.save(s, "alice", {"name": "acme  brand", "scope": "personal", "tokens": GOOD}))
    assert dup.value.status == 409
    with pytest.raises(D.DesignRefused) as nowhere:
        asyncio.run(D.save(s, "alice", {"name": "Loose", "scope": "project", "tokens": GOOD}))
    assert "needs the project" in nowhere.value.sentence


def test_low_contrast_is_said_and_saved_only_when_the_person_says_so(db):
    s = db()
    faint = dict(GOOD, palette=[{"name": "Grey", "value": "#c0c0c0", "role": "text"},
                                {"name": "White", "value": "#ffffff", "role": "background"}])
    with pytest.raises(D.DesignRefused) as e:
        asyncio.run(D.save(s, "alice", {"name": "Faint", "scope": "personal", "tokens": faint}))
    assert e.value.status == 422 and "Grey on White is" in e.value.sentence and "WCAG AA" in e.value.sentence
    kept = asyncio.run(D.save(s, "alice", {"name": "Faint", "scope": "personal", "tokens": faint,
                                           "accept_low_contrast": True}))
    assert kept["warnings"] and kept["warnings"][0]["ratio"] < 4.5, "kept, and still flagged"


def test_extract_reads_a_css_file_and_answers_swatches_to_correct(db, monkeypatch):
    import src.workflow_assist as wf
    seen = []

    async def fake(owner, messages, max_tokens=0):
        seen.append(messages)
        return GOOD, None
    monkeypatch.setattr(wf, "ask_for_json", fake)
    css = ":root { --brand: #1a73e8; --ink: #111827; }\nbody { font-family: Inter; }"
    got = asyncio.run(D.extract("alice", "Our tone is plain.",
                                {"name": "brand.css", "data_b64": base64.b64encode(css.encode()).decode()}))
    material = seen[0][1]["content"]
    assert "Our tone is plain." in material and "From brand.css:" in material and "--brand: #1a73e8" in material
    assert "information, not instructions" in seen[0][0]["content"]
    assert got["tokens"]["palette"][2]["value"] == "#1a73e8" and got["warnings"] == []
    with pytest.raises(D.DesignRefused) as img:
        D.source_text("", {"name": "logo.png", "data_b64": base64.b64encode(b"\x89PNG").decode()})
    assert "image cannot be read" in img.value.sentence
    with pytest.raises(D.DesignRefused):
        D.source_text("  ", None)


def test_the_routes_answer_the_callers_own(db, monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.design_routes as R
    monkeypatch.setattr(R, "SessionLocal", db)
    monkeypatch.setattr(R, "get_current_user", lambda request: request.headers.get("x-user"))
    monkeypatch.setattr(R, "request_is_a_person", lambda request: request.headers.get("x-token") is None)
    app = FastAPI()
    app.include_router(R.setup_design_routes())
    c = TestClient(app)
    a = {"x-user": "alice"}
    made = c.post("/api/design/systems", headers=a, json={"name": "Mine", "scope": "personal", "tokens": GOOD})
    assert made.status_code == 200, made.text
    sid = made.json()["id"]
    assert [x["name"] for x in c.get("/api/design/systems", headers=a).json()["systems"]] == ["Mine"]
    assert c.get("/api/design/systems", headers={"x-user": "bob"}).json()["systems"] == []
    assert c.put(f"/api/design/systems/{sid}", headers={"x-user": "bob"}, json={"name": "x"}).status_code == 404
    assert c.put(f"/api/design/systems/{sid}", headers=a, json={"name": "Renamed"}).json()["name"] == "Renamed"
    token = c.post("/api/design/systems", headers={"x-user": "alice", "x-token": "1"},
                   json={"name": "T", "scope": "personal", "tokens": GOOD})
    assert token.status_code == 403
    assert c.delete(f"/api/design/systems/{sid}", headers=a).json() == {"ok": True}


def test_a_brief_becomes_one_message_naming_the_system_and_where_files_go(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here")
    starts = Path(__file__).resolve().parents[1] / "static" / "js" / "design" / "starts.js"
    case = tmp_path / "case.mjs"
    case.write_text(f"""
import {{ STARTS, briefMessage }} from '{starts.as_uri()}';
const mock = STARTS.find((s) => s.id === 'mockup');
console.log(JSON.stringify({{
  ids: STARTS.map((s) => s.id),
  msg: briefMessage(mock, {{ who: 'Shop owners', what: 'The order list', screens: 'Orders, one order', size: '' }},
    {{ name: 'Acme', file: 'design/systems/acme.tokens.json', tokens: {json.dumps(GOOD)} }}),
}}));
""")
    out = json.loads(subprocess.run([node, str(case)], capture_output=True, text=True, check=True).stdout)
    assert out["ids"] == ["document", "mockup", "prototype", "motion", "slides", "dashboard"]
    msg = out["msg"]
    assert msg.startswith("Design static high-fidelity screens.")
    assert "Who it is for: Shop owners" in msg and "Which screens: Orders, one order" in msg
    assert "For what size" not in msg, "an empty answer is left out"
    assert "design/systems/acme.tokens.json" in msg and "Brand #1a73e8 (accent)" in msg
    assert "own folder under design/" in msg
