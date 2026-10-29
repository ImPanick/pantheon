# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1649` — a runbook says whose runs wait for a yes.

`D-2026-10-29-01` §1 (`B1605`): in a hired run whose person holds
`can_auto_approve` — *Auto-approve* in Settings → Users, which every admin
holds (`B1342`) — an action whose every effect the hire allows runs after
outside content without a card. For anyone else a hire asks as before. The
hire page shows the runbook under `hires.ALLOWED_AFTER_OUTSIDE`'s sentence, and
the runbook is every word the model is told, so a runbook that says "after
your first command, every step waits for the person's yes" now contradicts the
page for an admin and tells the model about a card that will not come.

**Measured before this change, by this check:** 76 of the 173 shipped agents
failed it. Read one by one: seventy promised a yes for a step their own table
allows — a write, a command, a fetch, a click — which an Auto-approve holder's
run takes unasked; two promised one the gate asks nobody about after outside
content (Config Drift's `ls` and `read_file`, Trip Planner's web search); and
four promised a yes every run does wait for (ETL Runner's replace, Restore
Drill's and Screenshot Reporter's `rm`, Unsubscribe Sweeper's unsubscribe) in
words that did not tie it to the effect that asks.

**The rule, sentence by sentence** (outside the fenced examples, which show a
run's report rather than promise one; quoted text is what a run writes): a
sentence that promises a yes is either everyone's or some people's.

  * *Some people's* — a call it is about runs unasked for an Auto-approve
    holder and waits for anyone else. Then it says whose runs: it names
    Auto-approve. And a call it is about that waits for everyone even so —
    the table asks for one of its effects — is named by that effect, so the
    holder reading the page knows what still asks.
  * *Everyone's* — no call it is about is lifted, and at least one waits for
    every hirer.

**The calls a sentence is about** are read the way the hire reads them: the
calls it names (a tool in backticks, with its action or command when one
follows), else the calls its step or bullet names, else every call of the kit
`hires.kit` leaves; narrowed to the ones carrying an effect it names that its
table asks (`network_egress` asks in your hire), else to the ones that act
rather than read. Each call is then put to the real gate
(`ToolRunSecurityContext.decision_for`) after outside content, with the hire's
table as `runtime.plan_for_task` hands it (`hires.effective_effects`), its
sealed and blind lifts, and the lift on and off — so "runs unasked" and "waits"
are the gate's answers, never a second copy of its rules (`Law 7`).
"""

from __future__ import annotations

import dataclasses
import json
import re
from contextlib import contextmanager
from typing import Dict, FrozenSet, Iterator, List, Optional, Tuple

import pytest

import src.tool_capabilities as TC
from src.agents import hires as H
from src.agents.catalogue import catalogue, get_agent
from src.agents.runtime import is_blind, is_sealed

#: Says whose runs: the privilege by its name in Settings → Users.
WHOSE = re.compile(r"\bAuto-approve\b")
#: A yes in the sense of a person's approval — not "yes, no or wrong", not
#: `PermitRootLogin yes`, not `npx --yes`.
YES = re.compile(r"\b(?:the person's|their|your|the|one|a) yes\b|\bsa(?:ys|id) yes\b", re.I)
READS = frozenset({"read_public", "read_workspace", "read_private", "brokered_network_read",
                   "user_interaction"})

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
#: A code span is kept whole; a quoted phrase outside one is what a run writes.
_QUOTED = re.compile(r"(`[^`]*`)|“[^”]*”|\"[^\"`\n]*\"")
#: A tool in backticks, and the argument that follows it closely (`with {…}`,
#: `call, os.replace(…)`), when one does.
_CALL = re.compile(r"`(?P<tool>[a-z][a-z0-9_]*)`(?:[^`]{0,12}?`(?P<arg>[^`]+)`)?")
_ACTION = re.compile(r'"action":\s*"(\w+)"')

Reach = FrozenSet[str]
Call = Tuple[str, Reach]


@dataclasses.dataclass(frozen=True)
class Hire:
    """A hire's table and kit, as `runtime.plan_for_task` builds them."""
    manifest: object
    allow: FrozenSet[str]
    ask: FrozenSet[str]
    never: FrozenSet[str]
    kit: Tuple[str, ...]
    sealed: bool
    blind: bool

    @classmethod
    def of(cls, m) -> "Hire":
        table = H.effective_effects(m, {})
        never = frozenset(e for e, r in table.items() if r == "never")
        kit = tuple(H.kit(m, never))
        return cls(m, frozenset(e for e, r in table.items() if r == "allow"),
                   frozenset(e for e, r in table.items() if r == "ask"), never, kit,
                   is_sealed(kit, never), is_blind(kit))


def blocks(m) -> List[str]:
    """The tagline, then each numbered step, bullet and paragraph of the
    runbook outside its fenced examples, with quoted phrases taken out."""
    out: List[str] = [m.tagline or ""]
    cur: List[str] = []
    fenced = False
    for line in (m.runbook or "").split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append(" ".join(cur))
            cur = []
            continue
        if fenced:
            continue
        if not line.strip() or line.startswith("#") or re.match(r"^\s*(?:\d+\.|[-*])\s", line):
            out.append(" ".join(cur))
            cur = [line.strip()] if line.strip() and not line.startswith("#") else []
            continue
        cur.append(line.strip())
    out.append(" ".join(cur))
    return [_QUOTED.sub(lambda q: q.group(1) or "", b) for b in out if b.strip()]


def _reaches(tool: str, content: Optional[str] = None) -> List[Reach]:
    if content is not None:
        caps = TC.capabilities_for_action(tool, content)
        if caps.known:
            return [frozenset(e.value for e in caps.effects)]
    return [frozenset(e.value for e in r) for r in TC.call_reaches(tool)]


def _calls(text: str, kit) -> List[Call]:
    out: List[Call] = []
    for c in _CALL.finditer(text):
        tool, arg = c["tool"], c["arg"]
        if tool not in kit:
            continue
        action = _ACTION.search(arg or "")
        content = (json.dumps({"action": action[1]}) if action
                   else arg if arg and not arg.lstrip().startswith("{") else None)
        out += [(tool, r) for r in _reaches(tool, content)]
    return out


def _named(text: str, hire: Hire) -> FrozenSet[str]:
    """The effects a text names that its hire asks about."""
    return frozenset(re.findall(r"`([a-z_]+)`", text)) & hire.ask


def about(sentence: str, block: str, hire: Hire) -> List[Call]:
    """The calls a sentence's yes is about (the module's docstring). One that
    says whose runs wait is about every call it reaches, the ones still asked
    of everyone included — that is what it must then name."""
    calls = (_calls(sentence, hire.kit) or _calls(block, hire.kit)
             or [(t, r) for t in hire.kit for r in _reaches(t)])
    named = None if WHOSE.search(sentence) else (_named(sentence, hire) or _named(block, hire))
    if named:
        tools = dict.fromkeys(t for t, _r in calls)
        return ([(t, r) for t, r in calls if r & named]
                or [(t, r) for t in tools for r in _reaches(t) if r & named] or calls)
    return [(t, r) for t, r in calls if r - READS] or calls


@contextmanager
def _classified(reach: Reach) -> Iterator[None]:
    """The gate's one classifier, answering `reach` for the call being asked
    about — so the gate's own rules decide it, for a call of each shape."""
    real = TC.capabilities_for_action
    TC.capabilities_for_action = lambda tool_name, content=None: TC.ToolCapabilities(
        frozenset(TC.ToolEffect(e) for e in reach))
    try:
        yield
    finally:
        TC.capabilities_for_action = real


def runs_unasked(hire: Hire, call: Call, *, lifted: bool) -> bool:
    """Whether the real gate runs this call in the hire's run after outside
    content — for a person who holds Auto-approve (`lifted`) or not."""
    tool, reach = call
    ctx = TC.ToolRunSecurityContext(
        external_untrusted_context_seen=True, hire_ask_effects=hire.ask,
        hire_never_effects=hire.never, hire_allow_effects=hire.allow, hire_sealed=hire.sealed,
        hire_blind=hire.blind, hire_allow_after_outside=lifted)
    with _classified(reach):
        return ctx.decision_for(tool, None).allowed


def misreads(m) -> List[str]:
    """Each sentence of `m`'s runbook that promises a yes without saying
    whose runs it is true of, with why. Empty means none."""
    hire = Hire.of(m)
    out: List[str] = []
    for block in blocks(m):
        for sentence in _SENTENCE.split(block):
            if not YES.search(sentence):
                continue
            calls = about(sentence, block, hire)
            seen = [(c, runs_unasked(hire, c, lifted=True), runs_unasked(hire, c, lifted=False))
                    for c in calls]
            some = [c for c, holder, other in seen if holder and not other]
            everyone = [c for c, holder, _o in seen if not holder and not (c[1] & hire.never)]
            said = f"{m.id}: “{sentence.strip()[:160]}”"
            if WHOSE.search(sentence):
                if not some:
                    out.append(f"{said} names Auto-approve, but no call it is about runs unasked for it.")
                unnamed = sorted({e for _t, r in everyone for e in r & hire.ask}
                                 - set(re.findall(r"`([a-z_]+)`", sentence)))
                if unnamed:
                    out.append(f"{said} — its hire asks about {', '.join(unnamed)} whoever holds "
                               f"Auto-approve, and the sentence does not say so.")
            elif some:
                lifted = sorted({e for _t, r in some for e in r})
                out.append(f"{said} promises a yes for {', '.join(lifted)}, which its hire allows: "
                           f"for a person who holds Auto-approve that step runs unasked. Say whose "
                           f"runs wait.")
            elif not everyone:
                out.append(f"{said} promises a yes the gate asks nobody for.")
    return out


@pytest.fixture(scope="module")
def hall():
    agents, broken = catalogue(None)
    assert broken == []
    return agents


def test_no_runbook_promises_a_yes_without_saying_whose_runs_wait_for_it(hall):
    found = {m.id: miss for m in hall for miss in [misreads(m)] if miss}
    assert not found, json.dumps(found, indent=1, ensure_ascii=False)


# ── the check itself ────────────────────────────────────────────────────────

def _with(m, **kw):
    return dataclasses.replace(m, **kw)


def test_a_yes_the_table_asks_for_is_everyones_and_one_it_allows_is_not():
    """The same sentence, read against the table. Unsubscribe Sweeper's
    unsubscribe waits for every hirer because `external_side_effect` asks in
    its hire; set it to allow and the sentence promises an Auto-approve holder
    a yes that will not come. Contact Keeper's kit cannot carry anything out
    (sealed, `D-2026-10-24-01`), so a change its table allowed would wait for
    nobody at all."""
    m = get_agent(None, "unsubscribe-sweeper")
    assert m.effects.get("external_side_effect") == "ask", "premise: the shipped table asks"
    assert misreads(m) == []
    loose = _with(m, effects={**m.effects, "external_side_effect": "allow"})
    said = " ".join(misreads(loose))
    assert ("“It waits for the person's yes.” promises a yes for external_side_effect, which its hire "
            "allows") in said, said
    keeper = get_agent(None, "contact-keeper")
    assert keeper.effects.get("write_private") == "ask" and misreads(keeper) == []
    loose = _with(keeper, effects={**keeper.effects, "write_private": "allow"})
    assert ("“Every change waits for the person's yes.” promises a yes the gate asks nobody for."
            in " ".join(misreads(loose)))


def test_the_sentence_every_development_runbook_shipped_is_refused_and_its_rewrite_is_not():
    m = get_agent(None, "bug-fixer")
    assert "unless they hold Auto-approve" in m.runbook
    old = _with(m, runbook=m.runbook.replace(" unless they hold Auto-approve", ""))
    said = " ".join(misreads(old))
    assert "After your first command, every step waits for the person's yes." in said
    assert "execute_code" in said and "Say whose runs wait" in said
    assert misreads(m) == []


def test_what_still_asks_an_auto_approve_holder_is_named():
    """Environment Setter's commands run unasked for a holder, but one that
    deletes asks every hirer (`destructive: ask`): a sentence that names
    Auto-approve and not that is wrong for the holder reading it."""
    m = get_agent(None, "environment-setter")
    assert m.effects.get("destructive") == "ask"
    sentence = next(s for b in blocks(m) for s in _SENTENCE.split(b) if WHOSE.search(s))
    assert "`destructive`" in sentence and misreads(m) == []
    bare = _with(m, runbook=m.runbook.replace(sentence, re.sub(r";.*", ".", sentence)))
    assert any("asks about destructive whoever holds Auto-approve" in x for x in misreads(bare))


def test_a_yes_nobody_is_asked_for_is_refused_too():
    """Config Drift's `ls` and `read_file` read files in the person's
    projects, which the gate asks nobody about after outside content: the
    sentence it shipped promised a yes that never came, for anyone."""
    m = get_agent(None, "config-drift")
    step = next(ln for ln in m.runbook.split("\n") if ln.startswith("3. "))
    old = _with(m, runbook=m.runbook.replace(step, step + " Each of these waits for the person's yes."))
    assert any("promises a yes the gate asks nobody for" in x for x in misreads(old))


def test_the_gate_answers_each_kind_of_call():
    """`runs_unasked` is the gate's answer, not a copy of its rules: a write
    the hire allows is lifted only for a holder, a call carrying an asked
    effect waits for both, a read of the projects folder waits for neither."""
    news = Hire.of(get_agent(None, "newsletter-writer"))
    write = ("create_document", frozenset({"write_private"}))
    assert runs_unasked(news, write, lifted=True) and not runs_unasked(news, write, lifted=False)
    filer = Hire.of(get_agent(None, "attachment-filer"))
    save = ("download_attachment", frozenset({"read_private", "write_workspace"}))
    assert not runs_unasked(filer, save, lifted=True) and not runs_unasked(filer, save, lifted=False)
    look = ("ls", frozenset({"read_workspace"}))
    assert runs_unasked(filer, look, lifted=True) and runs_unasked(filer, look, lifted=False)
    assert TC.capabilities_for_action("ls", None).effects == frozenset({TC.ToolEffect.READ_WORKSPACE}), \
        "the classifier is restored after each question"


def report() -> None:
    """Every sentence still to fix, by agent."""
    agents, _ = catalogue(None)
    found = {m.id: miss for m in agents for miss in [misreads(m)] if miss}
    for aid, miss in found.items():
        for line in miss:
            print(line)
    print(f"\n{len(found)} of {len(agents)} runbooks promise a yes without saying whose runs wait.")


if __name__ == "__main__":
    report()
