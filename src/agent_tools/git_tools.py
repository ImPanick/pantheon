# SPDX-License-Identifier: AGPL-3.0-or-later
"""`git` — a person's own git, called by the agent. `P25-03`.

One call is one action — `status`, `diff`, `log`, `branch`, `commit`, `pull`,
`push` or `clone` — on one repository, run **where this person's shell runs**
(`P20-03`): in their workstation home when the workstation routes their tools,
otherwise on this machine for the people allowed its shell (admins: `git` sits
beside `bash` in the non-admin blocklist and is lifted with it,
`tool_security`, `workstation_tools.LIFTED_TOOLS`). A tool that reached further
than the shell already does would be a second door to the same room with a
different lock.

**As the person.** Every command carries their own identity (`user.name`,
`user.email`, Settings → Git, `src/git_accounts.py`) and, for a command that
reaches a host, their own token for **that host only** — read for this one
command and handed to this one process in its environment, where an inline
credential helper answers git with it only when git asks about that host. The
token is never written to a file, a remote URL or the home, and an output that
somehow repeats it has it replaced before anyone reads it.

**What each action is** (`tool_capabilities._ACTION_CAPABILITIES`): status,
diff and log read the repository; branch and commit change it; pull and clone
also reach a host; push is the one that changes something outside — it asks
first wherever the person's rung asks for that, and a hired agent asks too
(`D-2026-10-24-01`).

**Never.** Hooks and the file-system monitor are off for every command
(`core.hooksPath=/dev/null`, `core.fsmonitor=false`): a repository someone else
wrote cannot run code because the agent looked at it or committed in it. A clone is from `https://` only — a token belongs to a host by name, and a
`file://` or `ext::` URL is a way out of the room. A push never forces.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import posixpath
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

TOOL_NAME = "git"
ACTIONS: Tuple[str, ...] = ("status", "diff", "log", "branch", "commit", "pull", "push", "clone")
READ_ACTIONS = frozenset({"status", "diff", "log"})
REACHING_ACTIONS = frozenset({"pull", "push", "clone"})

TIMEOUT_S = 120.0
REACH_TIMEOUT_S = 600.0
LOG_MAX = 50
OUTPUT_MAX = 20_000
MESSAGE_MAX = 5_000
_BRANCH_RE = re.compile(r"^(?!-)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,100}(?<!\.lock)(?<!/)$")
_REMOTE_RE = re.compile(r"^[A-Za-z0-9._-]{1,50}$")
_SCP_RE = re.compile(r"^[A-Za-z0-9._-]+@([A-Za-z0-9.-]+):")

def _aliases() -> Dict[str, str]:
    """The spellings `git` accepts — the classifier's table, so the action the
    gate classified is the action that runs (`Law 7`)."""
    from src.tool_capabilities import _ACTION_ALIASES
    return dict(_ACTION_ALIASES.get(TOOL_NAME, {}))

# The helper git asks for a password: it answers only for the host this
# command was given a token for. `$PANTHEON_GIT_*` are this process's own
# environment; nothing is written anywhere.
_HELPER = ('!f() { [ "$1" = get ] || exit 0; h=; while IFS= read -r l; do case "$l" in host=*) '
           'h="${l#host=}";; "") break;; esac; done; [ -n "$PANTHEON_GIT_HOST" ] && '
           '[ "$h" = "$PANTHEON_GIT_HOST" ] || exit 0; echo "username=$PANTHEON_GIT_USER"; '
           'echo "password=$PANTHEON_GIT_TOKEN"; }; f')

NO_IDENTITY = ("Your commits need a name and an email first. Set them in Settings → Git, then "
               "commit again.")


class _GitProblem(ValueError):
    pass


def _bool(v: Any) -> bool:
    """A yes/no argument from the model: the tools' one rule (`env_flags`)."""
    from src.env_flags import tool_arg_truthy
    return tool_arg_truthy(v)


