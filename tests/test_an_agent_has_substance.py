# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-27` — the bar an agent's file clears before it is called finished.

The owner, 2026-10-24: *"Some of these agents only have like 2 lines of 'how
to be {agent}' and it's ridiculously thin. There's no actual substance to it."*
Measured on `c569ed0a`: 173 agents, every runbook a numbered list of 3 to 7
lines (243 to 954 characters), five with an evaluation set — and **none** of
the 173 clears the bar below.

The row names what substance is; this file makes each part something code can
count, and drives the harness for the rest (`Law 20`):

  * **steps** a small model can follow — a numbered list (`## Steps`);
  * **the judgement calls, named and decided** — what counts as what, when to
    stop, what never to do (`## Judgement calls`: named bullets, one says when
    to stop, one says never);
  * **the edge cases** — nothing found, a tool refusing, sources that disagree
    (`## Edge cases`: named bullets covering all three);
  * **the deliverable's exact headings** — every word `delivers` makes the
    contract check look for is promised in `## Deliverable`, and every answer
    or document the file delivers names at least two (a heading the code does
    not check is a heading nobody holds the model to);
  * **what good output looks like** — `## Example`: a fenced example that
    passes the real contract check (`runtime.check_contract`) and ends as the
    run's own answer does, with `## Report` and (keeping a notebook)
    `## Carry forward`;
  * **consistent with its frontmatter** — every tool it lists is named in the
    runbook (in backticks) and it names no tool it does not have; every effect
    any of its tools can have is decided in its table, none left to the default;
  * **an evaluation set** of 5–10 cases (`evals.json`, `P24-16`), each saying
    what it proves, at least one a model must fail and one that checks what it
    must never do — and every case passes through the real harness;
  * **a sample report** (`sample.json`) that is what the harness reports for
    its case today.

**The floor.** `AT_THE_BAR` is the agents that clear it, and the measured set
must equal it: an agent that falls below fails here, and one brought up to it
is added here in the same change — so the number only rises, and each wave
starts from a live one. `python -m tests.test_an_agent_has_substance` prints
the count by section and what each agent still lacks.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Dict, List

import pytest

from src.agents import evals as E
from src.agents.catalogue import catalogue, get_agent

