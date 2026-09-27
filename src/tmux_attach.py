# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B909` — the one place an "attach to this tmux session" command is built.

The Forge's **Copy tmux** used to put `tmux attach -t <session>` on the
clipboard, built in the browser. On the shipped Docker install that command
cannot work anywhere a person can type it:

  * on the host it names nothing — the session lives inside the container;
  * inside the container it still fails, because tmux keeps one socket per user
    (`/tmp/tmux-<uid>/default`), the image has no `USER` so `docker exec` is
    root, and the app runs as `PUID` under `gosu` (`docker/entrypoint.sh`).
    Root's `tmux attach` answers *"no server running on /tmp/tmux-0/default"*.

What works in a container is `docker compose exec -u <uid> pantheon tmux attach
…`, and only the server can fill that in: it knows whether it runs in a
container (`running_in_container()`, reused rather than re-derived — `Law 14`)
and the uid its sessions belong to (`os.getuid()`). It does **not** know the
container's name, so the plain-`docker` form carries a visible `<container>`
placeholder rather than a guess, and the note says *if* you run it with
Compose rather than asserting that you do.

So the command is built here, once, and every surface reads it — the Forge's
menu through `GET /api/shell/tmux-attach` (`routes/shell_routes.py`), and
`P4-15`'s attach affordance for the agent's own shell when that can exist
(`B908`). A copyable command only: no listener, no web terminal, no remote
shell (`Law 16`, `Law 17`).

