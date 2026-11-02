# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1478`, `D-2026-10-25-04` §3 — an admin controls the workstation's containers.

The owner: *"The backend should have a real switch — because the admins should
be able to control this container and then (in the future) have access to the
other endpoints and direct shell access and commands to."*

Until this, Settings → Workstation → *Backend* changed only wording: which kind
of workstation runs was decided by the compose overlay in `.env`, and Pantheon
holds no Docker socket. This module is the part that can act, and only where the
operator has given Pantheon the means — `docker/host-docker.yml`, the Forge's
existing opt-in (`src/host_docker_access.py`), which is broad control of the
host's Docker daemon and is never switched on by Pantheon itself.

**What it touches.** Only containers of Pantheon's own compose project — the
project label on Pantheon's own container — whose service is one of the
workstation's (`SERVICES`). It never creates, removes, pulls or builds: it
lists them, starts, stops and restarts them, reads their logs, and switches the
backend by starting one kind's services and stopping the other's. A backend
whose containers do not exist yet is a sentence naming the overlay to add, not
an attempt to make them.

**How.** The Docker Engine API over the unix socket, with the standard library:
no SDK, no CLI, no compose plugin in the image. Every call is a short request on
a local socket; nothing here leaves the host.
"""

from __future__ import annotations

import http.client
import json
import socket
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from src.host_docker_access import HOST_DOCKER_SOCKET_PATH, host_docker_access_enabled

API_VERSION = "v1.41"          # Docker 20.10+, every engine still supported
PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"

#: The workstation's services, by the backend they make up. `workstation-net`
#: holds the container backend's network namespace (`P20-06`) and starts with
#: it; the VM backend's service is `workstation-vm` when both backends are
#: configured side by side (`docker/workstation-both.yml`), and `workstation`
#: when the VM overlay is used alone — the daemon's own `health.backend` says
#: which a running `workstation` is.
SERVICES = {
    "container": ("workstation-net", "workstation"),
    "vm": ("workstation-vm",),
}
ALL_SERVICES = tuple(dict.fromkeys(s for group in SERVICES.values() for s in group))
ACTIONS = ("start", "stop", "restart")

ENABLE_SENTENCE = (
    "Pantheon can't start or stop the workstation here: it has no access to the host's Docker. "
    "To give it that, add docker/host-docker.yml to COMPOSE_FILE in .env (broad control of the "
    "host's Docker — the Forge uses the same opt-in) and run `docker compose up -d`."
)


class DockerControlError(Exception):
    """A request the daemon refused or could not answer, as a sentence."""


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float = 10.0):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:  # noqa: D401 — http.client's hook
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


class DockerAPI:
    """The few Engine API calls this module makes, over one unix socket."""

    def __init__(self, socket_path: str = HOST_DOCKER_SOCKET_PATH, timeout: float = 10.0):
        self.socket_path = socket_path
        self.timeout = timeout

    def _request(self, method: str, path: str, *, timeout: Optional[float] = None) -> tuple:
        conn = _UnixConnection(self.socket_path, timeout=timeout or self.timeout)
        try:
            conn.request(method, f"/{API_VERSION}{path}", headers={"Host": "docker"})
            res = conn.getresponse()
            return res.status, res.read()
        except OSError as exc:
            raise DockerControlError(f"The host's Docker didn't answer ({exc.__class__.__name__}).") from exc
        finally:
            conn.close()

    def get_json(self, path: str) -> Any:
        status, body = self._request("GET", path)
        if status >= 400:
            raise DockerControlError(_daemon_sentence(status, body))
        return json.loads(body or b"null")

    def post(self, path: str, *, timeout: Optional[float] = None) -> int:
        status, body = self._request("POST", path, timeout=timeout)
        # 304: already in that state, which is what was asked for.
        if status >= 400:
            raise DockerControlError(_daemon_sentence(status, body))
        return status

    def get_raw(self, path: str) -> bytes:
        status, body = self._request("GET", path)
        if status >= 400:
            raise DockerControlError(_daemon_sentence(status, body))
        return body


def _daemon_sentence(status: int, body: bytes) -> str:
    try:
        message = json.loads(body or b"{}").get("message") or ""
    except ValueError:
        message = ""
    return f"The host's Docker answered {status}" + (f": {message}" if message else ".")


def available() -> bool:
    """Whether the operator gave Pantheon the host's Docker (`host-docker.yml`)."""
    return host_docker_access_enabled()