#: The agents that clear the bar. Measured, never carried (`Law 6`): the test
#: below fails if this differs from what the files say, either way.
AT_THE_BAR = frozenset({
    # Wave 1 (2026-10-27): the five starred and twelve of the other thirteen
    # starters — Model Steward waits for a world that answers the Forge and
    # the hub (`P24-27`'s plan).
    "inbox-triage", "morning-brief", "topic-watcher", "site-builder", "server-health",
    "follow-up-chaser", "meeting-catcher", "weekly-review", "deep-researcher", "release-watcher",
    "proofreader", "notes-gardener", "dependency-watch", "repo-doctor", "backup-verifier",
    "contact-keeper", "form-responder",
    # Email & Inbox, the rest of the section but Attachment Filer, whose tool
    # cannot save into a folder (`P24-27`'s plan).
    "newsletter-digest", "out-of-office-cover", "phishing-spotter", "receipt-collector",
    "unsubscribe-sweeper",
    # Personal & Home, the whole section.
    "bill-renewal-tracker", "evening-wrap", "family-calendar-keeper", "gift-date-keeper",
    "habit-coach", "home-maintenance", "meal-planner", "price-watcher", "trip-planner",
    # Second slice (2026-10-28, `wave-ae`). Research & Intelligence and Writing &
    # Documents, the whole of both sections.
    "competitor-tracker", "fact-checker", "local-news-digest", "market-mapper", "paper-reader",
    "standards-watch", "vendor-evaluator",
    "executive-summary", "meeting-minutes", "newsletter-writer", "report-writer", "style-keeper",
    "template-filler", "translator",
    # Knowledge & Memory but Memory Auditor, whose tool answers nothing in an
    # evaluation's world (`B1602`); Learning & Coaching, the whole section.
    "archive-sorter", "bookmark-librarian", "decision-log", "faq-builder", "wiki-builder",
    "course-builder", "flashcard-maker", "homework-helper", "language-partner", "reading-companion",
    "tutor",
    # Design & UX but UX Auditor, which walks a browser no evaluation world
    # answers yet; Product & Projects, the whole section.
    "brand-guardian", "copy-polisher", "image-optimiser", "mockup-maker", "ux-researcher",
    "web-performance",
    "deadline-watcher", "feedback-synthesiser", "planner", "roadmap-keeper", "spec-writer",
    "sprint-prioritiser", "standup-collector", "status-reporter",
    # Marketing & Content, the whole section.
    "ad-copy-writer", "campaign-strategist", "content-calendar", "content-creator",
    "email-sequence-writer", "press-release-writer", "repurposer",
    # SEO & Growth but AI Visibility Check (it asks other models, which no
    # evaluation world answers yet) and Conversion Auditor (a browser);
    # Social Media, the whole section.
    "content-gap-finder", "keyword-researcher", "rank-tracker", "review-watcher", "seo-auditor",
    "trend-spotter",
    # Sales & CRM and Support, the whole of both sections.
    "discovery-coach", "lead-researcher", "outbound-writer", "proposal-writer",
    "help-article-writer", "known-issue-linker", "support-responder",
    # Finance & Operations but Tax Folder Builder, whose download_attachment
    # cannot save into a folder yet (`B1600`).
    "bills-due", "budget-watcher", "expense-tracker", "subscription-auditor", "vendor-reviewer",
    # Legal & People and E-commerce, the whole of both sections.
    "applicant-screener", "compliance-checker", "contract-reviewer", "job-post-writer",
    "notice-date-keeper", "onboarding-buddy", "policy-answerer",
    "competitor-prices", "listing-writer",
    # Third slice (2026-10-28, `wave-ag`). The three the world now answers:
    # Memory Auditor (`B1602`), Attachment Filer and Tax Folder Builder (`B1600`).
    "memory-auditor", "attachment-filer", "tax-folder-builder",
    # The three a browser or other models blocked (`B1607`).
    "ux-auditor", "conversion-auditor", "ai-visibility-check",
    # AI Engineering, the whole section, on the world's models, Forge, hub and index.
    "model-steward", "benchmark-runner", "dataset-curator", "eval-builder", "mcp-builder",
    "prompt-tuner", "rag-builder",
    # Development, the whole section: each gathers what it needs in one command
    # first, and says that every later step waits for the person's yes.
    "api-mocker", "bug-fixer", "changelog-writer", "code-explainer", "code-reviewer", "docs-writer",
    "migration-runner", "prototype-builder", "refactorer", "script-smith",
    # Testing & QA, the whole section; nothing fetched to run a check (`Law 16`).
    "accessibility-auditor", "browser-qa", "flaky-test-hunter", "link-checker", "load-tester",
    "test-writer", "visual-regression",
    # Workstation & Desktop, the whole section: the browser ones on the world's
    # screens; the scheduled ones in one command, so a run waits for nobody.
    "browser-runner", "desktop-app-driver", "environment-setter", "file-converter", "file-fetcher",
    "form-filler", "screenshot-reporter",
    # DevOps & Infrastructure, the whole section: each looks in one command.
    "certificate-watch", "config-drift", "container-keeper", "disk-janitor", "incident-scribe",
    "log-watcher", "update-planner", "uptime-pinger",
})

SECTIONS = ("Steps", "Judgement calls", "Edge cases", "Deliverable", "Example")
NEGATIVE_CHECKS = ("not_called", "answer_lacks", "no_document", "no_draft_to", "drafts_at_most")
_NAMED = re.compile(r"^\s*[-*]\s+\*\*(?P<name>[^*]+)\*\*\s*[—–:-]\s*(?P<text>.+)$")
_NOTHING = re.compile(r"^no\b|\bnothing\b|\bempty\b|\bnone\b|\bno (?:new|mail|results?|events?|messages?)\b", re.I)
_REFUSED = re.compile(r"refus|\bfails?\b|\berror\b|unreachable|cannot|\bdown\b", re.I)
_DISAGREE = re.compile(r"disagree|contradict|conflict", re.I)
_ids = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def sections(runbook: str) -> Dict[str, str]:
    """`## Heading` → its body, ignoring headings inside a fenced block (the
    example's own `## Report` is part of the example)."""
    out: Dict[str, List[str]] = {}
    current = None
    fenced = False
    for line in (runbook or "").split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            current = line[3:].strip()
            out.setdefault(current, [])
            continue
        if current is not None:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def fenced(text: str) -> str:
    """Every fenced block in `text`, joined."""
    return "\n".join(m.group(1) for m in re.finditer(r"```[a-z]*\n(.*?)\n```", text or "", re.S))


def _negative(check: dict) -> bool:
    """A check of what must never happen: a never-kind, or a document or file
    that must lack something."""
    kind, want = next(iter(check.items()))
    return kind in NEGATIVE_CHECKS or (kind in ("document", "file", "memory") and isinstance(want, dict)
                                       and bool(want.get("lacks")))


def _named(body: str):
    return [m.groupdict() for m in map(_NAMED.match, (body or "").split("\n")) if m]


