# SPDX-License-Identifier: AGPL-3.0-or-later
# services/memory/skills.py
"""Skills storage layer.

Skills live on disk as `data/skills/<category>/<name>/SKILL.md` files with
YAML frontmatter and a structured markdown body (When to Use / Procedure /
Pitfalls / Verification). See `skill_format.py` for the format.

Usage counters (`uses`, `last_used`) live in a sidecar
`data/skills/_usage.json` keyed by owner plus skill name so the SKILL.md
content doesn't churn on every retrieval.

Ownership: skills declare `owner: <username>` in frontmatter. Single-user
deployments can leave that blank.

This module also retains a JSON fallback for any legacy `data/skills.json`
entries — they're surfaced as read-only `Skill` objects so old data still
loads while a user migrates them to disk.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Dict, Iterable, List, Optional, Tuple

from .skill_format import Skill, slugify
from .skill_lint import skill_similarity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Versioning — `P8-10`
# ---------------------------------------------------------------------------
#
# A skill is a *directory*, so the copy of what a write replaced goes in a
# `versions/` sibling: it travels with the skill through a rename or a
# recategorisation (both are one `os.rename` of the directory), it is deleted
# with the skill, and it costs no schema anywhere.
#
# Snapshots are named `NNNN-<version>.md`, never `SKILL.md`, so `_iter_skill_files`
# — which yields any directory containing a `SKILL.md` — cannot mistake one for a
# skill of its own.

VERSIONS_DIRNAME = "versions"

# What the nightly audit costs if nothing caps it: `_audit_one_skill` can rewrite
# a skill up to three times a night. Twenty keeps roughly a week of real edits per
# skill and bounds the directory.
MAX_KEPT_VERSIONS = 20

_VERSION_FILE_RE = re.compile(r"^(\d{4})-([A-Za-z0-9._-]{0,40})\.md$")
_VERSION_ID_RE = re.compile(r"^\d{4}-[A-Za-z0-9._-]{0,40}$")
_VERSION_LABEL_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")

# The fields whose change is an *edit*. Deliberately excluding `status`,
# `confidence`, `owner`, `teacher_model` and `created`: the audit writes those
# several times per skill per night (`_set_conf`, `_audit_finalize_status`), and
# a history recording them is a history with the real edit buried in it.
_SUBSTANTIVE_FIELDS = (
    "name", "description", "category", "tags", "platforms",
    "requires_toolsets", "fallback_for_toolsets",
    "when_to_use", "procedure", "pitfalls", "verification", "body_extra",
)


def _content_fingerprint(sk: Skill) -> tuple:
    """What has to differ before a write counts as an edit worth keeping."""
    out = []
    for field in _SUBSTANTIVE_FIELDS:
        v = getattr(sk, field, None)
        out.append(tuple(str(x) for x in v) if isinstance(v, list) else str(v or ""))
    return tuple(out)


def _bump_patch(version: str) -> str:
    """`1.0.0` → `1.0.1`. Anything unparseable gains a `.1` rather than raising —
    `version:` is hand-editable frontmatter and a person's `v2-final` must not
    make a save fail."""
    s = str(version or "").strip()
    if not s:
        return "1.0.1"
    parts = s.split(".")
    if parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return s + ".1"


def _version_label(version: str) -> str:
    """The `<version>` half of a snapshot filename, with anything that could
    address a directory removed. The `NNNN-` prefix already makes `.`/`..`
    impossible; this stops a `/` in hand-written frontmatter creating one."""
    label = _VERSION_LABEL_UNSAFE_RE.sub("_", str(version or "").strip())[:40]
    return label or "0"


# ---------------------------------------------------------------------------
# Parse cache — `P8-19`
# ---------------------------------------------------------------------------
#
# Module-level, not instance-level, and that is the whole point: `SkillsManager`
# is constructed fresh at every call site (`SkillsManager(DATA_DIR)` appears in
# the agent loop three times per request, in every route handler and in the tool
# handler), so an instance cache would be a cache that is always cold.
#
# Keyed on `(st_mtime_ns, st_size, st_ino)` rather than mtime alone: every write
# in this module goes through `atomic_write_text`, which `os.replace`s a new
# file into position, so the inode moves even when a filesystem's mtime
# granularity would not.

_PARSE_CACHE: Dict[str, Tuple[tuple, Dict]] = {}

# Bounded so a long-lived process that churns through skill directories cannot
# grow it without limit. The bundled library alone is 286 files.
_PARSE_CACHE_MAX = 4096


def invalidate_skill_cache() -> None:
    """Drop every cached parse. For tests and for anything that edits SKILL.md
    files behind this module's back."""
    _PARSE_CACHE.clear()


def _copy_skill_dict(d: Dict) -> Dict:
    """A caller-safe copy of a cached skill dict.

    `load_all` writes the usage counters straight onto what it is handed, and
    `Skill.to_dict()` has no nested dicts — only lists — so duplicating the lists
    is the whole of the isolation needed, at a fraction of `deepcopy`'s cost.
    """
    return {k: (list(v) if isinstance(v, list) else v) for k, v in d.items()}


def _default_library_root() -> str:
    """Where the bundled skill library ships: `<repo>/library/ecc/skills`.

    Resolved from this file's location rather than the working directory, so it
    is found identically whether Pantheon is started from the repo root, from a
    systemd unit, or inside the container. Missing is not an error — an install
    that has deleted the library simply has no bundled skills.
    """
    here = os.path.dirname(os.path.abspath(__file__))          # services/memory
    repo = os.path.dirname(os.path.dirname(here))              # repo root
    return os.environ.get("PANTHEON_SKILL_LIBRARY") or os.path.join(repo, "library", "ecc", "skills")


