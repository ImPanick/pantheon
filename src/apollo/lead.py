# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which roster agent leads a goal (settled calls 6 and 8).

Apollo hands each goal to a lead agent who owns the outcome. The pick uses the
hall's own matching (`src.agents.suggest.score`: the goal's words against each
agent's name, tagline and section) and then the fit badge for the model the
work would run on (`src.agents.fit`). An agent measured as *Needs a bigger
model* is never picked; *Runs well* beats *Not measured* on an even score.

No match is an answer too: the roster has a gap, and Apollo says so rather than
staffing the goal with a guess (phase 5 drafts the missing agent).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

MIN_SCORE = 2
FIT_BONUS = {"runs-well": 2, "runs-slowly": 1, "not-measured": 0}


def pick_lead(owner: Optional[str], text: str, *, model: Optional[str] = None,
              agents: Optional[Iterable[Any]] = None, fit_of=None) -> Optional[Dict[str, Any]]:
    """`{id, name, tagline, why, fit}` for the agent that best leads `text`, or `None`."""
    from src.agents import suggest as S

    stems = S._stems(str(text or "")[:4000])
    if not stems:
        return None
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
    if not ranked:
        return None
    # Highest total, then the higher word match, then the id: the same goal
    # gets the same lead every time.
    ranked.sort(key=lambda r: (-r[0], -r[1], r[2]))
    _total, _score, _id, best, badge, s = ranked[0]
    return {"id": best.id, "name": best.name, "tagline": best.tagline, "fit": badge,
            "why": f"{best.name} does this: {best.tagline}", "words": s["words"]}