def misses(m) -> List[str]:
    """What this agent's file lacks to clear the bar, one sentence each.
    Empty means it clears it."""
    from src.agents import runtime
    from src.tool_capabilities import capabilities_for_tool
    from src.tool_policy import selectable_tool_names

    out: List[str] = []
    s = sections(m.runbook)
    for name in SECTIONS:
        if not s.get(name):
            out.append(f"The runbook has no “## {name}” section.")
    steps = [ln for ln in s.get("Steps", "").split("\n") if re.match(r"^\s*\d+\.\s+\S", ln)]
    if s.get("Steps") and len(steps) < 3:
        out.append("“## Steps” has fewer than three numbered steps.")

    calls = [c for c in _named(s.get("Judgement calls", "")) if len(c["text"]) >= 20]
    if s.get("Judgement calls"):
        if len(calls) < 3:
            out.append("“## Judgement calls” names fewer than three decisions (- **Name** — the decision).")
        if not any(re.search(r"\bstop", c["name"] + " " + c["text"], re.I) for c in calls):
            out.append("No judgement call says when to stop.")
        if not any(re.search(r"\bnever\b", c["name"] + " " + c["text"], re.I) for c in calls):
            out.append("No judgement call says what never to do.")

    edges = [c for c in _named(s.get("Edge cases", "")) if len(c["text"]) >= 20]
    if s.get("Edge cases"):
        if len(edges) < 3:
            out.append("“## Edge cases” names fewer than three cases (- **Name** — what to do).")
        for rx, what in ((_NOTHING, "nothing found"), (_REFUSED, "a tool refusing"),
                         (_DISAGREE, "sources that disagree")):
            if not any(rx.search(c["name"]) for c in edges):
                out.append(f"No edge case is named for {what}.")

    shaped = [d for d in m.delivers if d.get("kind") in ("answer", "document")]
    if not shaped:
        out.append("It delivers no answer or document whose headings the contract can check.")
    for d in shaped:
        words = d.get("must_contain") or []
        what = f"the document “{d.get('title')}”" if d.get("kind") == "document" else "the answer"
        if len(words) < 2:
            out.append(f"`delivers` names fewer than two headings for {what}, so the contract checks "
                       f"almost nothing of it.")
        missing = runtime._missing_words(s.get("Deliverable", ""), words)
        if s.get("Deliverable") and missing:
            out.append(f"“## Deliverable” does not promise {', '.join(missing)}, which `delivers` checks.")

    example = fenced(s.get("Example", ""))
    if s.get("Example"):
        if not example:
            out.append("“## Example” has no fenced example.")
        else:
            plan = runtime.RunPlan(hire_id="", agent_id=m.id, name=m.name, system_prompt="", tools=[],
                                   ask_effects=frozenset(), never_effects=frozenset(),
                                   delivers=tuple(dict(d, kind="answer") for d in shaped))
            for c in runtime.failed(runtime.check_contract(None, plan, example, [])):
                out.append(f"The example would fail its own contract: {c['detail']}")
            if not re.search(r"^## Report\s*$", example, re.M):
                out.append("The example does not end with the run's “## Report” section.")
            if m.memory != "none" and not re.search(r"^## Carry forward\s*$", example, re.M):
                out.append("The example keeps a notebook and has no “## Carry forward” section.")

    known = set(selectable_tool_names())
    ticked = set(re.findall(r"`([a-z][a-z0-9_]*)`", m.runbook))
    named = (ticked | set(re.findall(r"\b[a-z]+(?:_[a-z0-9]+)+\b", m.runbook))) & known
    foreign = sorted(named - set(m.tools))
    if foreign:
        out.append(f"The runbook names tools the agent does not have: {', '.join(foreign)}.")
    unused = sorted(t for t in m.tools if t not in ticked)
    if unused:
        out.append(f"The runbook never says when to use {', '.join(unused)} (named in backticks).")
    undecided = sorted({e.value for t in m.tools for e in capabilities_for_tool(t).effects} - set(m.effects))
    if undecided:
        out.append(f"Its effects table leaves {', '.join(undecided)} to the default.")

    try:
        cases = E.load_evals(m)
    except E.EvalRefused as exc:
        out.append(f"Its evals.json does not read: {exc.sentence}")
        cases = []
    if not (5 <= len(cases) <= E.MAX_CASES):
        out.append(f"It has {len(cases)} evaluation cases; the bar is 5 to {E.MAX_CASES}.")
    if cases:
        if any(not str(c.get("about") or "").strip() for c in cases):
            out.append("A case does not say what it proves (“about”).")
        if not any({"status": "error"} in (c.get("checks") or []) for c in cases):
            out.append("No case is one a model must fail ({\"status\": \"error\"}).")
        if not any(_negative(k) for c in cases for k in c.get("checks") or []):
            out.append("No case checks what it must never do.")

    path = os.path.join(E.agent_dir(m), "sample.json")
    try:
        with open(path, encoding="utf-8") as fh:
            sample = json.load(fh)
    except (OSError, ValueError):
        sample = None
    if not isinstance(sample, dict):
        out.append("It ships no sample.json report.")
    else:
        if sample.get("from") != "its evaluation, with a scripted model" or not sample.get("answer"):
            out.append("Its sample.json is not a report from its evaluation.")
        if sample.get("case") not in {c["id"] for c in cases}:
            out.append("Its sample.json names a case its evaluation set does not have.")
        if not sample.get("checks") or not all(c.get("ok") for c in sample.get("checks")):
            out.append("Its sample.json shows a delivery that failed its checks.")
    return out


