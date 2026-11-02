# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-21` · Teams — a bundle of agents hired in one go.

PandaOS puts a *Featured teams* row above its catalogue with *Hire all*. Here a
team is a manifest too — `TEAM.md`, in the same two layers as agents
(`library/pantheon/teams/<id>/`, and a person's own beside their agents) — and
*Hire all* is one hire per member, each its own row with its own settings and
reports. **Members do not hand work to each other**: that is the multi-agent
step the plan leaves for later (§ 9), and a team that pretended otherwise would
be a promise the runtime does not keep.

    ---
    id: inbox-zero
    name: Inbox Zero
    tagline: A mailbox that stays clear.
    members: [inbox-triage, follow-up-chaser, meeting-catcher]
    ---
    A sentence or two on what the team is for.

**Shared inputs are asked once.** The team's form is every member's inputs,
one field per key — the first member to declare a key gives its label and
kind — and each member is hired with the values for the keys it asks for.

**Everything is checked before anything is written** — every member's inputs,
the project — so *Hire all* leaves either every new hire or none. A member the
person has already hired is left as it is and said so.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.agents.manifest import (
    HANDOFF_VIA_RE, ManifestRefused, parse_frontmatter, split_manifest,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
SHIPPED_TEAMS = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "library", "pantheon", "teams")
TEAM_FILE = "TEAM.md"
TEAM_MAX_MEMBERS = 12
FLOW_MAX_EDGES = 24
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    tagline: str
    members: Tuple[str, ...]
    about: str
    source: str = "shipped"
    #: `P24-28`. Who hands to whom inside the team, `{from, to, via}` each;
    #: documentation today (the hall draws it), the triggers *Hire all*
    #: compiles between members once delegation lands (the plan's D4).
    flow: Tuple[Dict[str, str], ...] = ()


def parse_team(text: str, *, source: str = "shipped") -> Team:
    fm_text, about = split_manifest(text)
    fm = parse_frontmatter(fm_text)
    extra = set(fm) - {"id", "name", "tagline", "members", "flow"}
    if extra:
        raise ManifestRefused(f"The team has a field nothing reads: {', '.join(sorted(extra))}.")
    tid = str(fm.get("id") or "")
    if not _ID_RE.match(tid):
        raise ManifestRefused(f"The team id “{tid}” is not lower-case words joined by dashes.")
    name = str(fm.get("name") or "").strip()
    tagline = str(fm.get("tagline") or "").strip()
    if not name or len(name) > 48:
        raise ManifestRefused("A team needs a name of at most 48 characters.")
    if not tagline or len(tagline) > 140:
        raise ManifestRefused("A team needs a tagline of at most 140 characters.")
    members = fm.get("members")
    if not isinstance(members, list) or not (2 <= len(members) <= TEAM_MAX_MEMBERS):
        raise ManifestRefused(f"A team has 2 to {TEAM_MAX_MEMBERS} members.")
    if len(set(members)) != len(members) or not all(isinstance(m, str) and _ID_RE.match(m) for m in members):
        raise ManifestRefused("A team's members are agent ids, each once.")
    flow = fm.get("flow", [])
    if not isinstance(flow, list) or len(flow) > FLOW_MAX_EDGES:
        raise ManifestRefused(f"A team's flow is a list of at most {FLOW_MAX_EDGES} edges like "
                              f"{{from: inbox-triage, to: follow-up-chaser, via: \"document:Inbox triage\"}}.")
    edges = []
    for n, e in enumerate(flow, start=1):
        if not (isinstance(e, dict) and set(e) == {"from", "to", "via"}):
            raise ManifestRefused(f"Flow edge {n} is {{from: <member>, to: <member>, via: event:<name> | document:<title> | delegate}}.")
        if e["from"] not in members or e["to"] not in members or e["from"] == e["to"]:
            raise ManifestRefused(f"Flow edge {n} joins two different members of the team.")
        if not (isinstance(e["via"], str) and HANDOFF_VIA_RE.match(e["via"])):
            raise ManifestRefused(f"Flow edge {n}'s via is event:<name>, document:<title> or delegate.")
        edges.append({"from": e["from"], "to": e["to"], "via": e["via"]})
    return Team(id=tid, name=name, tagline=tagline, members=tuple(members),
                about=(about or "").strip(), source=source, flow=tuple(edges))


def _layer(root: str, source: str):
    good: Dict[str, Team] = {}
    broken: List[Dict[str, str]] = []
    if not os.path.isdir(root):
        return good, broken
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry, TEAM_FILE)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                team = parse_team(fh.read(), source=source)
        except ManifestRefused as refused:
            broken.append({"folder": entry, "source": source, "sentence": refused.sentence})
            continue
        except (OSError, UnicodeDecodeError) as exc:
            broken.append({"folder": entry, "source": source,
                           "sentence": f"The file could not be read: {exc.__class__.__name__}."})
            continue
        if team.id != entry:
            broken.append({"folder": entry, "source": source,
                           "sentence": f"The folder is “{entry}” but the team's id is “{team.id}”."})
            continue
        good[team.id] = team
    return good, broken