**The `-t` value is exact.** tmux resolves a session target by exact name, then
by *prefix*: measured on tmux 3.4, with only `serve-10` alive, `-t serve-1`
lands in `serve-10`. A command that names one session must not open another,
so the target carries tmux's own exact-match prefix, `=`. And tmux stores `.`
and `:` in a session name as `_` (`session_check_name`), while `-t a.b` reads
`.b` as a pane — so the target is the name tmux actually holds (`B908` measured
the same rewrite for the agent's `pan-agent-` sessions).
"""

from __future__ import annotations

import os
import shlex
from typing import Dict, Optional

from src.host_docker_access import running_in_container

#: `where` — which of the three cases the command is for. An enum, not a
#: boolean (`Law 10`): "remote" and "in a container" are independent facts, and
#: a flag named for one of them would be read as the other.
WHERE_CONTAINER = "container"
WHERE_NATIVE = "native"
WHERE_REMOTE = "remote"

#: The service name in all three shipped compose files — `docker-compose.yml`
#: and both `docker-compose.gpu-*.yml`. `docs/setup.md` already tells people to
#: run `docker compose exec pantheon …` from the same folder.
COMPOSE_SERVICE = "pantheon"

#: What the plain-`docker` form prints where the container's name goes. The
#: server cannot know it (a Compose project names it `<folder>-pantheon-1`; a
#: `docker run` names it whatever was typed), and a guess that is wrong attaches
#: to nothing while looking right. Pasted unedited, `<container>` is a shell
#: syntax error, so it fails before it runs anything.
CONTAINER_PLACEHOLDER = "<container>"

NOTE_COMPOSE = (
    "If you run Pantheon with Docker Compose, run this from the folder that "
    "holds docker-compose.yml."
)
NOTE_PLAIN_DOCKER = (
    f"With plain docker, put your container's name in place of "
    f"{CONTAINER_PLACEHOLDER}."
)
#: Attaching puts a person's keyboard on a live model server: Ctrl-c there stops
#: it. Detaching is the one keystroke that matters, so it is said every time.
NOTE_DETACH = "Detach with Ctrl-b then d to leave it running. Ctrl-c stops it."

#: Longest session name or host accepted. tmux has no limit of its own; this is
#: a bound on what a request can make the server echo back.
MAX_LENGTH = 256


def _refuse_control_characters(value: str, what: str) -> None:
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{what} contains a control character")
    if len(value) > MAX_LENGTH:
        raise ValueError(f"{what} is longer than {MAX_LENGTH} characters")


def tmux_target(session: str) -> str:
    """The `-t` value that names exactly this session, unquoted.

    `=` makes the match exact; `.` and `:` become `_`, as tmux itself rewrote
    them when it created the session. A name with a control character is
    refused rather than guessed at: tmux stores those escaped
    (`utf8_stravis`), and no session Pantheon creates carries one.
    """
    name = "" if session is None else str(session)
    if not name.strip():
        raise ValueError("session is required")
    _refuse_control_characters(name, "session")
    return "=" + name.replace(".", "_").replace(":", "_")


def _server_user() -> Optional[str]:
    """The login name this process runs as, or None when it cannot be told."""
    getuid = getattr(os, "getuid", None)
    if getuid is not None:
        try:
            import pwd

            return pwd.getpwuid(getuid()).pw_name
        except (ImportError, KeyError):
            # No passwd entry for this uid (an arbitrary `--user` in a
            # container): fall through to the environment's answer.
            pass
    try:
        import getpass

        return getpass.getuser() or None
    except (ImportError, KeyError, OSError):
        # getpass raises OSError (3.13+) or KeyError (through pwd, earlier)
        # when nothing names this uid; the note then says "the user Pantheon
        # runs as" instead of a name.
        return None


def _remote_note(host: str) -> str:
    user, _, hostname = host.rpartition("@")
    if user and hostname:
        return f"This session is on {hostname}. Log in there over SSH as {user}, then run this."
    return (
        f"This session is on {host}. Log in there over SSH as the user Pantheon "
        "connects as, then run this."
    )


def attach_command(
    session: str,
    *,
    remote_host: str = "",
    in_container: Optional[bool] = None,
    uid: Optional[int] = None,
    user: Optional[str] = None,
) -> Dict[str, object]:
    """How a person opens `session` in their own terminal.

    Returns ``{where, session, command, note, alternative, detach}``:

      * ``where`` — ``"container" | "native" | "remote"``;
      * ``session`` — the name as tmux holds it;
      * ``command`` — the one **Copy tmux** copies, the session quoted with
        `shlex.quote`;
      * ``note`` — one sentence: where to run it, and as whom;
      * ``alternative`` — ``{command, note}`` or None. Only a container has one:
        the plain-`docker` form, with `<container>` left for the person;
      * ``detach`` — how to leave without stopping it.

    ``remote_host`` is the task's SSH target (`task.remoteHost` in the Forge).
    A remote session belongs to the SSH user on that machine, so the bare
    command is right once logged in there, and the note says so rather than
    wrapping it in an `ssh` whose keys live on the Pantheon server, not on the
    person's machine. ``in_container``, ``uid`` and ``user`` default to what
    this process can see; they are parameters so a test can ask about the
    other cases.

    Raises ``ValueError`` for an empty session, or a session or host with a
    control character or longer than ``MAX_LENGTH``.
    """
    target = tmux_target(session)
    tmux = f"tmux attach -t {shlex.quote(target)}"
    result: Dict[str, object] = {
        "session": target[1:],
        "detach": NOTE_DETACH,
        "alternative": None,
    }

    host = "" if remote_host is None else str(remote_host).strip()
    if host:
        _refuse_control_characters(host, "host")
        result.update(where=WHERE_REMOTE, command=tmux, note=_remote_note(host))
        return result

    containerised = running_in_container() if in_container is None else bool(in_container)
    if containerised:
        if uid is None:
            getuid = getattr(os, "getuid", None)
            uid = getuid() if getuid is not None else None
        as_user = f"-u {int(uid)} " if uid is not None else ""
        result.update(
            where=WHERE_CONTAINER,
            command=f"docker compose exec {as_user}{COMPOSE_SERVICE} {tmux}",
            note=NOTE_COMPOSE,
            alternative={
                "command": f"docker exec -it {as_user}{CONTAINER_PLACEHOLDER} {tmux}",
                "note": NOTE_PLAIN_DOCKER,
            },
        )
        return result

    who = _server_user() if user is None else user
    result.update(
        where=WHERE_NATIVE,
        command=tmux,
        note=(
            f"Run this on the machine Pantheon runs on, logged in as {who}."
            if who
            else "Run this on the machine Pantheon runs on, logged in as the user Pantheon runs as."
        ),
    )
    return result