def parse_args(content: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """`(arguments, problem)`, the action de-aliased and every field checked."""
    if isinstance(content, dict):
        raw: Any = dict(content)
    else:
        text = str(content or "").strip()
        if not text:
            return {}, f"`git` needs an action: one of {', '.join(ACTIONS)}."
        if text.startswith("{"):
            try:
                raw = json.loads(text)
            except ValueError:
                return {}, ('`git` arguments are a JSON object, such as '
                            '{"action": "status", "repo": "my-project"}.')
        else:
            raw = {"action": text.split()[0]}
    if not isinstance(raw, dict):
        return {}, "`git` arguments are a JSON object."
    a = dict(raw)
    action = str(a.get("action") or "").strip().lower().replace("-", "_")
    action = _aliases().get(action, action)
    if action not in ACTIONS:
        return {}, f"“{a.get('action')}” is not a `git` action. It is one of {', '.join(ACTIONS)}."
    a["action"] = action
    try:
        if a.get("repo") is not None and not isinstance(a.get("repo"), str):
            raise _GitProblem("“repo” is a folder, as a path.")
        if action == "log":
            n = a.get("limit", 10)
            n = int(n) if str(n).strip().lstrip("-").isdigit() else 10
            a["limit"] = max(1, min(LOG_MAX, n))
        if action == "branch" and a.get("name") is not None:
            if not _BRANCH_RE.match(str(a["name"])):
                raise _GitProblem(f"“{a['name']}” is not a branch name git accepts.")
        if action == "commit":
            msg = str(a.get("message") or "").strip()
            if not msg:
                raise _GitProblem("A commit needs a message: say what changed and why.")
            if len(msg) > MESSAGE_MAX:
                raise _GitProblem(f"A commit message is at most {MESSAGE_MAX:,} characters.")
            a["message"] = msg
            files = a.get("files")
            if files is not None:
                if isinstance(files, str):
                    files = [files]
                if not isinstance(files, list) or not all(isinstance(f, str) and f.strip() for f in files):
                    raise _GitProblem("“files” is a list of paths in the repository.")
                if any(f.startswith("-") for f in files):
                    raise _GitProblem("A path to commit does not start with “-”.")
                a["files"] = [f.strip() for f in files][:200]
        if action in ("pull", "push"):
            remote = str(a.get("remote") or "origin")
            if not _REMOTE_RE.match(remote):
                raise _GitProblem(f"“{remote}” is not a remote's name.")
            a["remote"] = remote
            if a.get("branch") is not None and not _BRANCH_RE.match(str(a["branch"])):
                raise _GitProblem(f"“{a['branch']}” is not a branch name git accepts.")
        if action == "clone":
            url = str(a.get("url") or "").strip()
            parts = urlsplit(url)
            if parts.scheme != "https" or not parts.hostname:
                raise _GitProblem("A clone is from an https:// address, like "
                                 "https://github.com/owner/project.git.")
            if parts.username or parts.password:
                raise _GitProblem("Give the address without a user or token in it; your token for "
                                 "that host is used from Settings → Git.")
            a["url"] = url
            into = a.get("into")
            if into is not None and (not isinstance(into, str) or not into.strip()
                                     or into.strip().startswith("-")):
                raise _GitProblem("“into” is the folder to clone into.")
    except _GitProblem as p:
        return {}, str(p)
    return a, None


def describe(args: Dict[str, Any]) -> str:
    """One line a person reads on the card: *commit “Fix the footer”*."""
    action = args.get("action")
    repo = f" in {args['repo']}" if args.get("repo") else ""
    if action == "commit":
        m = args.get("message", "").splitlines()[0]
        return f"commit “{m if len(m) <= 60 else m[:59] + '…'}”{repo}"
    if action == "branch":
        if args.get("name"):
            return f"{'new branch' if _bool(args.get('create')) else 'switch to'} {args['name']}{repo}"
        return f"branches{repo}"
    if action in ("pull", "push"):
        b = f" {args['branch']}" if args.get("branch") else ""
        return f"{action} {args.get('remote', 'origin')}{b}{repo}"
    if action == "clone":
        return f"clone {args.get('url')}"
    if action == "log":
        return f"log, last {args.get('limit', 10)}{repo}"
    if action == "diff":
        return f"diff{' (staged)' if _bool(args.get('staged')) else ''}{repo}"
    return f"{action}{repo}"


def command_line(content: Any) -> str:
    args, problem = parse_args(content)
    return str(content or "").strip()[:200] if problem else describe(args)


def host_of(url: str) -> Optional[str]:
    """The host a remote URL reaches, for https and scp-style addresses."""
    url = (url or "").strip()
    m = _SCP_RE.match(url)
    if m:
        return m.group(1).lower()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if not parts.hostname:
        return None
    return parts.hostname.lower() + (f":{parts.port}" if parts.port else "")


def _git(identity: Optional[Dict[str, str]], *argv: str, helper: bool = False) -> str:
    """One git command line, with the settings every command carries."""
    pre = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
           "-c", "core.quotePath=false",
           "-c", "color.ui=false", "-c", "advice.detachedHead=false",
           "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
           "-c", "protocol.ssh.allow=always"]
    if identity:
        pre += ["-c", f"user.name={identity['name']}", "-c", f"user.email={identity['email']}"]
    if helper:
        pre += ["-c", "credential.helper=", "-c", f"credential.helper={_HELPER}"]
    return shlex.join(pre + list(argv))