def own_teams_root(owner: Optional[str], data_dir: Optional[str] = None) -> str:
    from src.agents.catalogue import own_root
    return os.path.join(own_root(owner, data_dir), "_teams")


def teams(owner: Optional[str], agent_ids, *, shipped_root: Optional[str] = None,
          data_dir: Optional[str] = None) -> Tuple[List[Team], List[Dict[str, str]]]:
    """`(teams, broken)` as this person sees them. A team naming an agent the
    person's catalogue does not have is listed broken, with the agent named —
    never offered with a member missing."""
    shipped, broken = _layer(shipped_root or SHIPPED_TEAMS, "shipped")
    own, broken_o = _layer(own_teams_root(owner, data_dir), "own")
    merged = dict(shipped)
    merged.update(own)
    known = set(agent_ids)
    out: List[Team] = []
    for team in merged.values():
        missing = [m for m in team.members if m not in known]
        if missing:
            broken.append({"folder": team.id, "source": team.source,
                           "sentence": f"{team.name} names {', '.join(missing)}, which the hall does not have."})
            continue
        out.append(team)
    out.sort(key=lambda t: t.name.lower())
    return out, broken + broken_o


def get_team(owner: Optional[str], team_id: str, agent_ids, **kw) -> Optional[Team]:
    found, _ = teams(owner, agent_ids, **kw)
    return next((t for t in found if t.id == team_id), None)


def member_key(member_id: str, key: str) -> str:
    """The form's key for a member's own input when its key collides."""
    return f"{member_id}.{key}"


def team_inputs(team: Team, manifests: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The team's form: every member's inputs, a shared key asked once.

    A key is shared only when the members mean the same thing by it — the same
    kind and the same label. Two members that both ask `at` but mean *when it
    arrives* and *when it wraps up* are not one question: the later one is
    asked as its own field (`<member>.<key>`), labelled with its agent's name,
    so a morning brief and an evening wrap are not given one time."""
    out: List[Dict[str, Any]] = []
    seen: Dict[str, Tuple[Any, Any]] = {}
    for mid in team.members:
        m = manifests.get(mid)
        for spec in (m.inputs if m else ()):
            sig = (spec.get("kind"), spec.get("label"))
            if spec["key"] not in seen:
                seen[spec["key"]] = sig
                out.append(dict(spec))
            elif seen[spec["key"]] != sig:
                own = dict(spec)
                own["key"] = member_key(mid, spec["key"])
                own["label"] = f"{m.name}: {spec.get('label')}"
                out.append(own)
    return out


def member_values(team: Team, manifests: Dict[str, Any], member_id: str,
                  values: Dict[str, Any]) -> Dict[str, Any]:
    """What one member is hired with from the team form's values: its own
    field where its key collided, the shared field otherwise."""
    m = manifests.get(member_id)
    asked = {i["key"] for i in team_inputs(team, manifests)}
    out: Dict[str, Any] = {}
    for spec in (m.inputs if m else ()):
        own = member_key(member_id, spec["key"])
        if own in asked:
            # Its own field, and only that: the shared one means something else.
            if own in values:
                out[spec["key"]] = values[own]
        elif spec["key"] in values:
            out[spec["key"]] = values[spec["key"]]
    return out


def to_public(team: Team, manifests: Dict[str, Any], hired_ids=()) -> Dict[str, Any]:
    hired = set(hired_ids)
    return {
        "id": team.id, "name": team.name, "tagline": team.tagline, "about": team.about,
        "members": [{"id": mid, "name": manifests[mid].name if mid in manifests else mid,
                     "hired": mid in hired} for mid in team.members],
        "inputs": team_inputs(team, manifests),
        "hired": sum(1 for mid in team.members if mid in hired),
        "source": team.source,
        "flow": [dict(e) for e in team.flow],
    }
