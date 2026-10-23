# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-02` · The catalogue: two layers, the same id shadowing.

    library/pantheon/agents/<id>/AGENT.md        shipped, read-only
    <data>/agents/<person>/<id>/AGENT.md          a person's own, or their copy

A person's file with a shipped agent's id **shadows** it for that person and
nobody else, exactly as a person's skill shadows a library skill. The person's
folder is named by `workstation.protocol.project_folder` — the one function
that already turns an account into a folder name, so a person's agents and
their projects folder carry the same name (`Law 7`).

Every file is asked the lint (`manifest.parse_manifest`). One that fails it is
listed under `broken` with the sentence, never as hireable — a broken file in a
person's folder must not take a shipped agent of the same id away from them,
so a broken own file does not shadow.

Reads are cached on each file's modification time: the hall lists the whole
catalogue on every open, and 207 manifests parsed per open is work nothing
changed since the last one.
"""

from __future__ import annotations

import os
import threading
from typing import Dict, List, Optional, Tuple

from src.agents.manifest import Manifest, ManifestRefused, parse_manifest

_HERE = os.path.dirname(os.path.abspath(__file__))
SHIPPED_ROOT = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "library", "pantheon", "agents")
MANIFEST_NAME = "AGENT.md"

_cache: Dict[str, Tuple[float, object]] = {}
_lock = threading.Lock()


def own_root(owner: Optional[str], data_dir: Optional[str] = None) -> str:
    """Where a person's own agents live."""
    from src.constants import DATA_DIR
    from src.workstation_access import workstation_owner
    from workstation.protocol import project_folder
    return os.path.join(data_dir or DATA_DIR, "agents", project_folder(workstation_owner(owner)))


def _read(path: str, source: str):
    """A `Manifest`, or the `ManifestRefused` it raised — cached by mtime."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        result: object = parse_manifest(text, source=source, path=path)
    except ManifestRefused as refused:
        result = refused
    except (OSError, UnicodeDecodeError) as exc:
        result = ManifestRefused(f"The file could not be read: {exc.__class__.__name__}.")
    with _lock:
        _cache[path] = (mtime, result)
    return result


def _layer(root: str, source: str) -> Tuple[Dict[str, Manifest], List[Dict[str, str]]]:
    good: Dict[str, Manifest] = {}
    broken: List[Dict[str, str]] = []
    if not os.path.isdir(root):
        return good, broken
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry, MANIFEST_NAME)
        if not os.path.isfile(path):
            continue
        got = _read(path, source)
        if isinstance(got, Manifest):
            if got.id != entry:
                broken.append({"folder": entry, "source": source,
                               "sentence": f"The folder is “{entry}” but the file's id is “{got.id}”; "
                                           f"they have to match."})
                continue
            good[got.id] = got
        elif isinstance(got, ManifestRefused):
            broken.append({"folder": entry, "source": source, "sentence": got.sentence})
    return good, broken


def catalogue(owner: Optional[str], *, shipped_root: Optional[str] = None,
              data_dir: Optional[str] = None) -> Tuple[List[Manifest], List[Dict[str, str]]]:
    """`(agents, broken)` as this person sees them, in the hall's order:
    section order, then starred first, then wave, then name."""
    from src.agents.manifest import SECTION_IDS
    shipped, broken_s = _layer(shipped_root or SHIPPED_ROOT, "shipped")
    own, broken_o = _layer(own_root(owner, data_dir), "own")
    merged = dict(shipped)
    merged.update(own)
    order = {sid: n for n, sid in enumerate(SECTION_IDS)}
    agents = sorted(merged.values(),
                    key=lambda m: (order.get(m.section, 99), not m.starred, m.wave, m.name.lower()))
    return agents, broken_s + broken_o


def get_agent(owner: Optional[str], agent_id: str, *, shipped_root: Optional[str] = None,
              data_dir: Optional[str] = None) -> Optional[Manifest]:
    """One agent as this person sees it, or `None`."""
    if not agent_id or "/" in agent_id or "\\" in agent_id or agent_id.startswith("."):
        return None
    for root, source in ((own_root(owner, data_dir), "own"), (shipped_root or SHIPPED_ROOT, "shipped")):
        got = _read(os.path.join(root, agent_id, MANIFEST_NAME), source)
        if isinstance(got, Manifest) and got.id == agent_id:
            return got
    return None