def plan(args: Dict[str, Any], identity: Optional[Dict[str, str]]) -> List[str]:
    """The command lines this action runs, in order. Every argument the model
    sent reaches git as one quoted word, after `--` where it is a path."""
    action = args["action"]
    if action == "status":
        return [_git(identity, "status", "--short", "--branch")]
    if action == "diff":
        argv = ["diff", "--stat", "--patch"] + (["--cached"] if _bool(args.get("staged")) else [])
        if args.get("path"):
            argv += ["--", str(args["path"])]
        return [_git(identity, *argv)]
    if action == "log":
        return [_git(identity, "log", f"-{args['limit']}", "--date=short",
                     "--pretty=format:%h %ad %an  %s")]
    if action == "branch":
        name = args.get("name")
        if not name:
            return [_git(identity, "branch", "--all", "--verbose", "--no-abbrev")]
        if _bool(args.get("create")):
            return [_git(identity, "switch", "--create", str(name))]
        return [_git(identity, "switch", str(name))]
    if action == "commit":
        if not identity:
            raise _GitProblem(NO_IDENTITY)
        add = (["add", "--"] + args["files"]) if args.get("files") else ["add", "--all"]
        return [_git(identity, *add), _git(identity, "commit", "--message", args["message"]),
                _git(identity, "log", "-1", "--stat", "--pretty=format:%h %s")]
    if action == "pull":
        argv = ["pull", "--ff-only", args["remote"]] + ([str(args["branch"])] if args.get("branch") else [])
        return [_git(identity, *argv, helper=True)]
    if action == "push":
        argv = ["push", "--porcelain"]
        if _bool(args.get("set_upstream")):
            argv.append("--set-upstream")
        argv.append(args["remote"])
        argv.append(str(args["branch"]) if args.get("branch") else "HEAD")
        return [_git(identity, *argv, helper=True)]
    if action == "clone":
        argv = ["clone", "--", args["url"]] + ([args["into"].strip()] if args.get("into") else [])
        return [_git(identity, *argv, helper=True)]
    raise _GitProblem(f"`git` cannot {action}.")


