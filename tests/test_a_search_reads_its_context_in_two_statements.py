# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-13`): `/api/search` reads the messages around its hits in
two statements, not four per hit.

Measured by the perf audit on `9560d50`, in process on 8,000 messages:
`?q=reminders&limit=20` was 84 statements, 82 of them `SELECT chat_messages…` —
`_context_for_message` asked twice per hit (before, after), and the FTS and LIKE
paths both asked for every hit of their own, including those the merge then
dropped. Now the hits are found without context and the merged list gets it
from one window query and one read.

The context must be exactly what it was: the nearest `count` user/assistant
messages strictly before and strictly after the hit's timestamp. The oracle
below is the old per-hit rule, run against the same database. Out of process,
because the FTS index is built by `init_db` on a file database.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

_PROBE = textwrap.dedent(
    """
    import json, uuid
    from datetime import datetime, timedelta
    from sqlalchemy import event
    import core.database as cdb
    from core.database import SessionLocal, Session as S, ChatMessage as M, engine
    from src.session_search import search_session_messages, SEARCH_ROLES

    db = SessionLocal()
    base = datetime(2026, 1, 1)
    for s in range(6):
        sid = f"s{s}"
        db.add(S(id=sid, owner="ann", name=f"chat {s}", endpoint_url="x", model="m"))
        for i in range(60):
            role = ("user", "assistant", "system")[i % 3]
            words = "remember the reminders" if i % 7 == 3 else f"line {i}"
            # Neighbours that share a hit's timestamp, one ordered after the
            # hit (25 with hit 24) and one before it (30 with hit 31).
            minute = {25: 24, 30: 31}.get(i, i)
            t = base + timedelta(minutes=s * 100 + minute)
            db.add(M(id=f"{sid}-{i:02d}", session_id=sid, role=role, content=words, timestamp=t))
    db.commit()

    statements = []
    event.listen(engine, "before_cursor_execute", lambda *a, **k: statements.append(a[2]))

    def oracle(db, msg_id, count):
        msg = db.query(M).filter(M.id == msg_id).first()
        if count <= 0 or not msg.timestamp:
            return [], []
        before = (db.query(M).filter(M.session_id == msg.session_id, M.role.in_(SEARCH_ROLES),
                                     M.timestamp < msg.timestamp)
                  .order_by(M.timestamp.desc()).limit(count).all())
        after = (db.query(M).filter(M.session_id == msg.session_id, M.role.in_(SEARCH_ROLES),
                                    M.timestamp > msg.timestamp)
                 .order_by(M.timestamp.asc()).limit(count).all())
        return [m.id for m in reversed(before)], [m.id for m in after]

    out = {}
    for count in (1, 3):
        statements.clear()
        results = search_session_messages("reminders", limit=20, owner="ann", context_messages=count, db=db)
        out[f"statements_{count}"] = len(statements)
        out[f"chat_message_selects_{count}"] = sum(1 for s in statements if "chat_messages" in s)
        out[f"hits_{count}"] = len(results)
        mismatches = []
        for r in results:
            want = oracle(db, r.message_id, count)
            got = ([c["message_id"] for c in r.context_before], [c["message_id"] for c in r.context_after])
            if got != want:
                mismatches.append([r.message_id, got, want])
        out[f"mismatches_{count}"] = mismatches
    statements.clear()
    plain = search_session_messages("reminders", limit=20, owner="ann", context_messages=0, db=db)
    out["no_context_statements"] = len(statements)
    out["no_context_empty"] = all(not r.context_before and not r.context_after for r in plain)
    # Where SQLite has no FTS5 the LIKE path answers alone, with the same context.
    db.execute(cdb.text("DROP TABLE chat_messages_fts"))
    db.commit()
    statements.clear()
    results = search_session_messages("reminders", limit=20, owner="ann", context_messages=2, db=db)
    out["like_only_statements"] = len(statements)
    out["like_only_hits"] = len(results)
    out["like_only_mismatches"] = [r.message_id for r in results
        if ([c["message_id"] for c in r.context_before], [c["message_id"] for c in r.context_after])
        != oracle(db, r.message_id, 2)]
    print("RESULT " + json.dumps(out))
    """
)


def _run(tmp_path):
    env = os.environ.copy()
    env.update({"DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}", "PANTHEON_DATA_DIR": str(tmp_path),
                "PYTHONPATH": str(_REPO), "PYTHON_DOTENV_DISABLED": "1"})
    done = subprocess.run([sys.executable, "-c", _PROBE], cwd=_REPO, env=env,
                          capture_output=True, text=True, timeout=240)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, done.stderr[-4000:]
    return json.loads(line[len("RESULT "):])


def test_a_search_reads_its_context_in_two_statements_and_reads_the_same_context(tmp_path):
    out = _run(tmp_path)
    for count in (1, 3):
        assert out[f"hits_{count}"] == 20, out
        assert out[f"mismatches_{count}"] == [], out[f"mismatches_{count}"]
        # FTS check + FTS hits + their rows + LIKE hits + context window + context rows.
        assert out[f"statements_{count}"] <= 7, out
        assert out[f"chat_message_selects_{count}"] <= 6, out
    assert out["no_context_empty"] is True
    assert out["no_context_statements"] <= 5
    assert out["like_only_hits"] == 20
    assert out["like_only_mismatches"] == []
    # FTS check + LIKE hits + context window + context rows.
    assert out["like_only_statements"] <= 4, out
