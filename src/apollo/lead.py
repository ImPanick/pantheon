# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which saved agents fit a goal (settled calls 6 and 8).

A goal's lead is written for that goal (`goal_lead.py`, owner's direction
2026-11-24); the saved agent that fits it best is named in that lead's runbook
as the teammate to hand to, and `candidates` answers the fleet tool's
`roster`. The pick uses the
hall's own matching (`src.agents.suggest.score`: the goal's words against each
agent's name, tagline and section) and then the fit badge for the model the
work would run on (`src.agents.fit`). An agent measured as *Needs a bigger
model* is never picked; *Runs well* beats *Not measured* on an even score.

No match is an answer too: the written lead works the goal without a saved
teammate, and the fleet tool can propose the missing one (`gaps.py`).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

MIN_SCORE = 2
FIT_BONUS = {"runs-well": 2, "runs-slowly": 1, "not-measured": 0}


def candidates(owner: Optional[str], text: str, *, model: Optional[str] = None,
               agents: Optional[Iterable[Any]] = None, fit_of=None, limit: int = 6) -> List[Dict[str, Any]]:
    """The agents that fit `text`, best first: `{id, name, tagline, fit, why,
    words}` each. An agent measured as *Needs a bigger model* is left out."""
    from src.agents import suggest as S

    stems = S._stems(str(text or "")[:4000])
    if not stems:
        return []
    if agents is None:
        from src.agents.catalogue import catalogue
        agents, _broken = catalogue(owner)
    if fit_of is None:
        from src.agents.fit import fit, model_for
        model = model or model_for(owner)

        def fit_of(manifest):
            return fit(manifest, model)["badge"]
    ranked = []
    for agent in agents:
        s = S.score(stems, agent)
        if s["score"] < MIN_SCORE:
            continue
        badge = fit_of(agent)
        if badge == "needs-bigger":
            continue
        ranked.append((s["score"] + FIT_BONUS.get(badge, 0), s["score"], agent.id, agent, badge, s))
    # Highest total, then the higher word match, then the id: the same goal
    # gets the same lead every time.
    ranked.sort(key=lambda r: (-r[0], -r[1], r[2]))
    return [{"id": a.id, "name": a.name, "tagline": a.tagline, "fit": badge,
             "why": f"{a.name} does this: {a.tagline}", "words": s["words"]}
            for _t, _s, _i, a, badge, s in ranked[:max(1, limit)]]


def pick_lead(owner: Optional[str], text: str, *, model: Optional[str] = None,
              agents: Optional[Iterable[Any]] = None, fit_of=None) -> Optional[Dict[str, Any]]:
    """`{id, name, tagline, why, fit}` for the agent that best leads `text`, or `None`."""
    found = candidates(owner, text, model=model, agents=agents, fit_of=fit_of, limit=1)
    return found[0] if found else None