def _scrub(text: str, secret: Optional[str]) -> str:
    text = str(text or "")
    if secret:
        text = text.replace(secret, "••••")
    if len(text) > OUTPUT_MAX:
        text = text[:OUTPUT_MAX // 2] + "\n… (cut) …\n" + text[-OUTPUT_MAX // 2:]
    return text


# ── where it runs ───────────────────────────────────────────────────────────

class _Place:
    """The person's shell: their workstation, or this machine."""

    def __init__(self, owner: Optional[str], station_workspace: Optional[str],
                 host_workspace: Optional[str] = None):
        self.owner = owner
        self.station_workspace = station_workspace
        self.host_workspace = host_workspace
        self.client = None
        self.account = None
        self.home = None
        # `P27-04`. The person's proxy and trusted file, for every command run
        # here (`src/vault_names.env_for`); empty on this machine.
        self.names_env: Dict[str, str] = {}

    async def open(self) -> Optional[Dict[str, Any]]:
        from src.workstation_access import routes_tools
        if not routes_tools(self.owner):
            return None
        from src.agent_tools.workstation_tools import _home_path
        from src.workstation_access import sync_config, workstation_for
        from src.workstation_client import WorkstationError
        try:
            self.client, self.account = workstation_for(self.owner)
            await sync_config(self.client)
            self.home = await _home_path(self.client, self.account)
        except WorkstationError as e:
            return e.as_result()
        from src import vault_names
        try:
            self.names_env = vault_names.env_for(await vault_names.sync(self.client, self.account, self.owner))
        except WorkstationError as e:
            # A daemon older than `P27-04` has no names route: commands run as
            # before, and a mapped name is said not to resolve in its own words.
            logger.info("names not applied for %s: %s", self.account, e.message)
        except Exception as e:  # noqa: BLE001 — names unread never stop a command; see above
            logger.warning("names not read for %s: %s", self.account, e)
        return None

    @property
    def in_workstation(self) -> bool:
        return self.client is not None

    def base(self) -> str:
        if self.in_workstation:
            return self.station_workspace or self.home
        if self.host_workspace:
            return self.host_workspace
        from src.tool_execution import agent_cwd
        return agent_cwd()

    def resolve(self, raw: Optional[str]) -> str:
        """The repository's folder: `raw` against the workspace, kept inside
        the person's home on the workstation."""
        if self.in_workstation:
            from src.agent_tools.workstation_tools import _sensitive, within
            path = posixpath.normpath(posixpath.join(self.base(), raw or "."))
            if raw and raw.startswith("~"):
                path = posixpath.normpath(posixpath.join(self.home, raw[1:].lstrip("/")))
            if not within(path, self.home):
                raise _GitProblem(f"{raw} is outside your home, so git does not work there.")
            if _sensitive(path):
                raise _GitProblem(f"{raw} is a folder git is not run in.")
            return path
        path = os.path.normpath(os.path.join(self.base(), os.path.expanduser(raw or ".")))
        return path

    async def run(self, command: str, cwd: str, env: Dict[str, str], timeout: float) -> Dict[str, Any]:
        base_env = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false", "SSH_ASKPASS": "/bin/false",
                    "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C.UTF-8"}
        if self.in_workstation:
            r = await self.client.exec(self.account, command, shell="bash", cwd=cwd,
                                       timeout_s=timeout, env={**base_env, **self.names_env, **env})
            return {"stdout": r.get("stdout") or "", "stderr": r.get("stderr") or "",
                    "exit_code": r.get("exit_code"), "timed_out": bool(r.get("timed_out"))}
        from src.agent_tools.subprocess_tools import _create_bash_subprocess, kill_tree, own_process_group
        proc = await _create_bash_subprocess(
            command, cwd=cwd, env={**os.environ, **base_env, **env},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **own_process_group())
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            kill_tree(proc)
            return {"stdout": "", "stderr": "", "exit_code": None, "timed_out": True}
        return {"stdout": out.decode("utf-8", "replace"), "stderr": err.decode("utf-8", "replace"),
                "exit_code": proc.returncode, "timed_out": False}


def _where(place: _Place) -> Dict[str, Any]:
    return {"ran_in": "workstation", "account": place.account} if place.in_workstation else {}


async def run_git(content: Any, *, owner: Optional[str], station_workspace: Optional[str] = None,
                  ) -> Dict[str, Any]:
    """Run one `git` action for `owner`. Answers a tool result."""
    from core.database import SessionLocal
    from src import git_accounts as G

    args, problem = parse_args(content)
    if problem:
        return {"error": problem, "exit_code": 1}
    place = _Place(owner, station_workspace)
    refused = await place.open()
    if refused is not None:
        return refused
    try:
        cwd = place.resolve(args.get("repo"))
    except _GitProblem as p:
        return {"error": str(p), "exit_code": 1, **_where(place)}

    db = SessionLocal()
    try:
        identity = G.identity(db, owner)
        env: Dict[str, str] = {}
        secret: Optional[str] = None
        host: Optional[str] = None
        if args["action"] in REACHING_ACTIONS:
            if args["action"] == "clone":
                host = host_of(args["url"])
            else:
                got = await place.run(_git(None, "remote", "get-url", "--", args["remote"]), cwd, {}, TIMEOUT_S)
                if got.get("exit_code") != 0:
                    return {"error": _scrub(got.get("stderr") or got.get("stdout") or
                                            f"There is no remote called {args['remote']}.", None).strip(),
                            "exit_code": 1, **_where(place)}
                host = host_of(got.get("stdout", "").strip().splitlines()[0] if got.get("stdout") else "")
            cred = G.credential_for(db, owner, host) if host else None
            if cred:
                env = {"PANTHEON_GIT_HOST": host, "PANTHEON_GIT_USER": cred[0], "PANTHEON_GIT_TOKEN": cred[1]}
                secret = cred[1]
        try:
            commands = plan(args, identity)
        except _GitProblem as p:
            return {"error": str(p), "exit_code": 1, **_where(place)}
    finally:
        db.close()

    timeout = REACH_TIMEOUT_S if args["action"] in REACHING_ACTIONS else TIMEOUT_S
    out_parts: List[str] = []
    for n, command in enumerate(commands):
        r = await place.run(command, cwd, env, timeout)
        stdout, stderr = _scrub(r.get("stdout"), secret), _scrub(r.get("stderr"), secret)
        if r.get("timed_out"):
            return {"error": f"git {args['action']} did not finish within {int(timeout)} seconds.",
                    "output": "\n".join(out_parts), "exit_code": 124, **_where(place)}
        if r.get("exit_code") != 0:
            said = (stderr or stdout).strip() or f"git {args['action']} failed."
            hint = ""
            if args["action"] in REACHING_ACTIONS and not secret and re.search(
                    r"Authentication failed|could not read Username|403|401|terminal prompts disabled", said):
                hint = (f" You have no token for {host or 'that host'} in Settings → Git; add one, "
                        "then try again.")
            if args["action"] == "commit" and n == 1 and "nothing to commit" in (stdout + stderr):
                return {"output": "Nothing to commit: the working tree is clean.", "exit_code": 0,
                        **_where(place)}
            return {"error": said + hint, "output": "\n".join(out_parts), "exit_code": r.get("exit_code") or 1,
                    **_where(place)}
        text = "\n".join(t for t in (stdout.strip(), stderr.strip()) if t)
        if text:
            out_parts.append(text)
    output = "\n".join(out_parts).strip()
    if not output:
        output = {"status": "Clean.", "diff": "No changes.", "log": "No commits yet.",
                  "pull": "Already up to date.", "push": "Pushed."}.get(args["action"], "Done.")
    result = {"output": output, "exit_code": 0, "repo": cwd, **_where(place)}
    if args["action"] in REACHING_ACTIONS and host:
        result["host"] = host
        result["as"] = "your token" if secret else "no token"
    return result


