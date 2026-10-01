# SPDX-License-Identifier: AGPL-3.0-or-later
"""Workspace API - browse server directories to pick a tool workspace folder.

`B968` (`D-2026-10-01-01`): with the workstation on for the person asking —
`workstation_access.routes_tools`, the question the dispatcher asks before a
shell or file tool runs — the folders are the ones in their workstation home,
because that is where those tools work. Anyone that answer is yes for may
browse there: it maps their own home, not this machine. With the workstation
off, both routes answer exactly as before, admin-gated (`Law 1`).
"""
import os
import posixpath
from typing import Dict, Optional

from fastapi import APIRouter, Request, HTTPException, Query

from src.auth_helpers import get_current_user
from src.tool_security import owner_is_admin_or_single_user

# Cap entries returned per directory (mirrors filesystem_tools._CODENAV_MAX_HITS).
# A huge directory shouldn't dump thousands of rows into the picker; the user can
# type/paste a path to jump straight in instead.
_MAX_BROWSE_DIRS = 500


def _in_workstation(request: Request, owner: Optional[str]) -> bool:
    from src.workstation_access import routes_tools
    state = getattr(getattr(request, "app", None), "state", None)
    return routes_tools(owner, auth_manager=getattr(state, "auth_manager", None))


def _from_loop(fn, *args):
    """Run a coroutine function on the app's event loop from this endpoint's
    worker thread. The two endpoints stay plain functions, so the host answer
    is the code it was; the workstation's client is async."""
    import anyio.from_thread
    from src.workstation_client import WorkstationError
    try:
        return anyio.from_thread.run(fn, *args)
    except WorkstationError as e:
        from routes.workstation_routes import _http_error
        raise _http_error(e)


async def _browse_workstation(owner: Optional[str], raw: str) -> Dict:
    """The host answer's shape, for a folder in the person's workstation home,
    plus `where` and `home`. Never above the home: with `sudo` on the daemon
    would list `/`, and the owner's call is a folder in the home."""
    from src.agent_tools.workstation_tools import _home_path, _sensitive, within
    from src.workstation_access import sync_config, workstation_for
    from src.workstation_client import WorkstationError
    client, account = workstation_for(owner)
    # `B987`: the admin's `sudo` and network pushed first, as every tool call
    # does — this reads files through the daemon, and the daemon's jail is
    # whatever it was last told. (The answer stays in the home either way.)
    await sync_config(client)
    home = await _home_path(client, account)
    target = home
    text = (raw or "").strip()
    if text:
        try:
            got = str((await client.list(account, text, max_entries=0))["path"])
            if within(got, home):
                target = got
        except WorkstationError as e:
            # Not a folder there (or outside the home): the home instead, as
            # the host answer falls back to `~` for a path that is not a folder.
            if e.code not in ("not_found", "outside_home", "forbidden", "bad_request"):
                raise
    listing = await client.list(account, target)
    dirs = sorted(({"name": e["path"], "path": posixpath.join(target, e["path"])}
                   for e in listing.get("entries") or ()
                   if e.get("type") == "dir" and not str(e.get("path", "")).startswith(".")),
                  key=lambda d: d["name"].lower())
    return {
        "path": target,
        "parent": posixpath.dirname(target) if target != home else None,
        "dirs": dirs[:_MAX_BROWSE_DIRS],
        "truncated": bool(listing.get("truncated")) or len(dirs) > _MAX_BROWSE_DIRS,
        "selectable": not _sensitive(target),
        "where": "workstation",
        "home": home,
    }


async def _vet_workstation(owner: Optional[str], raw: str) -> Dict:
    from src.agent_tools.workstation_tools import vet_workspace
    from src.workstation_access import sync_config, workstation_for
    await sync_config(workstation_for(owner)[0])   # `B987`, as `_browse_workstation`
    path = await vet_workspace(owner, raw)
    return {"ok": path is not None, "path": path, "where": "workstation"}


def setup_workspace_routes():
    router = APIRouter(prefix="/api/workspace", tags=["workspace"])

    @router.get("/browse")
    def browse(request: Request, path: str = Query(default="")):
        """List subdirectories of `path` (default: home) so the UI can navigate
        the server filesystem and pick a workspace folder. Directories only.

        ADMIN-ONLY: this enumerates the server filesystem, so it is gated the
        same way the file/shell tools are (read_file/write_file/bash are in
        NON_ADMIN_BLOCKED_TOOLS). A non-admin who can't use those tools must not
        be able to map the host's directory tree either.

        With the workstation on for the caller, the folders in their
        workstation home instead (`B968`; the module docstring).
        """
        owner = get_current_user(request)
        if _in_workstation(request, owner):
            return _from_loop(_browse_workstation, owner, path)
        if not owner_is_admin_or_single_user(owner):
            raise HTTPException(status_code=403, detail="Workspace browsing is admin-only")

        # Resolve symlinks so the reported path is canonical and the UI navigates
        # real directories (defends against symlink games in displayed paths).
        target = os.path.realpath(os.path.expanduser(path.strip() or "~"))
        if not os.path.isdir(target):
            target = os.path.realpath(os.path.expanduser("~"))

        dirs = []
        try:
            with os.scandir(target) as it:
                for entry in it:
                    try:
                        # Don't follow symlinks when classifying - a symlinked
                        # dir is skipped rather than letting the browser wander
                        # off via a link. Hidden entries are omitted.
                        if entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                            # Build the child path server-side with os.path.join
                            # so it's correct on Windows (backslashes) and Linux.
                            dirs.append({"name": entry.name, "path": os.path.join(target, entry.name)})
                    except OSError:
                        continue
        except (PermissionError, OSError):
            dirs = []

        dirs_sorted = sorted(dirs, key=lambda d: d["name"].lower())
        truncated = len(dirs_sorted) > _MAX_BROWSE_DIRS
        parent = os.path.dirname(target)
        from src.tool_execution import vet_workspace
        return {
            "path": target,
            "parent": parent if parent and parent != target else None,
            "dirs": dirs_sorted[:_MAX_BROWSE_DIRS],
            "truncated": truncated,
            # Whether this directory may be bound as a workspace (filesystem
            # roots and sensitive dirs may be browsed through but not chosen).
            "selectable": vet_workspace(target) is not None,
        }

    @router.get("/vet")
    def vet(request: Request, path: str = Query(default="")):
        """Validate a workspace path without binding it.

        The UI calls this before persisting a manually typed path (/workspace
        set) so a typo, file path, deleted folder, sensitive dir, or filesystem
        root is rejected up front with the canonical path returned on success,
        instead of being stored client-side and silently dropped at chat time.
        Admin-gated like /browse: it confirms path existence on the host.
        """
        owner = get_current_user(request)
        if _in_workstation(request, owner):
            return _from_loop(_vet_workstation, owner, path)
        if not owner_is_admin_or_single_user(owner):
            raise HTTPException(status_code=403, detail="Workspace selection is admin-only")
        from src.tool_execution import vet_workspace
        resolved = vet_workspace(path)
        return {"ok": resolved is not None, "path": resolved}

    return router
