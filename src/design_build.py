# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P26-08` · *Build it*: a design handed to the project as a branch.

The owner (2026-10-24): *"Eventually — we will implement whole-project DevOps
as an additional layer beyond this platform."* This is the seam that layer
extends: one design becomes one branch, `design/<slug>`, worked on in its own
folder, reviewed and previewed, and merged only when the person says yes.

**Where the work happens.** A git worktree beside the project —
`<project>--design-<slug>`, on the branch `design/<slug>` made from the base
branch's tip — so the person's own checkout is never moved and the agent's
changes are on the branch by construction: git itself refuses to check the
base branch out in a second worktree while it is checked out in the first, so
the agent's `git` tool (`P25-03`) cannot switch the build folder onto it.
Every command is the person's own, where their shell runs — their workstation,
or this machine for an admin — through the git tool's own `_Place`, with its
identity and its settings (hooks off, no fs-monitor).

**The brief** is `design/<slug>/BUILD.md` in the branch, its first commit:
the screens (the design's pages, read where the design lives), the design
system's tokens, every note with its author (`P26-09`), and the acceptance —
the person's lines and the rules of the branch (commit here, never merge).

**The merge is the person's.** Nothing here merges unless the request is a
person's (not a token, not the assistant) and says `yes` — a literal `true`,
which only the window's *Yes, merge* sends — and the project folder is on the
base branch with no changes of its own. A conflict aborts the merge and says
which files. The adversary (`Law 17`) is a tool acting on an approval it never
got: the agent's tools have no merge, and the one route that merges asks for
the person.

**The record** of a build is kept with the design, in `design.json`'s
`build` — the design's own file, which is not part of its versions.
"""

from __future__ import annotations

import json
import os
import posixpath
import time
from typing import Any, Dict, List, Optional

from src.design_files import DESIGN_DIR, META, DesignFileRefused, _Fs, _clean_slug

BRANCH_PREFIX = "design/"
TIMEOUT_S = 120.0
ACCEPTANCE_MAX = 4000
STATUSES = ("open", "merged", "closed")


class BuildRefused(DesignFileRefused):
    pass


# ── where git runs ──────────────────────────────────────────────────────────

async def _place(owner: Optional[str]):
    """The person's shell, as the git tool reaches it — or a sentence."""
    from src.agent_tools.git_tools import _Place
    place = _Place(owner, None)
    refused = await place.open()
    if refused is not None:
        raise BuildRefused(refused.get("error") or "Your workstation did not answer.", 503)
    if not place.in_workstation:
        from src.tool_execution import _owner_is_admin
        if not _owner_is_admin(owner):
            raise BuildRefused("A build runs git where your shell runs, and you have no shell here yet: an admin "
                               "can switch the workstation on for you in Settings → Workstation.", 409)
    return place


async def _git(place, cwd: str, identity, *argv: str, ok_codes=(0,)) -> Dict[str, Any]:
    from src.agent_tools.git_tools import _git as line
    r = await place.run(line(identity, *argv), cwd, {}, TIMEOUT_S)
    if r.get("timed_out"):
        raise BuildRefused(f"git {argv[0]} did not finish within {int(TIMEOUT_S)} seconds.", 504)
    r["out"] = (r.get("stdout") or "").strip()
    r["err"] = (r.get("stderr") or "").strip()
    r["ok"] = r.get("exit_code") in ok_codes
    return r


async def _must(place, cwd: str, identity, *argv: str) -> str:
    r = await _git(place, cwd, identity, *argv)
    if not r["ok"]:
        raise BuildRefused(f"git {argv[0]} said: {(r['err'] or r['out'])[:300] or 'it failed'}", 409)
    return r["out"]


def _identity(owner: Optional[str]) -> Dict[str, str]:
    from core.database import SessionLocal
    from src import git_accounts as G
    from src.agent_tools.git_tools import NO_IDENTITY
    db = SessionLocal()
    try:
        ident = G.identity(db, owner)
    finally:
        db.close()
    if not ident:
        raise BuildRefused(NO_IDENTITY.replace("then commit again", "then build again"), 409)
    return ident


def _join(place, *parts: str) -> str:
    if place.in_workstation:
        return posixpath.normpath(posixpath.join(*parts))
    return os.path.normpath(os.path.join(*parts))


# ── the record, in design.json ──────────────────────────────────────────────

async def _meta(fs: _Fs, slug: str) -> Dict[str, Any]:
    try:
        return json.loads(await fs.read(f"{DESIGN_DIR}/{slug}/{META}") or b"{}")
    except (DesignFileRefused, ValueError):
        raise BuildRefused("There is no such design in this project.", 404) from None


async def _open_design(owner: Optional[str], project: str, slug: str):
    """`(fs, meta)` for the design — `project` may be the build folder itself
    (the chat's workspace while the agent works there): it is answered as the
    project it was made from, the first worktree git lists."""
    fs = await _Fs(owner, project).open()
    try:
        return fs, await _meta(fs, slug)
    except BuildRefused:
        place = await _place(owner)
        r = await _git(place, fs.root, None, "worktree", "list", "--porcelain")
        main = next((ln[len("worktree "):] for ln in r["out"].splitlines() if ln.startswith("worktree ")), "")
        if not r["ok"] or not main or main.rstrip("/") == fs.root.rstrip("/"):
            raise
        fs = await _Fs(owner, main).open()
        return fs, await _meta(fs, slug)


async def _keep(fs: _Fs, slug: str, meta: Dict[str, Any]) -> None:
    await fs.write(f"{DESIGN_DIR}/{slug}/{META}", json.dumps(meta, indent=2).encode())


# ── the brief ───────────────────────────────────────────────────────────────

def brief_text(*, name: str, kind: str, brief: str, slug: str, branch: str, base: str, base_sha: str,
               design_folder: str, pages: List[str], tokens_css: str, system_name: str,
               notes: List[Dict[str, Any]], acceptance: str) -> str:
    """`BUILD.md`: what the agent follows. Plain words; every path whole."""
    lines = [f"# Build: {name}", "",
             f"This folder is the branch `{branch}`, made from `{base}` at {base_sha[:12]}. "
             "Work here, and only here.", "",
             "## What it is", "", f"A {kind or 'design'}." + (f" {brief.strip()}" if brief.strip() else ""), "",
             "## Screens", "",
             f"The design lives in {design_folder} — read it there; do not change it. Its pages:"]
    lines += [f"- {design_folder}/{p}" for p in pages] or ["- (no page yet: build from the brief above)"]
    lines += ["", "## Tokens", ""]
    if tokens_css.strip():
        lines += [f"The design system “{system_name}”. Use these values, as CSS variables where the project "
                  "has CSS:", "", "```css", tokens_css.strip(), "```"]
    else:
        lines += ["No design system is named: take the values from the design's own pages."]
    lines += ["", "## Notes", ""]
    if notes:
        for n in notes:
            about = f" (about `{n['selector']}`)" if n.get("selector") else ""
            lines.append(f"- {n['author']}{about}: {n['text']}")
    else:
        lines.append("No notes.")
    lines += ["", "## Acceptance", ""]
    lines += [f"- {a.strip().lstrip('-').strip()}" for a in acceptance.splitlines() if a.strip()]
    lines += [f"- The project's own pages show what {design_folder}/ shows, in the project's own code.",
              f"- Every change is committed with the git tool on `{branch}`, in this folder.",
              f"- Never switch this folder to `{base}`, never merge, never push `{base}`: merging is the "
              "person's, and they are asked.",
              "- Start the project from this folder so it can be previewed, and say the address it is at."]
    return "\n".join(lines) + "\n"


# ── start ───────────────────────────────────────────────────────────────────

async def start(owner: Optional[str], project: str, slug: str, *, base: Any = None,
                acceptance: Any = "", system_css: str = "", system_name: str = "",
                notes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Make the branch and its folder, write and commit the brief, and keep
    the record. Nothing on the base branch moves."""
    slug = _clean_slug(slug)
    acceptance = str(acceptance or "")[:ACCEPTANCE_MAX]
    fs = await _Fs(owner, project).open()
    meta = await _meta(fs, slug)
    if (meta.get("build") or {}).get("status") == "open":
        raise BuildRefused(f"This design is being built already, on {meta['build']['branch']}. Merge or close "
                           "that build first.", 409)
    ident = _identity(owner)
    place = await _place(owner)
    top = await _git(place, fs.root, None, "rev-parse", "--show-toplevel")
    root = top["out"] if top["ok"] else ""
    if not root:
        raise BuildRefused(f"{project} is not a git repository. Make it one (git init, a first commit), "
                           "then build again.", 409)
    if base:
        base = str(base).strip()
        from src.agent_tools.git_tools import _BRANCH_RE
        if not _BRANCH_RE.match(base):
            raise BuildRefused(f"“{base[:60]}” is not a branch name git accepts.")
    else:
        got = await _git(place, root, None, "symbolic-ref", "--short", "-q", "HEAD")
        if not got["ok"] or not got["out"]:
            raise BuildRefused("Your project is not on a branch (a detached HEAD). Say which branch to build "
                               "from.", 409)
        base = got["out"]
    base_sha = (await _git(place, root, None, "rev-parse", "--verify", "-q", f"refs/heads/{base}"))
    if not base_sha["ok"]:
        raise BuildRefused(f"There is no branch {base} in {project}.", 404)
    base_sha = base_sha["out"]
    branch = BRANCH_PREFIX + slug
    if (await _git(place, root, None, "rev-parse", "--verify", "-q", f"refs/heads/{branch}"))["ok"]:
        # A branch an earlier build left, already in the base, is taken down
        # for the new one (`git branch -d` deletes only what is merged); any
        # other branch of that name is somebody's work, and stays.
        old = meta.get("build") or {}
        merged = (await _git(place, root, None, "merge-base", "--is-ancestor", branch, base))["ok"]
        if old.get("branch") == branch and old.get("status") in ("merged", "closed") and merged:
            if not old.get("folder_removed"):
                raise BuildRefused("The last build's folder is still there. Remove it (Remove the build folder), "
                                   "then build again.", 409)
            await _must(place, root, None, "branch", "-d", branch)
        else:
            raise BuildRefused(f"The branch {branch} exists already and is not in {base}. Merge or delete it, "
                               "then build again.", 409)
    parent, name = (posixpath.split(root.rstrip("/")) if place.in_workstation else os.path.split(root))
    worktree = _join(place, parent, f"{name}--design-{slug}")
    if place.in_workstation:
        from src.agent_tools.workstation_tools import within
        if not within(worktree, place.home):
            raise BuildRefused(f"The build folder would be {worktree}, outside your home. Keep the project in "
                               "a folder of its own under your home.", 409)
    await _must(place, root, ident, "worktree", "add", "-b", branch, "--", worktree, base)

    design_folder = _join(place, fs.root, DESIGN_DIR, slug)
    pages = sorted(e["path"] for e in await fs.list(f"{DESIGN_DIR}/{slug}")
                   if e["path"].endswith(".html") and e["path"].split("/", 1)[0] not in (".versions", "variants"))
    text = brief_text(name=str(meta.get("name") or slug), kind=str(meta.get("kind") or ""),
                      brief=str(meta.get("brief") or ""), slug=slug, branch=branch, base=base,
                      base_sha=base_sha, design_folder=design_folder, pages=pages, tokens_css=system_css,
                      system_name=system_name, notes=notes or [], acceptance=acceptance)
    wfs = await _Fs(owner, worktree).open()
    await wfs.write(f"{DESIGN_DIR}/{slug}/BUILD.md", text.encode("utf-8"))
    await _must(place, worktree, ident, "add", "--", f"{DESIGN_DIR}/{slug}/BUILD.md")
    await _must(place, worktree, ident, "commit", "--message", f"Design brief: {meta.get('name') or slug}")
    record = {"branch": branch, "base": base, "base_sha": base_sha, "worktree": worktree, "project": root,
              "status": "open", "started": time.time(), "preview": ""}
    meta["build"] = record
    await _keep(fs, slug, meta)
    return {**record, "brief": f"{DESIGN_DIR}/{slug}/BUILD.md", "message": chat_message(meta, record, slug)}


def chat_message(meta: Dict[str, Any], record: Dict[str, Any], slug: str) -> str:
    """The one message the window sends to start the work."""
    return (f"Build the design “{meta.get('name') or slug}” on the branch {record['branch']}, in "
            f"{record['worktree']}: follow {DESIGN_DIR}/{slug}/BUILD.md there. Commit with the git tool on "
            f"{record['branch']} only — never switch to {record['base']} and never merge; merging is mine, and "
            "I will be asked. When it runs, start it from that folder and tell me the address so I can preview it.")


# ── status ──────────────────────────────────────────────────────────────────

async def status(owner: Optional[str], project: str, slug: str) -> Dict[str, Any]:
    """The build as the window shows it: the branch, its commits and changes
    since the base, whether the base moved, whether the folder has work not
    committed. `{build: None}` when the design has never been built."""
    slug = _clean_slug(slug)
    fs, meta = await _open_design(owner, project, slug)
    rec = meta.get("build")
    if not rec:
        return {"build": None}
    out: Dict[str, Any] = {"build": rec}
    if rec.get("status") != "open":
        return out
    place = await _place(owner)
    root, branch, base = rec["project"], rec["branch"], rec["base"]
    log = await _git(place, root, None, "log", "--date=short", "--pretty=format:%h %ad %an  %s", f"{base}..{branch}")
    out["commits"] = [ln for ln in log["out"].splitlines() if ln.strip()] if log["ok"] else []
    stat = await _git(place, root, None, "diff", "--stat", f"{base}...{branch}")
    out["changes"] = stat["out"] if stat["ok"] else ""
    now = await _git(place, root, None, "rev-parse", "--verify", "-q", f"refs/heads/{base}")
    out["base_moved"] = bool(now["ok"] and now["out"] != rec["base_sha"])
    dirty = await _git(place, rec["worktree"], None, "status", "--porcelain")
    out["uncommitted"] = len([ln for ln in dirty["out"].splitlines() if ln.strip()]) if dirty["ok"] else None
    out["folder_exists"] = dirty["ok"]
    return out


async def set_preview(owner: Optional[str], project: str, slug: str, address: Any) -> Dict[str, Any]:
    """The address the person previews the branch at — kept with the build."""
    slug = _clean_slug(slug)
    text = str(address or "").strip()
    if text and (len(text) > 300 or any(c.isspace() for c in text)):
        raise BuildRefused("That is not an address, such as localhost:5173.")
    fs, meta = await _open_design(owner, project, slug)
    if not meta.get("build"):
        raise BuildRefused("This design has not been built.", 404)
    meta["build"]["preview"] = text
    await _keep(fs, slug, meta)
    return {"preview": text}


# ── merge: the person's yes ─────────────────────────────────────────────────

async def merge(owner: Optional[str], project: str, slug: str, *, yes: Any) -> Dict[str, Any]:
    """Merge the branch into its base — only with `yes is True`, which only
    the person's press sends. Refused in a sentence when the project folder
    is not on the base, has changes of its own, or the build folder has work
    not committed; a conflict aborts and names the files."""
    if yes is not True:
        raise BuildRefused("Merging asks you first. Nothing was merged.", 400)
    slug = _clean_slug(slug)
    fs, meta = await _open_design(owner, project, slug)
    rec = meta.get("build") or {}
    if rec.get("status") != "open":
        raise BuildRefused("There is no open build of this design to merge.", 409)
    ident = _identity(owner)
    place = await _place(owner)
    root, branch, base = rec["project"], rec["branch"], rec["base"]
    on = await _git(place, root, None, "symbolic-ref", "--short", "-q", "HEAD")
    if not on["ok"] or on["out"] != base:
        raise BuildRefused(f"Your project folder is on {on['out'] or 'no branch'}, not {base}. Switch it back to "
                           f"{base}, then merge again. Nothing was merged.", 409)
    if not (await _git(place, root, None, "diff", "--quiet", "HEAD"))["ok"]:
        raise BuildRefused(f"Your project folder has changes of its own on {base}. Commit or put them aside, then "
                           "merge again. Nothing was merged.", 409)
    dirty = await _git(place, rec["worktree"], None, "status", "--porcelain")
    if dirty["ok"] and dirty["out"].strip():
        raise BuildRefused("The build folder has changes that are not committed, so they would not be merged. "
                           "Ask the agent to commit them, then merge again. Nothing was merged.", 409)
    ahead = await _git(place, root, None, "rev-list", "--count", f"{base}..{branch}")
    if ahead["ok"] and ahead["out"].strip() == "0":
        raise BuildRefused(f"{branch} has nothing {base} does not have. Nothing was merged.", 409)
    m = await _git(place, root, ident, "merge", "--no-ff", "--no-edit", "-m",
                   f"Merge {branch}: {meta.get('name') or slug}", branch)
    if not m["ok"]:
        conflicted = await _git(place, root, None, "diff", "--name-only", "--diff-filter=U")
        await _git(place, root, None, "merge", "--abort")
        files = [f for f in conflicted["out"].splitlines() if f.strip()][:20]
        said = (f" It conflicts in {', '.join(files)}." if files else
                f" git said: {(m['err'] or m['out'])[:200]}")
        raise BuildRefused(f"{branch} does not merge cleanly into {base}.{said} The merge was undone; nothing "
                           "changed. Ask the agent to bring the branch up to date, then merge again.", 409)
    sha = await _must(place, root, None, "rev-parse", "HEAD")
    rec.update({"status": "merged", "merged_sha": sha, "merged_at": time.time(), "merged_by": owner})
    meta["build"] = rec
    await _keep(fs, slug, meta)
    return {"merged": True, "into": base, "sha": sha, "build": rec}


async def close(owner: Optional[str], project: str, slug: str) -> Dict[str, Any]:
    """Remove the build folder. The branch stays: closing is not deleting work."""
    slug = _clean_slug(slug)
    fs, meta = await _open_design(owner, project, slug)
    rec = meta.get("build") or {}
    if not rec:
        raise BuildRefused("This design has not been built.", 404)
    place = await _place(owner)
    if rec.get("worktree"):
        dirty = await _git(place, rec["worktree"], None, "status", "--porcelain")
        if dirty["ok"] and dirty["out"].strip() and rec.get("status") == "open":
            raise BuildRefused("The build folder has changes that are not committed; closing would lose them. "
                               "Ask the agent to commit them first.", 409)
        await _git(place, rec["project"], None, "worktree", "remove", "--force", "--", rec["worktree"])
    if rec.get("status") == "open":
        rec["status"] = "closed"
    rec["folder_removed"] = True
    meta["build"] = rec
    await _keep(fs, slug, meta)
    return {"build": rec}


__all__ = ["BuildRefused", "start", "status", "merge", "close", "set_preview", "brief_text", "chat_message"]