# ── the repositories a person has (`P25-04`'s *Git ›*) ──────────────────────

REPOS_MAX = 50
_LIST = ('find . -maxdepth 4 -type d -name .git -prune 2>/dev/null | head -n {n} | '
         'while IFS= read -r g; do r="${{g%/.git}}"; '
         'b=$({git} -C "$r" symbolic-ref --short -q HEAD || {git} -C "$r" rev-parse --short HEAD 2>/dev/null); '
         'c=$({git} -C "$r" status --porcelain 2>/dev/null | wc -l); '
         'printf "%s\\t%s\\t%s\\n" "$r" "$b" "$c"; done')


async def list_repos(owner: Optional[str], *, station_workspace: Optional[str] = None,
                     host_workspace: Optional[str] = None) -> Dict[str, Any]:
    """`{repos: [{path, name, branch, changes}], where, base}` — the git
    repositories four folders deep under where this person's shell starts —
    or `{error}` with the sentence why not."""
    place = _Place(owner, station_workspace, host_workspace)
    refused = await place.open()
    if refused is not None:
        return {"error": refused.get("error") or "Your workstation did not answer."}
    if not place.in_workstation:
        # The dispatcher's own question for a blocked tool on this machine
        # (`tool_execution`), not a second one (`check-auth-map.py`).
        from src.tool_execution import _owner_is_admin
        if not _owner_is_admin(owner):
            return {"error": "Git runs where your shell runs, and you have no shell here yet: an "
                             "admin can switch the workstation on for you in Settings → Workstation."}
    base = place.base()
    git = shlex.join(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"])
    r = await place.run(_LIST.format(n=REPOS_MAX, git=git), base, {}, TIMEOUT_S)
    repos = []
    for line in str(r.get("stdout") or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        rel = parts[0][2:] if parts[0].startswith("./") else parts[0]
        rel = rel or "."
        full = posixpath.normpath(posixpath.join(base, rel)) if place.in_workstation \
            else os.path.normpath(os.path.join(base, rel))
        repos.append({"path": rel, "abs": full,
                      "name": posixpath.basename(rel.rstrip("/")) if rel != "." else posixpath.basename(base),
                      "branch": parts[1] or None,
                      "changes": int(parts[2]) if parts[2].strip().isdigit() else 0})
    repos.sort(key=lambda x: x["path"].lower())
    return {"repos": repos, "where": "workstation" if place.in_workstation else "server", "base": base}


class GitTool:
    """The registry's handler: the dispatcher calls `run_git` by name with the
    turn's owner and workspace; this answers a call that reaches it another
    way, with the owner in `ctx`."""

    async def execute(self, content: str, ctx: Optional[dict] = None) -> Dict[str, Any]:
        return await run_git(content, owner=(ctx or {}).get("owner"))
