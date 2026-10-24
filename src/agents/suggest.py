# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P25-09` · An agent for what a message is asking, offered — never summoned.

The owner (2026-10-24): *"If the user triggers key words or thought processes,
such as 'I need optimization for X workflows' or 'I'm thinking of these
products' the suggestion of 'load X agent' to enhance your experience in
{whatever task is referenced} — I think that would be a valuable add."*

Two questions, both answered here without a model, so a suggestion costs
nothing per message and says the same thing twice for the same words:

  1. **Is this a person describing a job, not asking a one-off question?**
     A phrase of need, intent, habit or planning (`INTENT`): *I need…*,
     *I'm thinking of…*, *every morning…*, *keep track of…*, *optimise…*.
  2. **Which agent in the hall does that job?** The message's words, stemmed
     (`text_stemmer`, the retrieval engines' own), against each agent's name
     and id (worth most), its tagline, and its section. The best wins when it
     clears `THRESHOLD`; nothing is offered otherwise — a wrong suggestion is
     worse than none.

The chip that shows it is the person's to take (`summon.js`): *Summon* or
*Not now*, and an agent declined is not offered again in that chat.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

INTENT = re.compile(
    r"\b(i need|i want|i'?d like|i would like|help me|can you help|i'?m thinking|i am thinking|"
    r"thinking (?:of|about)|i'?m looking|looking (?:for|into|at)|optimi[sz]|automat|streamline|"
    r"keep (?:track|an eye)|track(?:ing)? (?:of|my)|every (?:day|morning|evening|week|month)|"
    r"each (?:day|week|morning)|remind me|workflows?|i keep (?:forgetting|having to)|is there a way|"
    r"how (?:can|do) i (?:keep|stop|manage|organi[sz]e)|i'?m (?:planning|working on|trying to)|"
    r"we need|our team|i have to)\b", re.I)

# Words that say nothing about which job: the intent phrases' own, and the
# hall's commonest ones.
STOP = frozenset("""a an and are as at be but by can could do does for from get got have help how i i'm
im in into is it its just keep let like look looking make me more my need of on or our out over so some
than that the their them then there these thing things think thinking this those to too try up us use
want was we what when where which while who why will with work working workflow workflows would you your
agent agents optimise optimize optimisation optimization automate automation streamline every each
new way ways better best lot lots really very also get getting stuff one two all any much many good great
quick fast easy needs wants which cheapest""".split())

NAME_WEIGHT = 3
TAGLINE_WEIGHT = 2
SECTION_WEIGHT = 1
THRESHOLD = 2


def _stop_stems() -> frozenset:
    from src.text_stemmer import stem
    # `new` stays a word: its stem is also `news`'s, which names a job.
    return frozenset(stem(w) for w in STOP if w != "new")


def _stems(text: str) -> List[str]:
    from src.text_stemmer import stem
    stops = _stop_stems()
    out = []
    for w in re.findall(r"[a-z][a-z'-]{2,}", str(text or "").lower()):
        w = w.strip("'-")
        if w in STOP or len(w) < 3:
            continue
        st = stem(w)
        if st in stops:
            continue
        # One spelling for a doer and the doing: `watcher`/`watch`, `planner`/`plan`.
        if st.endswith("er") and len(st) > 5:
            st = st[:-2]
        out.append(st)
    return out


def wants_a_job(text: str) -> bool:
    return bool(INTENT.search(str(text or "")))


def score(text_stems: Iterable[str], agent) -> Dict[str, Any]:
    words = set(text_stems)
    name = set(_stems(agent.name)) | set(_stems(agent.id.replace("-", " ")))
    tag = set(_stems(agent.tagline))
    section = set(_stems(getattr(agent, "section_label", "") or agent.to_public().get("section_label", "")))
    hits_name = words & name
    hits_tag = (words & tag) - hits_name
    hits_section = (words & section) - hits_name - hits_tag
    total = NAME_WEIGHT * len(hits_name) + TAGLINE_WEIGHT * len(hits_tag) + SECTION_WEIGHT * len(hits_section)
    return {"score": total, "words": sorted(hits_name | hits_tag | hits_section)}


def suggest(text: str, agents: Iterable[Any], *, skip: Iterable[str] = ()) -> Optional[Dict[str, Any]]:
    """`{agent: {id, name, tagline}, why, words}` for the agent that does the
    job this message describes, or None."""
    text = str(text or "")[:4000]
    if not wants_a_job(text):
        return None
    stems = _stems(text)
    if not stems:
        return None
    skipped = set(skip)
    ranked = []
    for a in agents:
        if a.id in skipped:
            continue
        s = score(stems, a)
        if s["score"] >= THRESHOLD:
            ranked.append((s["score"], bool(getattr(a, "starred", False)), -len(a.tagline), a, s))
    if not ranked:
        return None
    ranked.sort(key=lambda r: (r[0], r[1], r[2]), reverse=True)
    best, best_s = ranked[0][3], ranked[0][4]
    if len(ranked) > 1 and ranked[1][0] == ranked[0][0] and ranked[1][1] == ranked[0][1]:
        # Two agents fit equally well: the words do not say which. Offering
        # one of them at random would be a guess presented as advice.
        if ranked[1][2] == ranked[0][2]:
            return None
    return {"agent": {"id": best.id, "name": best.name, "tagline": best.tagline},
            "why": f"{best.name} does this: {best.tagline}", "words": best_s["words"]}