@pytest.fixture(scope="module")
def hall():
    agents, broken = catalogue(None)
    assert broken == []
    return agents


def test_the_agents_at_the_bar_are_exactly_the_ones_pinned(hall):
    measured = {m.id: misses(m) for m in hall}
    at_bar = {aid for aid, miss in measured.items() if not miss}
    fell = {aid: measured.get(aid, ["it is not in the hall"]) for aid in AT_THE_BAR - at_bar}
    rose = sorted(at_bar - AT_THE_BAR)
    assert not fell, f"These agents no longer clear the bar: {json.dumps(fell, indent=1)}"
    assert not rose, f"These agents now clear the bar; add them to AT_THE_BAR so the floor rises: {rose}"


@pytest.mark.parametrize("agent", sorted(AT_THE_BAR))
def test_each_agent_at_the_bar_delivers_through_the_harness(agent):
    """Every case through the real scheduler, gate, contract and report; and
    the sample is what the harness reports for its case today."""
    m = get_agent(None, agent)
    results = asyncio.run(E.run_agent(m))
    failed = {r.case: [c for c in r.checks if not c["ok"]] for r in results if not r.passed}
    assert not failed, failed
    with open(os.path.join(E.agent_dir(m), "sample.json"), encoding="utf-8") as fh:
        sample = json.load(fh)
    result = next(r for r in results if r.case == sample["case"])
    # A note or event the run made is linked by its fresh id; the rest is the
    # same run, word for word — and, `B1604`, the documents it wrote are the
    # ones the sample carries.
    keys = ("answer", "read", "wrote", "checks", "documents")
    same = lambda d: _ids.sub("<id>", json.dumps({k: d.get(k) or None for k in keys}, ensure_ascii=False))
    assert same(sample) == same(E.sample_report(result)), \
        "sample.json is not what its case reports today: python -m src.agents.evals <agent> --sample"


# ── the bar itself ──────────────────────────────────────────────────────────

def _with(m, **kw):
    import dataclasses
    return dataclasses.replace(m, **kw)


def test_the_runbooks_as_they_shipped_do_not_clear_it():
    """The bar measures the file, so the 2026-10-24 Morning Brief — five
    numbered lines — misses every part of it, each in a sentence."""
    m = get_agent(None, "morning-brief")
    thin = _with(m, runbook="1. Call manage_calendar.\n2. Call list_emails.\n3. Answer with **Today**.",
                 path="/nonexistent/AGENT.md")
    said = " ".join(misses(thin))
    for words in ("no “## Steps”", "no “## Judgement calls”", "no “## Edge cases”", "no “## Example”",
                  "never says when to use", "0 evaluation cases", "no sample.json"):
        assert words in said, words


def test_a_runbook_that_names_a_tool_it_lacks_or_an_example_that_fails_its_contract_is_refused():
    m = get_agent(None, "morning-brief")
    body = m.runbook
    if "## Example" not in body:
        pytest.skip("Morning Brief is not at the bar yet")
    sneaky = _with(m, runbook=body.replace("## Steps", "## Steps\nIf it helps, call `send_email`.\n", 1))
    assert any("does not have: send_email" in x for x in misses(sneaky))
    s = sections(body)
    ex = s["Example"]
    broken = body.replace(ex, ex.replace("**Today**", "**Later**"))
    assert any("would fail its own contract" in x for x in misses(_with(m, runbook=broken)))


def report() -> None:
    """The live number, by section, and what each agent still lacks."""
    from src.agents.manifest import SECTIONS as HALL
    agents, _ = catalogue(None)
    by = {sid: [] for sid, _l, _f in HALL}
    for m in agents:
        by[m.section].append((m.id, misses(m)))
    total = sum(1 for rows in by.values() for _a, miss in rows if not miss)
    print(f"{total} of {len(agents)} agents clear the bar (P24-27).\n")
    for sid, label, _f in HALL:
        rows = by[sid]
        done = sum(1 for _a, miss in rows if not miss)
        print(f"{label}: {done} of {len(rows)}")
        for aid, miss in rows:
            if miss:
                print(f"  {aid}: {len(miss)} to go — {miss[0]}")


if __name__ == "__main__":
    report()