def own_project(api: DockerAPI, hostname: Optional[str] = None) -> Optional[str]:
    """The compose project Pantheon itself runs in, from its own container's
    labels. A container's hostname is its short id unless compose set one; the
    API accepts either a name or an id prefix, so both are tried."""
    candidates = [c for c in (hostname or socket.gethostname(), _own_container_id()) if c]
    for name in candidates:
        try:
            info = api.get_json(f"/containers/{quote(name, safe='')}/json")
        except DockerControlError:
            continue
        project = ((info.get("Config") or {}).get("Labels") or {}).get(PROJECT_LABEL)
        if project:
            return project
    return None


def _own_container_id(mountinfo: str = "/proc/self/mountinfo") -> str:
    """This container's id, from where Docker mounted its `/etc/hostname` —
    for a compose service whose `hostname:` is a name rather than the id."""
    import re
    try:
        text = open(mountinfo, "r", encoding="utf-8").read()
    except OSError:
        return ""
    m = re.search(r"/containers/([0-9a-f]{64})/", text)
    return m.group(1) if m else ""


def _health(state: Dict[str, Any]) -> str:
    return ((state or {}).get("Health") or {}).get("Status") or ""


def workstation_containers(api: DockerAPI, project: str) -> List[Dict[str, Any]]:
    """The workstation's containers in `project`, one dict each: `service`,
    `backend`, `id`, `name`, `state` (running/exited/…), `health`, `image`."""
    filters = json.dumps({"label": [f"{PROJECT_LABEL}={project}"]})
    rows = api.get_json(f"/containers/json?all=1&filters={quote(filters, safe='')}") or []
    out = []
    for row in rows:
        labels = row.get("Labels") or {}
        service = labels.get(SERVICE_LABEL) or ""
        if service not in ALL_SERVICES:
            continue
        backend = next((b for b, group in SERVICES.items() if service in group), "")
        health = ""
        status = row.get("Status") or ""
        if "(healthy)" in status:
            health = "healthy"
        elif "(unhealthy)" in status:
            health = "unhealthy"
        elif "(health: starting)" in status:
            health = "starting"
        out.append({
            "service": service, "backend": backend, "id": (row.get("Id") or "")[:12],
            "name": ((row.get("Names") or ["/"])[0] or "/").lstrip("/"),
            "state": row.get("State") or "", "status": status, "health": health,
            "image": row.get("Image") or "",
        })
    order = {s: i for i, s in enumerate(ALL_SERVICES)}
    return sorted(out, key=lambda r: order.get(r["service"], 99))


def act(api: DockerAPI, project: str, service: str, action: str) -> Dict[str, Any]:
    """Start, stop or restart one workstation service's container in `project`.
    Refuses any other service, any other project's container, and any other
    action — the list is the control, not the caller's word."""
    if action not in ACTIONS:
        raise DockerControlError(f"{action!r} isn't something the panel does; it starts, stops or restarts.")
    if service not in ALL_SERVICES:
        raise DockerControlError(f"{service!r} isn't one of the workstation's services.")
    row = next((r for r in workstation_containers(api, project) if r["service"] == service), None)
    if row is None:
        raise DockerControlError(f"There is no {service} container in this install yet.")
    # A VM host powers its machines off cleanly; give it the grace compose does.
    timeout = 130 if service == "workstation-vm" and action != "start" else 30
    suffix = "?t=120" if action != "start" and service == "workstation-vm" else ""
    api.post(f"/containers/{row['id']}/{action}{suffix}", timeout=timeout)
    return {"service": service, "action": action, "container": row["name"]}


