#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P17-08` — what the agent was offered, what it reached for, and what it could not do.

`P17-06` asked for a gap analysis *"derived from what the agent is actually
asked to do rather than from imagination"*. `P17-07` built the instrumentation.
This reads it back.

**THIS IS A SCRIPT AND NOT A DOCUMENT, BECAUSE A DOCUMENT IS A MEASUREMENT
NOBODY CAN REPEAT.** The corpus lives on one running deployment; anybody else
who wants these numbers has to produce their own, and a markdown file of
figures from a database they cannot see is exactly the *trust us* this fork's
ledger refuses. Run it against your own and you get your own answer.

**THE THREE QUESTIONS, AND WHY THE THIRD IS THE ONE WORTH ASKING.**

  1. *What did the agent try and fail at?* `tool_call` events with a non-ok
     outcome, and `capability_gap` events — the classifier that notices the
     agent saying it has no tool for something.
  2. *What was it never offered?* Nothing here can answer that; it is the gap
     the data cannot see, and the section below says so rather than leaving a
     reader to assume the list is complete.
  3. **What was it offered and never once picked?** This is the one the
     instrumentation is uniquely good at, because `run_config.detail.tools`
     records the *offer* even on a turn where nothing was called. A tool that
     is never picked is either unnecessary, undiscoverable, or badly described
     — three different problems that look identical from the outside, and all
     three are invisible without this column.

**READ-ONLY, AND IT WILL NOT OPEN A LIVE DATABASE.** Point it at a snapshot.
Taking one is `sqlite3.Connection.backup()` from a `mode=ro` source, which is
atomic and leaves a running writer alone; opening the live file read-write to
run a `SELECT` is how an analysis script corrupts a WAL it did not create.

**NO MESSAGE CONTENT IS PRINTED.** Not a privacy gesture — a correctness one.
Every number here is a count or a name, so the report can be committed and
argued with, and nothing in it depends on a human reading somebody's mail.
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys

# The classifier's own vocabulary, from `src/teacher_escalation.py`. Named here
# so a reader of the report knows what "capability gap" was actually detected
# by, rather than taking the phrase on trust.
GAP_KINDS = {
    "reply_give_up": "the agent said, in the reply, that it could not do it",
    "tool_error": "a tool returned an error the classifier recognises",
}


