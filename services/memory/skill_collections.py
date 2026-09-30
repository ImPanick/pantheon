# SPDX-License-Identifier: AGPL-3.0-or-later
"""Skill packages and skill groups — `P8-49`, `P8-50`, `P8-51`.

The owner, 2026-09-30, asked two things at once: that a package of skills
arrive *as* a package, sectioned and together, and that skills be groupable by
hand as well — and then, whether a skill that belongs to two groups should be
duplicated or cross-referenced. The answer he chose (`D-2026-09-30-01`) is the
shape of this file:

  * **A skill exists once.** Its `name` is its identity, its folder and its API
    id (`FORBIDDEN.md` Part 1). Nothing here copies a skill or stores anything
    about one except its name.
  * **A package** is where a set of skills came from — a GitHub repository —
    with the sections that repository declares and the name each of its
    folders was given here. It can be refreshed, switched off, or removed as a
    unit.
  * **A group** is a list of names, made by a person. A skill can be in any
    number of groups, and editing it once edits it everywhere it is listed —
    which is the whole argument for references over copies.
  * **Off wins.** A skill is left out of what the model is shown when its
    package, or any group it is in, is switched off. Switching one back on
    cannot re-enable a skill another switch still holds off; the reason is
    listed, so the card can say which.

One JSON sidecar beside `_usage.json`, owner-scoped the way skills are: a record
belongs to the owner it was written for, and `None` is the single-user owner.
Written atomically under a process lock, read on every injection — it is a few
kilobytes, and a cache here would be a second answer to "is this on?".
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from typing import Dict, Iterable, Iterator, List, Optional

logger = logging.getLogger(__name__)

COLLECTIONS_FILENAME = "_collections.json"
MAX_GROUPS = 200
MAX_GROUP_SKILLS = 2000
MAX_TITLE = 60

_LOCK = threading.RLock()
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _mine(rec: Dict, owner: Optional[str]) -> bool:
    return (rec.get("owner") or "") == (owner or "")


def package_skills(rec: Dict) -> List[str]:
    """Every skill a package holds, in section order, each once."""
    out: List[str] = []
    for sec in rec.get("sections") or []:
        for name in sec.get("skills") or []:
            if name not in out:
                out.append(name)
    return out


def clean_title(title: str) -> str:
    return " ".join(str(title or "").split())[:MAX_TITLE]


class SkillCollections:
    """Packages and groups for one skills root."""

    def __init__(self, skills_root: str):
        self.path = os.path.join(skills_root, COLLECTIONS_FILENAME)

    # -- storage ---------------------------------------------------------------

    def _load(self) -> Dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError) as e:
            # A damaged file must not take injection down with it: every skill
            # reads as on, which is what it was before this file existed.
            logger.warning("skill collections unreadable (%s); treating as empty", e)
            data = {}
        if not isinstance(data, dict):
            data = {}
        packages = data.get("packages")
        groups = data.get("groups")
        return {
            "version": 1,
            "packages": [p for p in packages if isinstance(p, dict)] if isinstance(packages, list) else [],
            "groups": [g for g in groups if isinstance(g, dict)] if isinstance(groups, list) else [],
        }

    def _save(self, data: Dict) -> None:
        from core.atomic_io import UnreadableTargetError, atomic_write_json

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            # `P3-16`: guarded. The groups a person made and the switches they
            # set are not in any other file, and `_load` answers a damaged file
            # with an empty store — which must never be written back over it.
            atomic_write_json(self.path, data, indent=2, preserve_unreadable=True)
        except UnreadableTargetError as e:
            raise ValueError(
                f"The skill packages and groups file ({self.path}) cannot be read, so it "
                "was left as it is rather than replaced. Fix or move it, then try again."
            ) from e

    @contextmanager
    def _edit(self) -> Iterator[Dict]:
        with _LOCK:
            data = self._load()
            yield data
            self._save(data)

    # -- packages --------------------------------------------------------------

    def packages(self, owner: Optional[str]) -> List[Dict]:
        return [p for p in self._load()["packages"] if _mine(p, owner)]

    def package(self, owner: Optional[str], pid: str) -> Optional[Dict]:
        return next((p for p in self.packages(owner) if p.get("id") == pid), None)

    def put_package(self, owner: Optional[str], rec: Dict) -> Dict:
        rec = dict(rec, owner=owner)
        with self._edit() as data:
            data["packages"] = [p for p in data["packages"]
                                if not (_mine(p, owner) and p.get("id") == rec.get("id"))]
            data["packages"].append(rec)
        return rec

    def drop_package(self, owner: Optional[str], pid: str) -> Optional[Dict]:
        with self._edit() as data:
            gone = next((p for p in data["packages"] if _mine(p, owner) and p.get("id") == pid), None)
            data["packages"] = [p for p in data["packages"] if p is not gone]
        return gone

    def set_package_enabled(self, owner: Optional[str], pid: str, enabled: bool) -> Optional[Dict]:
        with self._edit() as data:
            for p in data["packages"]:
                if _mine(p, owner) and p.get("id") == pid:
                    p["enabled"] = bool(enabled)
                    return p
        return None

    # -- groups ----------------------------------------------------------------

    def groups(self, owner: Optional[str]) -> List[Dict]:
        return [g for g in self._load()["groups"] if _mine(g, owner)]

    def group(self, owner: Optional[str], gid: str) -> Optional[Dict]:
        return next((g for g in self.groups(owner) if g.get("id") == gid), None)

    def create_group(self, owner: Optional[str], title: str, skills: Iterable[str] = ()) -> Dict:
        from .skill_format import slugify

        title = clean_title(title)
        if not title:
            raise ValueError("A group needs a name.")
        members = self._valid_names(skills)
        with self._edit() as data:
            mine = [g for g in data["groups"] if _mine(g, owner)]
            if len(mine) >= MAX_GROUPS:
                raise ValueError(f"You have {MAX_GROUPS} groups, which is the most there can be.")
            taken = {g.get("id") for g in mine}
            base = slugify(title, fallback="group")
            gid, i = base, 2
            while gid in taken:
                gid, i = f"{base}-{i}", i + 1
            rec = {"id": gid, "owner": owner, "title": title, "enabled": True,
                   "skills": members[:MAX_GROUP_SKILLS], "created_at": time.time()}
            data["groups"].append(rec)
        return rec

    def update_group(self, owner: Optional[str], gid: str, *, title: Optional[str] = None,
                     enabled: Optional[bool] = None, add: Iterable[str] = (),
                     remove: Iterable[str] = ()) -> Optional[Dict]:
        add_names = self._valid_names(add)
        drop = set(remove or ())
        with self._edit() as data:
            for g in data["groups"]:
                if not (_mine(g, owner) and g.get("id") == gid):
                    continue
                if title is not None:
                    t = clean_title(title)
                    if not t:
                        raise ValueError("A group needs a name.")
                    g["title"] = t
                if enabled is not None:
                    g["enabled"] = bool(enabled)
                members = [n for n in (g.get("skills") or []) if n not in drop]
                for n in add_names:
                    if n not in members:
                        members.append(n)
                if len(members) > MAX_GROUP_SKILLS:
                    raise ValueError(f"A group holds at most {MAX_GROUP_SKILLS} skills.")
                g["skills"] = members
                return g
        return None

    def delete_group(self, owner: Optional[str], gid: str) -> bool:
        with self._edit() as data:
            before = len(data["groups"])
            data["groups"] = [g for g in data["groups"]
                              if not (_mine(g, owner) and g.get("id") == gid)]
            return len(data["groups"]) != before

    @staticmethod
    def _valid_names(names: Iterable[str]) -> List[str]:
        out: List[str] = []
        for n in names or ():
            n = str(n or "").strip()
            if not _NAME_RE.match(n):
                raise ValueError(f"“{n}” is not a skill name.")
            if n not in out:
                out.append(n)
        return out

    # -- what a skill is part of -----------------------------------------------

    def switched_off(self, owner: Optional[str]) -> Dict[str, List[str]]:
        """`{skill name: [titles of what holds it off]}` for this owner."""
        data = self._load()
        off: Dict[str, List[str]] = {}
        for p in data["packages"]:
            if _mine(p, owner) and p.get("enabled") is False:
                for n in package_skills(p):
                    off.setdefault(n, []).append(str(p.get("title") or p.get("id")))
        for g in data["groups"]:
            if _mine(g, owner) and g.get("enabled") is False:
                for n in g.get("skills") or []:
                    off.setdefault(n, []).append(str(g.get("title") or g.get("id")))
        return off

    def disabled_names(self, owner: Optional[str]) -> set:
        return set(self.switched_off(owner))

    def memberships(self, owner: Optional[str]) -> Dict[str, Dict]:
        """`{skill name: {"package": id|None, "groups": [ids]}}`."""
        data = self._load()
        out: Dict[str, Dict] = {}
        for p in data["packages"]:
            if _mine(p, owner):
                for n in package_skills(p):
                    out.setdefault(n, {"package": None, "groups": []})["package"] = p.get("id")
        for g in data["groups"]:
            if _mine(g, owner):
                for n in g.get("skills") or []:
                    out.setdefault(n, {"package": None, "groups": []})["groups"].append(g.get("id"))
        return out

    def rename_skill(self, owner: Optional[str], old: str, new: str) -> None:
        """A renamed skill keeps its package and its groups."""
        if old == new:
            return
        with self._edit() as data:
            for p in data["packages"]:
                if not _mine(p, owner):
                    continue
                for sec in p.get("sections") or []:
                    sec["skills"] = [new if n == old else n for n in sec.get("skills") or []]
                names = p.get("names") or {}
                for folder, n in list(names.items()):
                    if n == old:
                        names[folder] = new
            for g in data["groups"]:
                if _mine(g, owner):
                    g["skills"] = [new if n == old else n for n in g.get("skills") or []]

    def forget_skill(self, owner: Optional[str], name: str) -> None:
        """A deleted skill leaves its package and its groups — nothing dangles."""
        with self._edit() as data:
            for p in data["packages"]:
                if not _mine(p, owner):
                    continue
                for sec in p.get("sections") or []:
                    sec["skills"] = [n for n in sec.get("skills") or [] if n != name]
                names = p.get("names") or {}
                for folder, n in list(names.items()):
                    if n == name:
                        del names[folder]
            for g in data["groups"]:
                if _mine(g, owner):
                    g["skills"] = [n for n in g.get("skills") or [] if n != name]