def switch(api: DockerAPI, project: str, backend: str) -> Dict[str, Any]:
    """Start `backend`'s services and stop the other local backend's. `remote`
    stops both local ones — the workstation is another machine. A backend with
    no containers in this install is refused with what to add."""
    if backend not in ("container", "vm", "remote"):
        raise DockerControlError(f"{backend!r} isn't a backend.")
    rows = workstation_containers(api, project)
    have = {r["service"] for r in rows}
    wanted = SERVICES.get(backend, ())
    if wanted and not (set(wanted) & have):
        if backend == "vm":
            # The VM is in Pantheon's own docker-compose.yml (2026-10-31).
            raise DockerControlError(
                "This install has no vm workstation to switch to yet. Run `docker compose up -d "
                "--build` where you start Pantheon to make it; then the switch can start it.")
        # So is the container, since the same day (`docker/workstation.yml`
        # is a shim): an install from before it has not been brought up again.
        raise DockerControlError(
            f"This install has no {backend} workstation to switch to yet. Run `docker compose up "
            "-d --build` where you start Pantheon to make it; then the switch can start it.")
    steps = []
    for other, group in SERVICES.items():
        if other == backend:
            continue
        for service in group:
            if service in have and service not in wanted:
                act(api, project, service, "stop")
                steps.append(f"stopped {service}")
    for service in wanted:
        if service in have:
            act(api, project, service, "start")
            steps.append(f"started {service}")
    return {"backend": backend, "steps": steps}


def hold(backend: str, api: Optional[DockerAPI] = None) -> Dict[str, Any]:
    """At start-up: put the admin's backend back after a `compose up` started
    both — stop the other's running services and start this one's stopped
    ones. Changes nothing when everything is already as chosen."""
    api = api or DockerAPI()
    project = own_project(api)
    if not project:
        return {"backend": backend, "steps": []}
    rows = {r["service"]: r for r in workstation_containers(api, project)}
    wanted = set(SERVICES.get(backend, ()))
    steps = []
    for service, row in rows.items():
        if service in wanted and row["state"] != "running":
            act(api, project, service, "start")
            steps.append(f"started {service}")
        elif service not in wanted and row["backend"] and row["backend"] != backend \
                and row["state"] == "running":
            act(api, project, service, "stop")
            steps.append(f"stopped {service}")
    return {"backend": backend, "steps": steps}


def logs(api: DockerAPI, project: str, service: str, tail: int = 200) -> str:
    """The last `tail` lines a workstation service wrote, as text."""
    if service not in ALL_SERVICES:
        raise DockerControlError(f"{service!r} isn't one of the workstation's services.")
    row = next((r for r in workstation_containers(api, project) if r["service"] == service), None)
    if row is None:
        raise DockerControlError(f"There is no {service} container in this install yet.")
    tail = max(1, min(int(tail), 2000))
    raw = api.get_raw(f"/containers/{row['id']}/logs?stdout=1&stderr=1&tail={tail}")
    return _demux(raw)


def _demux(raw: bytes) -> str:
    """Docker's multiplexed log stream (8-byte frame headers) as plain text;
    a TTY container's stream has no frames and is returned as it is."""
    out = bytearray()
    i = 0
    framed = len(raw) >= 8 and raw[0] in (0, 1, 2) and raw[1:4] == b"\x00\x00\x00"
    if not framed:
        return raw.decode("utf-8", "replace")
    while i + 8 <= len(raw):
        size = int.from_bytes(raw[i + 4:i + 8], "big")
        out += raw[i + 8:i + 8 + size]
        i += 8 + size
    return out.decode("utf-8", "replace")


__all__ = ["ACTIONS", "ALL_SERVICES", "DockerAPI", "DockerControlError", "ENABLE_SENTENCE",
           "SERVICES", "act", "available", "hold", "logs", "own_project", "switch",
           "workstation_containers"]