# ---------------------------------------------------------------------------
# Token / similarity helpers (kept for the relevance fallback)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set:
    return {w.strip('.,!?";:()[]') for w in (text or "").lower().split() if len(w) > 1}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _to_float(x, default: float = 0.0) -> float:
    """Coerce a possibly hand-edited frontmatter value to float without
    raising — a blank or non-numeric `confidence:` in a SKILL.md must not
    blow up retrieval or eviction."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# SkillsManager
# ---------------------------------------------------------------------------


class SkillsManager:
    """Read/write SKILL.md files under <data_dir>/skills/."""

    def __init__(self, data_dir: str, library_root: Optional[str] = None):
        self.data_dir = data_dir
        self.skills_root = os.path.join(data_dir, "skills")
        self.usage_file = os.path.join(self.skills_root, "_usage.json")
        self.legacy_file = os.path.join(data_dir, "skills.json")  # back-compat
        # The bundled library ships **in the repo**, not in the data dir, and is
        # never written to. Two reasons it is a separate root rather than seeded
        # copies under data/skills/:
        #   * a `data/` wipe is a supported thing to do here (data is disposable)
        #     and must not cost the user the library;
        #   * seeding copies would make every update a three-way merge against
        #     files the user may have edited. A read-only layer that a
        #     same-named user skill shadows has no merge at all.
        self.library_root = library_root if library_root is not None else _default_library_root()
        os.makedirs(self.skills_root, exist_ok=True)

    # ----------------------------------------------------------------------
    # Path helpers
    # ----------------------------------------------------------------------

    def _skill_dir(self, category: str, name: str) -> str:
        cat = slugify(category or "general", fallback="general")
        nm = slugify(name, fallback="skill")
        return os.path.join(self.skills_root, cat, nm)

    def _skill_file(self, category: str, name: str) -> str:
        return os.path.join(self._skill_dir(category, name), "SKILL.md")

    # ----------------------------------------------------------------------
    # Usage sidecar
    # ----------------------------------------------------------------------

    def _load_usage(self) -> Dict[str, Dict]:
        if not os.path.exists(self.usage_file):
            return {}
        try:
            with open(self.usage_file, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _save_usage(self, usage: Dict[str, Dict]) -> None:
        try:
            from core.atomic_io import atomic_write_json
            atomic_write_json(self.usage_file, usage, indent=2)
        except Exception:
            tmp = self.usage_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(usage, f, indent=2)
            os.replace(tmp, self.usage_file)

    @staticmethod
    def _usage_key(name: str, owner: Optional[str] = None) -> str:
        # Skill names are not globally unique once multiple owners are present.
        # Keep the usage sidecar keyed the same way the skill file is scoped.
        return f"{owner}::{name}" if owner else name

    def _usage_entry(self, usage: Dict[str, Dict], name: str, owner: Optional[str] = None) -> Dict:
        key = self._usage_key(name, owner)
        entry = usage.get(key)
        if isinstance(entry, dict):
            return entry
        return {}

    def set_audit(self, name: str, verdict: str, by_teacher: bool = False,
                  worker_model: str = "", teacher_model: str = "",
                  owner: Optional[str] = None) -> None:
        """Record the last test/audit result for a skill in the usage sidecar
        (so it surfaces in load() without touching SKILL.md). Drives the
        'verified' check + teacher mark on the card."""
        import time as _t
        usage = self._load_usage()
        key = self._usage_key(name, owner)
        e = usage.setdefault(key, {"uses": 0, "last_used": None})
        e["audit_verdict"] = verdict
        e["audit_by_teacher"] = bool(by_teacher)
        if worker_model:
            e["audit_worker_model"] = worker_model
        if teacher_model:
            e["audit_teacher_model"] = teacher_model
        e["audited_at"] = _t.time()
        self._save_usage(usage)

    def set_necessity(self, name: str, necessary: bool,
                      redundant_with=None, reason: str = "",
                      owner: Optional[str] = None) -> None:
        """Record the advisory 'is this skill necessary?' judgment in the usage
        sidecar. Surfaced on the card as a flag; never acts on the skill."""
        usage = self._load_usage()
        key = self._usage_key(name, owner)
        e = usage.setdefault(key, {"uses": 0, "last_used": None})
        e["necessity"] = {
            "necessary": bool(necessary),
            "redundant_with": list(redundant_with or []),
            "reason": str(reason or ""),
        }
        self._save_usage(usage)

    # ----------------------------------------------------------------------
    # Disk scan
    # ----------------------------------------------------------------------

    def _iter_skill_files(self) -> Iterable[str]:
        """The user's own skills. **Writable — the library is deliberately not here.**

        Three callers share this, and one of them (`backfill_owner`) *rewrites*
        every file it is handed. Folding the read-only library into this
        iterator would therefore not merely surface it; it would rewrite it in
        place on the next owner backfill. The library gets its own iterator
        below, used only on read paths.
        """
        if not os.path.isdir(self.skills_root):
            return
        for root, _dirs, files in os.walk(self.skills_root, followlinks=False):
            if "SKILL.md" in files:
                yield os.path.join(root, "SKILL.md")

    def _iter_library_files(self) -> Iterable[str]:
        """The bundled library. Read-only, and never yielded to a write path."""
        root_dir = self.library_root
        if not root_dir or not os.path.isdir(root_dir):
            return
        for root, _dirs, files in os.walk(root_dir, followlinks=False):
            if "SKILL.md" in files:
                yield os.path.join(root, "SKILL.md")

    def library_manifest(self) -> Dict:
        """What the bundled library is, and where it came from. {} if absent."""
        if not self.library_root:
            return {}
        path = os.path.join(os.path.dirname(self.library_root.rstrip(os.sep)), "MANIFEST.json")
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _read_skill(self, path: str) -> Optional[Skill]:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            return Skill.from_markdown(text, path=path)
        except Exception as e:
            logger.warning(f"Failed to parse {path}: {e}")
            return None

    def _read_skill_dict(self, path: str) -> Optional[Dict]:
        """`Skill.to_dict()` for one file, parsed at most once per revision.

        `P8-19`. Before this, every request that injected skills re-read and
        re-parsed the whole store — twice in `_build_base_prompt` /
        `_build_system_prompt` and again in the tool-RAG pass — and the bundled
        library is 286 files and 2.5 MB of markdown that never change. The walk
        still happens (it is how a new or deleted skill is noticed); what is
        skipped is re-parsing a file whose bytes are the ones already parsed.
        """
        try:
            st = os.stat(path)
        except OSError:
            return None
        stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
        hit = _PARSE_CACHE.get(path)
        if hit is not None and hit[0] == stamp:
            return _copy_skill_dict(hit[1])
        sk = self._read_skill(path)
        if sk is None:
            return None
        d = sk.to_dict()
        if len(_PARSE_CACHE) >= _PARSE_CACHE_MAX:
            _PARSE_CACHE.clear()
        _PARSE_CACHE[path] = (stamp, d)
        return _copy_skill_dict(d)

    def _find_skill_path(self, name: str, owner: Optional[str] = None) -> Optional[str]:
        """The file backing one of the user's own skills, or None.

        Same iteration order and same owner rule as every scan it replaces —
        it reads the cached parse rather than re-parsing the store to find one
        name, which is what `read_skill_md` did on every slash-command
        invocation and every audit step.
        """
        for path in self._iter_skill_files():
            d = self._read_skill_dict(path)
            if not d or d.get("name") != name:
                continue
            if (d.get("owner") or "") != (owner or ""):
                continue
            return path
        return None

    # ----------------------------------------------------------------------
    # Versions — `P8-10`
    # ----------------------------------------------------------------------

    def _versions_dir(self, skill_dir: str) -> str:
        return os.path.join(skill_dir, VERSIONS_DIRNAME)

    def _keep_version(self, path: str, old_text: str, old_version: str) -> Optional[str]:
        """Put the SKILL.md that is about to be replaced into `versions/`.

        Returns the snapshot id, or None when the copy could not be written —
        which is logged and never raised: failing a save because the *history*
        could not be written would lose the edit as well as the copy.
        """
        vdir = self._versions_dir(os.path.dirname(path))
        try:
            os.makedirs(vdir, exist_ok=True)
            seq = 0
            for fn in os.listdir(vdir):
                m = _VERSION_FILE_RE.match(fn)
                if m:
                    seq = max(seq, int(m.group(1)))
            vid = f"{seq + 1:04d}-{_version_label(old_version)}"
            from core.atomic_io import atomic_write_text
            atomic_write_text(os.path.join(vdir, vid + ".md"), old_text)
            self._prune_versions(vdir)
            return vid
        except Exception as e:
            logger.warning("Could not keep a previous version of %s: %s", path, e)
            return None

    def _prune_versions(self, vdir: str) -> None:
        try:
            kept = sorted(
                (fn for fn in os.listdir(vdir) if _VERSION_FILE_RE.match(fn)),
                reverse=True,
            )
        except OSError:
            return
        for fn in kept[MAX_KEPT_VERSIONS:]:
            try:
                os.remove(os.path.join(vdir, fn))
            except OSError:
                pass

    def _version_path(self, skill_path: str, version_id: str) -> Optional[str]:
        """Resolve a snapshot id to a file inside this skill's `versions/`.

        Two guards, because one of them is a shape check and the other is the
        filesystem's own answer: the id must match `NNNN-<label>`, and the
        resolved path must still be inside the directory after `realpath`.
        """
        if not isinstance(version_id, str) or not _VERSION_ID_RE.match(version_id):
            return None
        base = os.path.realpath(self._versions_dir(os.path.dirname(skill_path)))
        target = os.path.realpath(os.path.join(base, version_id + ".md"))
        if os.path.commonpath([base, target]) != base or target == base:
            return None
        return target if os.path.isfile(target) else None

    def list_versions(self, name: str, owner: Optional[str] = None) -> Optional[List[Dict]]:
        """Earlier copies of one skill, newest first.

        `None` means "no such skill, for you" and `[]` means "this skill exists
        and has not been edited yet" — two different answers a caller has to be
        able to tell apart, which is why this is not one empty list (`Law 10`).
        """
        path = self._find_skill_path(name, owner)
        if path is None:
            return None
        vdir = self._versions_dir(os.path.dirname(path))
        out: List[Dict] = []
        try:
            entries = sorted(os.listdir(vdir), reverse=True)
        except OSError:
            return out
        for fn in entries:
            m = _VERSION_FILE_RE.match(fn)
            if not m:
                continue
            full = os.path.join(vdir, fn)
            try:
                st = os.stat(full)
            except OSError:
                continue
            out.append({
                "id": fn[:-3],
                "version": m.group(2),
                "saved_at": int(st.st_mtime),
                "bytes": int(st.st_size),
            })
        return out

    def read_version(self, name: str, version_id: str,
                     owner: Optional[str] = None) -> Optional[str]:
        """The SKILL.md text of one earlier copy, or None."""
        path = self._find_skill_path(name, owner)
        if path is None:
            return None
        target = self._version_path(path, version_id)
        if target is None:
            return None
        try:
            with open(target, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def restore_version(self, name: str, version_id: str,
                        owner: Optional[str] = None) -> bool:
        """Put an earlier copy back as the live SKILL.md. `P8-11`.

        The restore goes through the ordinary writer, so **the copy it replaces
        is itself kept** — a rollback made by mistake costs one more click
        rather than the work it undid.

        Identity does not travel with the body. A snapshot is a file a person can
        hand-edit, and `name`, `category` and `owner` decide which directory the
        skill lives in and which id the UI holds; letting a restore carry them
        would be the rename that `_apply_skill_md` and the markdown-save endpoint
        each already refuse, arriving by a third door.
        """
        path = self._find_skill_path(name, owner)
        if path is None:
            return False
        text = self.read_version(name, version_id, owner=owner)
        if text is None:
            return False
        current = self._read_skill(path)
        if current is None:
            return False
        try:
            sk = Skill.from_markdown(text, path=path)
        except Exception as e:
            logger.warning("Could not parse version %s of %s: %s", version_id, name, e)
            return False
        sk.name = current.name
        sk.category = current.category
        sk.owner = current.owner
        sk.created = current.created or sk.created
        self._write_skill(sk)
        return True

    # ----------------------------------------------------------------------
    # Export — `P8-16`
    # ----------------------------------------------------------------------

    def export_skill(self, name: str, owner: Optional[str] = None) -> Optional[Dict[str, str]]:
        """One skill's directory as `{relative path: text}`, or None if absent.

        The exact shape `import_bundle_from_files` takes, so an export is an
        import's inverse and a round trip is a round trip rather than two
        formats that nearly agree (`Law 14`). The caps are the importer's own
        constants for the same reason: an export that could not be imported
        back would be a backup nobody can restore.

        `versions/` is excluded. It is this install's edit history, not part of
        the skill, and shipping it would put a colleague's rejected drafts in
        whatever the user shares.
        """
        path = self._find_skill_path(name, owner)
        if path is None:
            return None
        from .skill_importer import MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES

        base = os.path.dirname(path)
        out: Dict[str, str] = {}
        total = 0
        for root, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d != VERSIONS_DIRNAME)
            for fn in sorted(files):
                if len(out) >= MAX_FILES or total >= MAX_TOTAL_BYTES:
                    return out
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, base).replace(os.sep, "/")
                try:
                    if os.path.getsize(full) > MAX_FILE_BYTES:
                        logger.info("Skill export: skipping oversized %s", rel)
                        continue
                    with open(full, encoding="utf-8") as f:
                        text = f.read()
                except (OSError, UnicodeDecodeError):
                    # A binary or unreadable extra file is not a reason to fail
                    # the export of the procedure somebody actually wants.
                    logger.info("Skill export: skipping unreadable %s", rel)
                    continue
                total += len(text.encode("utf-8", "ignore"))
                out[rel] = text
        return out

    def _write_skill(self, sk: Skill, *, bump: bool = True) -> str:
        """Persist a skill, keeping whatever it replaced.

        `P8-10`. Every write in this module lands here, which is why one place
        can make the guarantee: if the new markdown differs *substantively* from
        what is on disk, the old text goes to `versions/` first and the patch
        number moves. A caller that set the version itself is believed — a
        person who typed `2.0.0` meant it — and that is exactly the case no
        caller in this repo exercises today, which is why the field had never
        moved off `1.0.0`.
        """
        path = self._skill_file(sk.category or "general", sk.name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        from core.atomic_io import atomic_write_text
        try:
            with open(path, encoding="utf-8") as f:
                old_text = f.read()
        except OSError:
            old_text = None
        text = sk.to_markdown()
        if old_text is not None and old_text != text:
            try:
                old_sk = Skill.from_markdown(old_text)
            except Exception:
                old_sk = None
            if old_sk is not None and _content_fingerprint(old_sk) != _content_fingerprint(sk):
                self._keep_version(path, old_text, old_sk.version)
                if bump and str(sk.version or "") == str(old_sk.version or ""):
                    sk.version = _bump_patch(sk.version)
                    text = sk.to_markdown()
        atomic_write_text(path, text)
        sk.path = path
        return path

    def backfill_owner(self, primary_owner: str, valid_owners: Optional[set[str]] = None) -> int:
        """Assign legacy/unclaimed skill files to the primary owner.

        Skills are disk-backed, so the DB legacy-owner migration cannot fix
        them. If strict owner filtering is enabled and SKILL.md files have no
        owner or an owner from a deleted/test account, the UI appears empty even
        though files still exist. This mirrors the DB legacy-owner sweep.
        """
        primary_owner = (primary_owner or "").strip()
        if not primary_owner:
            return 0
        valid_owners = set(valid_owners or [])
        changed = 0
        for path in self._iter_skill_files():
            sk = self._read_skill(path)
            if not sk:
                continue
            owner = (sk.owner or "").strip()
            if owner == primary_owner:
                continue
            if owner and owner in valid_owners:
                continue
            sk.owner = primary_owner
            try:
                self._write_skill(sk)
                changed += 1
            except Exception as e:
                logger.warning("Failed to backfill owner for skill %s: %s", sk.name, e)
        return changed

    # ----------------------------------------------------------------------
    # Public API — keeps the old method names so callers don't break
    # ----------------------------------------------------------------------

    def load_all(self) -> List[Dict]:
        """Return every skill as a plain dict, plus any legacy JSON entries."""
        usage = self._load_usage()
        out: List[Dict] = []
        seen_names: set[str] = set()
        for path in self._iter_skill_files():
            d = self._read_skill_dict(path)
            if not d:
                continue
            name, owner_of = d.get("name"), d.get("owner")
            u = self._usage_entry(usage, name, owner_of)
            d["uses"] = int(u.get("uses", 0))
            d["last_used"] = u.get("last_used")
            d["opens"] = int(u.get("opens", 0))
            d["last_opened"] = u.get("last_opened")
            d["audit_verdict"] = u.get("audit_verdict")
            d["audit_by_teacher"] = bool(u.get("audit_by_teacher"))
            d["audit_worker_model"] = u.get("audit_worker_model")
            d["audit_teacher_model"] = u.get("audit_teacher_model")
            d["audited_at"] = u.get("audited_at")
            d["necessity"] = u.get("necessity")
            out.append(d)
            seen_names.add(name)

        # The bundled library, second so a user's own skill of the same name
        # shadows it. That shadowing *is* the fork mechanism: save a skill under
        # a bundled name and yours wins, with no merge and nothing to undo.
        for path in self._iter_library_files():
            d = self._read_skill_dict(path)
            if not d or d.get("name") in seen_names:
                continue
            u = self._usage_entry(usage, d.get("name"), None)
            d["uses"] = int(u.get("uses", 0))
            d["last_used"] = u.get("last_used")
            d["opens"] = int(u.get("opens", 0))
            d["last_opened"] = u.get("last_opened")
            d["source"] = "bundled"
            d["bundled"] = True
            d["editable"] = False
            d["owner"] = None          # bundled skills belong to the install
            out.append(d)
            seen_names.add(d.get("name"))

        # Legacy JSON entries — surfaced as draft, not editable from new flow
        if os.path.exists(self.legacy_file):
            try:
                with open(self.legacy_file, encoding="utf-8") as f:
                    legacy = json.load(f)
                if isinstance(legacy, list):
                    for row in legacy:
                        if not isinstance(row, dict):
                            continue
                        name = slugify(row.get("title") or row.get("id") or "skill")
                        if name in seen_names:
                            continue
                        out.append({
                            "id": row.get("id") or name,
                            "name": name,
                            "description": row.get("title", ""),
                            "version": "0.0.1",
                            "category": "legacy",
                            "tags": row.get("tags") or [],
                            "status": row.get("status") or "draft",
                            "confidence": row.get("confidence", 0.5),
                            "source": row.get("source", "imported"),
                            "owner": row.get("owner"),
                            "when_to_use": row.get("problem", ""),
                            "procedure": row.get("steps") or [],
                            "pitfalls": [],
                            "verification": [],
                            "body_extra": row.get("solution", ""),
                            "title": row.get("title", ""),
                            "problem": row.get("problem", ""),
                            "solution": row.get("solution", ""),
                            "steps": row.get("steps") or [],
                            "uses": row.get("uses", 0),
                            "last_used": row.get("last_used"),
                            "_legacy": True,
                        })
            except Exception:
                pass
        return out

    def load(self, owner: Optional[str] = None) -> List[Dict]:
        entries = self.load_all()
        if owner is None:
            return entries
        # SECURITY: strict ownership filter. The previous predicate also
        # included skills with NO owner field (`not s.get("owner")`), which
        # leaked legacy / un-stamped skills to every authenticated user.
        # Hide them now; the owner needs to be backfilled on disk if those
        # skills should be visible to a specific user.
        return [s for s in entries if s.get("owner") == owner]

    # ----------------------------------------------------------------------
    # CRUD — disk-backed
    # ----------------------------------------------------------------------

    def add_skill(
        self,
        title: str = "",
        problem: str = "",
        solution: str = "",
        steps: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        source: str = "learned",
        teacher_model: Optional[str] = None,
        confidence: float = 0.8,
        session_id: Optional[str] = None,
        owner: Optional[str] = None,
        # New-schema fields (optional; fall back to old shape if absent)
        name: Optional[str] = None,
        description: Optional[str] = None,
        category: str = "general",
        when_to_use: Optional[str] = None,
        procedure: Optional[List[str]] = None,
        pitfalls: Optional[List[str]] = None,
        verification: Optional[List[str]] = None,
        platforms: Optional[List[str]] = None,
        requires_toolsets: Optional[List[str]] = None,
        fallback_for_toolsets: Optional[List[str]] = None,
        status: str = "draft",
        version: str = "1.0.0",
    ) -> Dict:
        # Normalize name
        nm = slugify(name or title or description or "skill")

        # Free dedup-at-creation (always, no API): for LLM-authored skills,
        # skip if a near-identical skill already exists. User-authored skills
        # are never auto-skipped — a human asked for it, and `P9-12`'s undo
        # depends on that exemption to restore a deleted member of a duplicate
        # pair. The every-X AI audit handles the fuzzier near-duplicates this
        # cheap check won't catch.
        #
        # `P8-15` / `B731`. The comparison is `skill_lint.skill_similarity`, the
        # same function the author-facing lint and the nightly blocker use, so
        # the 0.82 refused here and the 0.38 shown to the author are two points
        # on **one** scale. It used to be `_tokenize`/`_jaccard` — a whitespace
        # split that keeps stopwords and two-character words — which measured
        # 1.65× higher than the lint's tokens on the same pair, so the two
        # numbers were never comparable and `B731` compared them anyway.
        # Measured over all 40,755 pairs of the bundled library on 2026-09-19:
        # the corpus maximum is 0.700 on either scale, so nothing reaches 0.82
        # and this unification changed no decision this branch has ever made.
        #
        # **And the exemption is no longer silent.** `SkillAddRequest.source`
        # defaults to `"user"`, so every skill added from the Workshop form took
        # the exempt branch and nothing anywhere said what it had just copied.
        # The skill is still created; `_overlaps` says what it sits on top of.
        from .skill_lint import DUPLICATE_REFUSAL, skill_overlaps
        _all = self.load_all()
        _dedup_pool = _all if owner is None else [s for s in _all if s.get("owner") == owner]
        _candidate = {
            "name": nm,
            "description": (description or title or ""),
            "when_to_use": (when_to_use if when_to_use is not None else (problem or "")),
            "procedure": list(procedure if procedure is not None else (steps or [])),
            "tags": list(tags or []),
        }
        if source != "user":
            for s in _dedup_pool:
                if skill_similarity(_candidate, s) >= DUPLICATE_REFUSAL:
                    # Near-identical — don't grow the library; bump the
                    # existing skill's usage and return it so the caller
                    # knows it already exists.
                    try:
                        self.record_use(s["name"], owner=s.get("owner"))
                    except Exception:
                        pass
                    return {**s, "_deduped": True, "_duplicate_of": s.get("name"),
                            "_duplicate_score": round(skill_similarity(_candidate, s), 3)}

        # Avoid clobbering an existing skill with the same name
        existing = {s["name"] for s in _all}
        base = nm
        i = 2
        while nm in existing:
            nm = f"{base}-{i}"
            i += 1

        sk = Skill(
            name=nm,
            description=(description or title or "").strip(),
            version=version,
            category=category or "general",
            tags=list(tags or []),
            platforms=list(platforms or []),
            requires_toolsets=list(requires_toolsets or []),
            fallback_for_toolsets=list(fallback_for_toolsets or []),
            status=status or "draft",
            confidence=float(confidence),
            source=source,
            teacher_model=teacher_model,
            owner=owner,
            when_to_use=(when_to_use if when_to_use is not None else (problem or "")),
            procedure=list(procedure if procedure is not None else (steps or [])),
            pitfalls=list(pitfalls or []),
            verification=list(verification or []),
            body_extra=(solution if solution and not procedure else ""),
        )
        self._write_skill(sk)

        # `P8-15`. What the new skill sits on top of, on the scale the lint uses.
        # Advisory and never a refusal: this is the branch a person asked for.
        out = sk.to_dict()
        try:
            _cand = dict(_candidate, name=nm)
            overlaps = skill_overlaps(_cand, _dedup_pool)
            if overlaps:
                out["_overlaps"] = overlaps
        except Exception:
            logger.debug("overlap report skipped", exc_info=True)
        return out

    def import_bundle_from_files(
        self,
        files: Dict[str, str],
        *,
        owner: Optional[str] = None,
        source_url: str = "",
        category: str = "imported",
    ) -> Dict:
        """Install a fetched skill bundle (relative path → text) under skills/."""
        from .skill_importer import SkillImportError, pick_skill_md, _safe_relpath
        from core.atomic_io import atomic_write_text

        if not files:
            raise SkillImportError("empty bundle")
        _rel, skill_md = pick_skill_md(files)
        sk = Skill.from_markdown(skill_md)
        nm = slugify(sk.name or _rel.split("/")[-2] or "skill")
        cat = slugify(category or sk.category or "imported", fallback="imported")

        existing = {s["name"] for s in self.load_all()}
        base = nm
        i = 2
        while nm in existing:
            nm = f"{base}-{i}"
            i += 1

        skill_dir = self._skill_dir(cat, nm)
        os.makedirs(skill_dir, exist_ok=True)

        # Preserve bundle layout (templates/, references/, etc.) under the skill dir.
        for rel, content in files.items():
            safe = _safe_relpath(rel)
            dest = os.path.join(skill_dir, safe)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            atomic_write_text(dest, content)

        sk.name = nm
        sk.category = cat
        sk.owner = owner
        sk.source = "imported"
        if source_url:
            extra = (sk.body_extra or "").strip()
            note = f"Imported from {source_url}"
            sk.body_extra = f"{extra}\n\n{note}".strip() if extra else note
        atomic_write_text(self._skill_file(cat, nm), sk.to_markdown())
        sk.path = self._skill_file(cat, nm)
        return sk.to_dict()

    def update_skill(self, skill_id: str, updates: Dict, owner: Optional[str] = None) -> bool:
        """`skill_id` is the slug name. Allows updating any field plus
        renames if `name` changes (file is moved on disk).

        The call is owner-scoped: it matches a skill on disk only if
        `skill.owner == owner` (string compare; both empty-string and
        None mean "ownerless"). When `owner is None` (the default), the
        call only matches skills whose own `owner` field is empty —
        callers that want to edit an owned skill must pass the matching
        owner explicitly. This prevents a caller with one owner from
        mutating a file owned by another user that happens to share
        the same slug across category directories. The `owner` key in
        `updates` is also ignored — ownership is not an editable field
        via this path; rename or admin tooling is required for that.
        """
        for path in self._iter_skill_files():
            sk = self._read_skill(path)
            if not sk or sk.name != skill_id:
                continue
            if (sk.owner or "") != (owner or ""):
                continue

            old_dir = os.path.dirname(path)

            scalar_keys = (
                "description", "version", "category", "status", "confidence",
                "source", "teacher_model", "when_to_use",
                "body_extra",
            )
            for k in scalar_keys:
                if k in updates:
                    setattr(sk, k, updates[k])
            list_keys = ("tags", "procedure", "pitfalls", "verification",
                         "platforms", "requires_toolsets", "fallback_for_toolsets")
            for k in list_keys:
                if k in updates:
                    setattr(sk, k, list(updates[k] or []))

            # Old-schema field aliases
            if "title" in updates and "description" not in updates:
                sk.description = updates["title"]
            if "problem" in updates and "when_to_use" not in updates:
                sk.when_to_use = updates["problem"]
            if "solution" in updates and "body_extra" not in updates and not sk.procedure:
                sk.body_extra = updates["solution"]
            if "steps" in updates and "procedure" not in updates:
                sk.procedure = list(updates["steps"] or [])

            # Rename
            new_name = slugify(updates.get("name") or sk.name)
            if new_name != sk.name:
                sk.name = new_name

            # Write to potentially new path
            new_path = self._skill_file(sk.category, sk.name)
            if new_path != path:
                # Move the whole skill directory if rename or recategorize
                new_dir = os.path.dirname(new_path)
                if os.path.isdir(new_dir):
                    logger.warning(f"Skill rename target exists: {new_dir}")
                    return False
                os.makedirs(os.path.dirname(new_dir), exist_ok=True)
                os.rename(old_dir, new_dir)
                # Also rename usage key
                usage = self._load_usage()
                old_usage_key = self._usage_key(skill_id, sk.owner)
                if old_usage_key in usage:
                    usage[self._usage_key(sk.name, sk.owner)] = usage.pop(old_usage_key)
                    self._save_usage(usage)
            self._write_skill(sk)
            return True
        return False

    def delete_skill(self, skill_id: str, owner: Optional[str] = None) -> bool:
        for path in self._iter_skill_files():
            sk = self._read_skill(path)
            if not sk or sk.name != skill_id:
                continue
            if (sk.owner or "") != (owner or ""):
                continue
            skill_dir = os.path.dirname(path)
            try:
                # Remove the whole skill dir
                for root, dirs, files in os.walk(skill_dir, topdown=False):
                    for f in files:
                        os.remove(os.path.join(root, f))
                    for d in dirs:
                        os.rmdir(os.path.join(root, d))
                os.rmdir(skill_dir)
            except Exception as e:
                logger.warning(f"Failed to remove skill dir {skill_dir}: {e}")
                return False
            usage = self._load_usage()
            usage_key = self._usage_key(skill_id, sk.owner)
            if usage_key in usage:
                del usage[usage_key]
                self._save_usage(usage)
            return True
        return False

    def record_use(self, skill_id: str, owner: Optional[str] = None) -> None:
        """One retrieval. `uses` counts what was **shown** to the model.

        `P8-21` re-measured what this number means and it is not what the card
        says. Its only caller is `agent_loop._build_system_prompt`, which
        increments it for every skill `get_relevant_skills` returned — before
        the model has read a word of it. So "used 40 times" is "matched 40
        times", and the matcher is Jaccard overlap against the last user
        message.

        `Law 1` and `Law 2` keep it exactly as it is: `uses` is on the wire, on
        the card and in three sort orders. What changed is that it is no longer
        the **only** number, and no longer the one that earns a retrieval boost.
        See `record_open`.
        """
        usage = self._load_usage()
        key = self._usage_key(skill_id, owner)
        entry = usage.setdefault(key, {"uses": 0, "last_used": None})
        entry["uses"] = int(entry.get("uses", 0)) + 1
        entry["last_used"] = int(time.time())
        self._save_usage(usage)

    def record_open(self, skill_id: str, owner: Optional[str] = None) -> None:
        """One open. `opens` counts what the model **fetched**. `P8-21`.

        A skill is opened when something calls `manage_skills action=view` and
        reads the whole SKILL.md. The index line carries name, description and
        category only (`skill_injection.INJECTED_FIELDS`), so fetching the file
        is a deliberate second step taken after reading the line — which is the
        nearest thing to evidence of use that exists anywhere on this path.

        It is not "the skill worked": nothing in this product knows that. It is
        "the model wanted the procedure", and that is a strictly better signal
        than "the retriever emitted it", which is what `uses` records.
        """
        usage = self._load_usage()
        key = self._usage_key(skill_id, owner)
        entry = usage.setdefault(key, {"uses": 0, "last_used": None})
        entry["opens"] = int(entry.get("opens", 0)) + 1
        entry["last_opened"] = int(time.time())
        self._save_usage(usage)

    # ----------------------------------------------------------------------
    # Reading a single skill (used by the skill_view tool)
    # ----------------------------------------------------------------------

    def read_skill_md(self, name: str, owner: Optional[str] = None) -> Optional[str]:
        path = self._find_skill_path(name, owner)
        if path is None:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def read_skill_reference(self, name: str, ref_path: str, owner: Optional[str] = None) -> Optional[str]:
        """Read a sub-file under the skill's directory (references/, etc).
        Refuses path traversal."""
        path = self._find_skill_path(name, owner)
        if path is None:
            return None
        base = os.path.realpath(os.path.dirname(path))
        target = os.path.realpath(os.path.join(base, ref_path))
        if os.path.commonpath([base, target]) != base or target == os.path.dirname(path):
            return None
        if not os.path.isfile(target):
            return None
        try:
            with open(target, encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    # ----------------------------------------------------------------------
    # Index — the lightweight summary injected into the system prompt
    # ----------------------------------------------------------------------

    def index_for(
        self,
        owner: Optional[str] = None,
        *,
        active_toolsets: Optional[List[str]] = None,
        platform: Optional[str] = None,
    ) -> List[Dict]:
        """Return the `[{name, description, category, status}]` list the
        agent sees in its system prompt.

        Includes:
          - All published skills.
          - Drafts written by the teacher-escalation loop
            (`source == "teacher-escalation"`). The whole point of
            the teacher loop is for the student to find the new
            procedure on the very next turn — waiting for a manual
            publish click defeats the loop.

        Excludes user-created drafts (status=draft, source != teacher-
        escalation) — those are work-in-progress and pollute the
        prompt with half-finished procedures.
        """
        out = []
        for s in self.load(owner=owner):
            status = s.get("status")
            # Published + None (pre-status legacy) always included.
            # Drafts only if the teacher wrote them.
            if status not in ("published", None):
                if status == "draft" and s.get("source") == "teacher-escalation":
                    pass  # let it through
                else:
                    continue
            # Platform gating
            if platform and s.get("platforms") and platform not in s["platforms"]:
                continue
            # requires_toolsets: hide unless every required toolset is active.
            # active_toolsets=None means the caller doesn't know the active
            # set (API listings, chat preface) — don't gate in that case;
            # only an explicit list filters.
            req = s.get("requires_toolsets") or []
            if req and active_toolsets is not None and not all(t in active_toolsets for t in req):
                continue
            # fallback_for_toolsets: hide when any of those toolsets is active
            fb = s.get("fallback_for_toolsets") or []
            if fb and active_toolsets and any(t in active_toolsets for t in fb):
                continue
            out.append({
                "name": s["name"],
                "description": s.get("description") or s.get("title", ""),
                "category": s.get("category", "general"),
                "status": status or "published",
                # `P4-16`. Where the procedure came from, and — when a teacher
                # wrote it — which model. The index is what the agent is shown,
                # so it is also what a report of "what was it shown" has to read
                # from; deriving those two fields from a second pass over the
                # store would be a second answer to the same question. Neither
                # reaches the prompt: the prompt lines are built from `name`,
                # `description` and `category` only.
                "source": s.get("source") or "",
                "teacher_model": s.get("teacher_model") or "",
                # `P8-21`. Carried for `render_skill_index_block`'s decision
                # about what survives the catalogue budget, and printed on no
                # prompt line — the same arrangement `source` and
                # `teacher_model` already have for `P4-16`'s receipt.
                "uses": int(s.get("uses") or 0),
                "opens": int(s.get("opens") or 0),
            })
        out.sort(key=lambda x: (x["category"], x["name"]))
        return out

    # ----------------------------------------------------------------------
    # Relevance search (kept for the existing /api/skills/search endpoint
    # and the `manage_skills` action="search"). Now operates on the new
    # field set.
    # ----------------------------------------------------------------------

    def get_relevant_skills(
        self,
        query: str,
        skills: Optional[List[Dict]] = None,
        threshold: float = 0.3,
        max_items: int = 5,
        min_confidence: float = 0.0,
    ) -> List[Dict]:
        if skills is None:
            skills = self.load_all()
        if not skills or not query.strip():
            return []
        # Consider published AND draft skills for relevance retrieval.
        # The teacher-escalation loop writes new skills as drafts; the
        # whole point is for the student to find them on the next try
        # without a manual publish click. The UI flags teacher-written
        # entries with a 🎓 badge so users can demote / delete bad
        # ones when they spot them.
        skills = [s for s in skills if s.get("status") in ("published", "draft")]
        # Confidence gate (used by prompt-injection, NOT by search): a DRAFT
        # skill must clear the bar to be injected. Published skills are already
        # vetted, so they always qualify. Missing confidence = treat as 1.0
        # (legacy skills shouldn't silently vanish). 0 disables the gate.
        if min_confidence > 0:
            def _passes(s):
                if s.get("status") == "published":
                    return True
                # Teacher-escalation drafts are auto-written from a (possibly
                # untrusted) trace and injected as authoritative guidance, so they
                # must EARN injection with an explicit, parseable confidence that
                # clears the bar — fail closed on a missing/garbage value instead
                # of treating it as 1.0. Hand-authored legacy drafts keep the
                # lenient "unset → keep" behavior so they don't silently vanish.
                if s.get("source") == "teacher-escalation":
                    c = s.get("confidence")
                    if c is None:
                        return False
                    return _to_float(c, 0.0) >= min_confidence  # unparseable → fail closed
                c = s.get("confidence")
                if c is None:
                    return True  # unset → don't filter (legacy)
                return _to_float(c, 1.0) >= min_confidence  # unparseable → pass
            skills = [s for s in skills if _passes(s)]
        if not skills:
            return []

        query_tokens = _tokenize(query)
        scored = []
        for sk in skills:
            text = " ".join([
                sk.get("name", ""),
                sk.get("description", ""),
                sk.get("when_to_use", ""),
                " ".join(sk.get("tags", []) or []),
                " ".join(sk.get("procedure", []) or []),
            ])
            score = _jaccard(query_tokens, _tokenize(text))
            for tag in sk.get("tags", []) or []:
                # Match tags as whole tokens, not substrings: `tag in query`
                # boosted e.g. a "ai" tag for any query containing "email".
                tag_tokens = _tokenize(tag)
                if tag_tokens and tag_tokens <= query_tokens:
                    score = max(score, 0.3) * 1.3
            if query.lower() in (sk.get("description") or "").lower():
                score = max(score, 0.6)
            score *= 1.0 + _to_float(sk.get("confidence"), 0.5) * 0.1
            # `P8-21`. This boost used to key off `uses`, which is written by
            # this very function's caller for every skill it returns — so one
            # keyword coincidence bought a permanent 5% advantage in the next
            # match, and the next, compounding luck into rank. `opens` is the
            # model fetching the procedure through `manage_skills action=view`,
            # which nothing in the retrieval path writes.
            if sk.get("opens", 0) > 0:
                score *= 1.05
            if score >= threshold:
                scored.append((score, sk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [sk for _, sk in scored[:max_items]]