def _open(path: str) -> sqlite3.Connection:
    """Read-only, and loudly so."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _json(raw):
    try:
        value = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def offered(conn):
    """Tool name -> how many runs offered it, plus how many runs recorded an offer.

    Keyed on the **name**, not the whole fingerprint. `detail.tools` entries are
    `{"name", "sha"}` and the sha moves whenever a tool's schema is edited, so
    counting the pair inflates the distinct total and splits one tool's history
    in half at the moment somebody changes its description.

    **One row per run, the last one, which is what `events.receipt()` does.** A
    run can write a second `run_config` when a later call carries a tool list
    the first did not (`P17-08`), so counting rows would count that run twice —
    once with no tools and once with them — and inflate the denominator every
    figure below is a fraction of.

    `runs_with_tools` is returned separately and it is the honest denominator
    for *offered and never picked*: a run that recorded no tool list is not
    evidence that nothing was offered, it is evidence of nothing at all.
    """
    latest = {}
    for row in conn.execute(
        "select run_id, ts, detail from events where kind='run_config' "
        "order by ts asc, id asc"
    ):
        latest[row["run_id"]] = _json(row["detail"])
    counts = collections.Counter()
    with_tools = 0
    for detail in latest.values():
        tools = detail.get("tools")
        if not tools:
            continue
        with_tools += 1
        for tool in tools:
            name = tool.get("name") if isinstance(tool, dict) else tool
            if isinstance(name, str) and name:
                counts[name] += 1
    return counts, len(latest), with_tools


def called(conn):
    """Tool name -> (calls, failures), from both places that record a call.

    Two sources on purpose. `events` rows carry an outcome and survive session
    deletion; `chat_messages.metadata.tool_events` carries the arguments and
    dies with its session. **They disagree**, and the disagreement is a finding
    rather than noise — a tool present in one and absent from the other means a
    call path that writes only one of them.
    """
    ev = collections.Counter()
    ev_fail = collections.Counter()
    for row in conn.execute(
        "select name, outcome, count(*) n from events "
        "where kind='tool_call' group by name, outcome"
    ):
        name = row["name"] or "?"
        ev[name] += row["n"]
        if (row["outcome"] or "") not in ("ok", "success"):
            ev_fail[name] += row["n"]

    md = collections.Counter()
    md_fail = collections.Counter()
    for row in conn.execute("select metadata from chat_messages where role='assistant'"):
        for event in _json(row["metadata"]).get("tool_events") or []:
            if not isinstance(event, dict):
                continue
            name = event.get("tool") or event.get("name") or "?"
            md[name] += 1
            if event.get("error") or event.get("exit_code") not in (0, None):
                md_fail[name] += 1
    return ev, ev_fail, md, md_fail


def called_without_being_offered(conn):
    """Calls whose tool was not in that run's recorded offer.

    **The sharpest column in this report**, and the one that says the other
    columns are incomplete. A tool the model cannot see a schema for should be
    impossible to call, so every row here is a call that arrived through some
    channel `run_config` does not describe. On the owner's deployment that is
    17 of 19 `create_document` calls, against 0 for every other tool — the
    fenced tool channel, which is prose in the system prompt and leaves no
    offer fingerprint anywhere.

    Why it matters more than the ranked list above: *offered and never picked*
    is only a statement about the schema channel. A tool reachable another way
    is neither offered nor missing, and it will sit in neither column.
    """
    latest = {}
    for row in conn.execute(
        "select run_id, detail from events where kind='run_config' "
        "order by ts asc, id asc"
    ):
        names = set()
        for tool in _json(row["detail"]).get("tools") or []:
            name = tool.get("name") if isinstance(tool, dict) else tool
            if isinstance(name, str):
                names.add(name)
        latest[row["run_id"]] = names

    out = collections.Counter()
    total = collections.Counter()
    no_config = collections.Counter()
    for row in conn.execute("select run_id, name from events where kind='tool_call'"):
        name = row["name"] or "?"
        total[name] += 1
        offer = latest.get(row["run_id"])
        if offer is None:
            no_config[name] += 1
        elif name not in offer:
            out[name] += 1
    return out, total, no_config


def gaps(conn):
    """`capability_gap` rows, grouped by what matched.

    A row whose `detail` is empty is reported as such and not quietly counted:
    the point of the event is to name what was asked, and one that names
    nothing is a gap in the instrumentation rather than a gap in the tools.
    """
    rows = []
    for row in conn.execute(
        "select ts, name, outcome, detail from events "
        "where kind='capability_gap' order by ts"
    ):
        detail = _json(row["detail"])
        rows.append({
            "ts": row["ts"],
            "kind": row["name"],
            "pattern": detail.get("pattern", ""),
            "empty": not detail,
        })
    return rows


def failures(conn):
    """Failed `tool_call` rows, and whether each says why."""
    out = []
    for row in conn.execute(
        "select ts, name, outcome, detail from events where kind='tool_call' "
        "and outcome not in ('ok','success') order by ts"
    ):
        out.append({
            "ts": row["ts"],
            "tool": row["name"],
            "outcome": row["outcome"],
            "detail": (row["detail"] or "").strip(),
        })
    return out


def corpus(conn):
    def one(sql, default=0):
        try:
            return conn.execute(sql).fetchone()[0]
        except sqlite3.Error:
            return default

    return {
        "sessions": one("select count(*) from sessions"),
        "sessions_with_messages": one("select count(*) from sessions where message_count > 0"),
        "user_messages": one("select count(*) from chat_messages where role='user'"),
        "assistant_messages": one("select count(*) from chat_messages where role='assistant'"),
        "events": one("select count(*) from events"),
        "runs": one("select count(*) from events where kind='run_config'"),
        "first_event": one("select min(ts) from events", ""),
        "last_event": one("select max(ts) from events", ""),
    }


def report(path: str) -> int:
    conn = _open(path)
    stats = corpus(conn)
    offer_counts, runs, runs_with_tools = offered(conn)
    ev, ev_fail, md, md_fail = called(conn)
    ever_called = set(ev) | set(md)

    print("## Corpus")
    for key in ("sessions", "sessions_with_messages", "user_messages",
                "assistant_messages", "events", "runs"):
        print(f"  {key:26} {stats[key]}")
    print(f"  window                     {stats['first_event']} .. {stats['last_event']}")
    print()
    print("  A corpus this size is a signal, not a conclusion. Every figure below")
    print("  is a count from these rows and nothing is extrapolated from them.")
    print()

    print("## Offered and never once picked")
    print(f"  {runs} runs recorded a config; {runs_with_tools} of them recorded a"
          f" tool list.")
    if runs_with_tools < runs:
        print(f"  **{runs - runs_with_tools} runs recorded no tool list at all.**"
              " Read the caveat below before")
        print("  quoting anything in this section.")
    print(f"  {len(offer_counts)} distinct tools offered across those"
          f" {runs_with_tools} runs; {len(ever_called)} were ever called.")
    never = [(n, c) for n, c in offer_counts.most_common() if n not in ever_called]
    print(f"  {len(never)} offered and never picked. The ten offered most often:")
    for name, count in never[:10]:
        print(f"   {name:44} offered {count:>3}  called 0")
    print()
    print("  Unnecessary, undiscoverable, or badly described — three different")
    print("  problems that look identical from outside. This column cannot tell")
    print("  them apart; it can only say which tools to ask the question about.")
    print()
    if runs_with_tools < runs:
        print("  CAVEAT, and it is the reason this script exists rather than a")
        print("  document: a run whose config carried no tool list contributes")
        print("  nothing to the counts above, so a tool is only 'never picked'")
        print("  among the runs that recorded an offer. Which runs those are is")
        print("  not random — see `P17-08`. Compare the offer count against the")
        print("  call count in the next section before drawing a conclusion: a")
        print("  tool called more often than it was offered is proof that this")
        print("  section is undercounting, not that the tool is unpopular.")
        print()

    print("## Picked, and how it went")
    for name in sorted(ever_called, key=lambda n: -(ev.get(n, 0) + md.get(n, 0))):
        calls = ev.get(name, 0)
        fails = ev_fail.get(name, 0)
        rate = f"{fails}/{calls}" if calls else "-"
        print(f"   {name:28} offered {offer_counts.get(name, 0):>3}"
              f"  events {calls:>3} (failed {rate:>6})"
              f"  metadata {md.get(name, 0):>3} (failed {md_fail.get(name, 0)})")
    print()

    print("## Called without being offered")
    unoffered, call_total, no_config = called_without_being_offered(conn)
    if not unoffered and not no_config:
        print("  None. Every call appears in its own run's offer.")
    for name in sorted(set(unoffered) | set(no_config), key=lambda n: -unoffered.get(n, 0)):
        print(f"   {name:24} called {call_total[name]:>3}"
              f"  not in its run's offer {unoffered.get(name, 0):>3}"
              f"  run had no config {no_config.get(name, 0):>3}")
    if unoffered:
        print()
        print("  A tool the model has no schema for should be impossible to call,")
        print("  so each of these arrived through a channel `run_config` does not")
        print("  describe. The section above is therefore a statement about the")
        print("  schema channel only: a tool reachable another way is neither")
        print("  offered nor missing, and sits in neither column.")
    print()

    print("## What the agent said it could not do")
    rows = gaps(conn)
    print(f"  {len(rows)} capability_gap events.")
    by_kind = collections.Counter(r["kind"] for r in rows)
    for kind, n in by_kind.most_common():
        print(f"   {kind:20} {n:>3}   {GAP_KINDS.get(kind, '')}")
    blank = [r for r in rows if r["empty"]]
    if blank:
        print(f"  {len(blank)} of {len(rows)} recorded no detail at all — the event fired")
        print("  and named nothing, so it says a gap happened and not which one.")
    for row in rows:
        print(f"   {row['ts']}  {row['kind']:16} {row['pattern'] or '(no detail)'}")
    print()

    print("## Failed tool calls, and whether they say why")
    fails = failures(conn)
    silent = [f for f in fails if not f["detail"]]
    print(f"  {len(fails)} failures, {len(silent)} with an empty detail column.")
    for row in fails:
        print(f"   {row['ts']}  {row['tool']:20} {row['outcome']:10}"
              f" {row['detail'] or '(no detail)'}")
    print()

    print("## The gap this data cannot see")
    print("  A tool the agent was never offered leaves no row anywhere. Nothing")
    print("  below is evidence about capabilities that do not exist — only about")
    print("  the ones that do. That half needs a different method, and saying so")
    print("  is the difference between a limitation and a silent one.")
    conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("database", help="path to a SNAPSHOT of app.db, not the live file")
    args = ap.parse_args()
    try:
        return report(args.database)
    except sqlite3.Error as exc:
        print(f"cannot read {args.database}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
