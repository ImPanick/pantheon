# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1478`, `D-2026-10-25-04` §3 — the backend control switches the backend.

The owner: *"The backend should have a real switch — because the admins should
be able to control this container."* Settings → Workstation → *Backend* changed
only words: which workstation ran was the overlay in `.env`, and Pantheon held no
Docker socket. Now, where the operator gave Pantheon the host's Docker
(`docker/host-docker.yml`), `src/workstation_control.py` lists the workstation's
containers in Pantheon's own compose project, starts, stops and restarts them,
reads their logs, and switches the backend by starting one kind's services and
stopping the other's — and the choice decides which daemon Pantheon talks to.

Driven against a stand-in Docker Engine on a real unix socket: the module's own
HTTP, the Engine API's paths and answers, and a container of another project
that must never be touched.
"""

from __future__ import annotations

import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest
import yaml

import src.workstation_control as wctl

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "pantheon"


class _Engine:
    """A Docker Engine that knows a few containers and records what it is asked."""

    def __init__(self):
        self.calls = []
        self.containers = [
            self._c("aaa111", "pantheon-pantheon-1", "pantheon", PROJECT, "running"),
            self._c("bbb222", "pantheon-workstation-net-1", "workstation-net", PROJECT, "running"),
            self._c("ccc333", "pantheon-workstation-1", "workstation", PROJECT, "running", "Up 2 hours (healthy)"),
            self._c("ddd444", "pantheon-workstation-vm-1", "workstation-vm", PROJECT, "exited"),
            self._c("eee555", "other-workstation-1", "workstation", "other", "running"),
        ]

    @staticmethod
    def _c(cid, name, service, project, state, status=""):
        return {"Id": cid * 5, "Names": ["/" + name], "State": state, "Status": status or state,
                "Image": "img", "Labels": {wctl.PROJECT_LABEL: project, wctl.SERVICE_LABEL: service}}


def _serve(engine, path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, body=b""):
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            engine.calls.append(("GET", self.path))
            p = self.path.split("/", 2)[2] if self.path.startswith("/v1.41/") else ""
            if p.startswith("containers/json"):
                from urllib.parse import parse_qs, urlsplit
                q = parse_qs(urlsplit(self.path).query)
                want = json.loads(q["filters"][0])["label"][0].split("=", 1)[1]
                rows = [c for c in engine.containers if c["Labels"][wctl.PROJECT_LABEL] == want]
                return self._send(200, json.dumps(rows).encode())
            if p.startswith("containers/") and p.endswith("/json"):
                name = p.split("/")[1]
                for c in engine.containers:
                    if c["Names"][0] == "/" + name or c["Id"].startswith(name):
                        return self._send(200, json.dumps({"Config": {"Labels": c["Labels"]}}).encode())
                return self._send(404, b'{"message": "No such container"}')
            if "/logs" in p:
                frame = b"\x01\x00\x00\x00" + (6).to_bytes(4, "big") + b"hello\n"
                return self._send(200, frame + b"\x02\x00\x00\x00" + (5).to_bytes(4, "big") + b"oops\n")
            return self._send(404, b"{}")

        def do_POST(self):
            engine.calls.append(("POST", self.path))
            cid = self.path.split("/")[3]
            action = self.path.split("/")[4].split("?")[0]
            for c in engine.containers:
                if c["Id"].startswith(cid):
                    c["State"] = "running" if action in ("start", "restart") else "exited"
            return self._send(204)

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

        def get_request(self):
            req, _ = super().get_request()
            return req, ("local", 0)

    srv = Server(str(path), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def engine(tmp_path):
    e = _Engine()
    sock = tmp_path / "docker.sock"
    srv = _serve(e, sock)
    try:
        yield e, wctl.DockerAPI(str(sock))
    finally:
        srv.shutdown()
        srv.server_close()


def test_it_finds_its_own_project_and_only_its_workstation(engine):
    e, api = engine
    assert wctl.own_project(api, hostname="pantheon-pantheon-1") == PROJECT
    rows = wctl.workstation_containers(api, PROJECT)
    assert [r["service"] for r in rows] == ["workstation-net", "workstation", "workstation-vm"]
    assert rows[1]["health"] == "healthy" and rows[2]["state"] == "exited"
    assert all(r["name"].startswith("pantheon-") for r in rows), "another project's container leaked in"


def test_it_starts_stops_and_restarts_one_service(engine):
    e, api = engine
    wctl.act(api, PROJECT, "workstation", "restart")
    assert ("POST", "/v1.41/containers/ccc333ccc333/restart") in e.calls
    with pytest.raises(wctl.DockerControlError):
        wctl.act(api, PROJECT, "pantheon", "stop")        # not a workstation service
    with pytest.raises(wctl.DockerControlError):
        wctl.act(api, PROJECT, "workstation", "kill")      # not an action the panel has
    assert not any("eee555" in path for _, path in e.calls), "another project's workstation was touched"


def test_switching_to_the_vm_starts_it_and_stops_the_container(engine):
    e, api = engine
    out = wctl.switch(api, PROJECT, "vm")
    assert out["steps"] == ["stopped workstation-net", "stopped workstation", "started workstation-vm"]
    state = {c["Labels"][wctl.SERVICE_LABEL]: c["State"] for c in e.containers
             if c["Labels"][wctl.PROJECT_LABEL] == PROJECT}
    assert state["workstation-vm"] == "running" and state["workstation"] == "exited"
    # the VM host powers its machines off cleanly: the stop of it waits two minutes
    wctl.switch(api, PROJECT, "container")
    assert ("POST", "/v1.41/containers/ddd444ddd444/stop?t=120") in e.calls


def test_a_backend_this_install_does_not_have_says_what_to_add(engine):
    e, api = engine
    e.containers = [c for c in e.containers if c["Labels"][wctl.SERVICE_LABEL] != "workstation-vm"]
    with pytest.raises(wctl.DockerControlError) as caught:
        wctl.switch(api, PROJECT, "vm")
    # The VM is in Pantheon's own docker-compose.yml (2026-10-31): nothing to add.
    assert "docker compose up -d --build" in str(caught.value)
    assert "COMPOSE_FILE" not in str(caught.value)
    e.containers = [c for c in e.containers
                    if c["Labels"][wctl.SERVICE_LABEL] not in ("workstation", "workstation-net")]
    with pytest.raises(wctl.DockerControlError) as caught:
        wctl.switch(api, PROJECT, "container")
    assert "docker/workstation.yml" in str(caught.value)


def test_logs_are_plain_text(engine):
    e, api = engine
    assert wctl.logs(api, PROJECT, "workstation", tail=50) == "hello\noops\n"


def test_without_the_hosts_docker_it_says_how_to_give_it(monkeypatch):
    monkeypatch.delenv("PANTHEON_ENABLE_HOST_DOCKER", raising=False)
    assert wctl.available() is False
    assert "docker/host-docker.yml" in wctl.ENABLE_SENTENCE


def test_the_vm_is_in_the_stack_and_the_old_overlays_add_no_second_host():
    """The owner (2026-10-31): *"We need to give this a proper VM to work
    inside for the workstation."* The VM host is Pantheon's own
    docker-compose.yml's `workstation-vm` — the service `workstation-both.yml`
    used to add, on the same volume, so every machine made under either is kept
    — and the two overlays that defined one are kept loadable and define none:
    two hosts on the `workstation-vm` volume would boot one person's disk twice."""
    stack = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    side = stack["services"]["workstation-vm"]
    assert side["hostname"] == "workstation-vm"
    assert side["build"] == {"context": "./workstation", "dockerfile": "vm.Dockerfile"}
    assert side["volumes"] == ["workstation-vm:/var/lib/pantheon-workstation-vm",
                               "workstation-vm-pairing:/workstation-pairing",
                               "${APP_DATA_DIR:-./data}/projects:/projects:z"]
    assert side["device_cgroup_rules"] == ["c 10:232 rwm"]
    assert not side.get("privileged") and not side.get("cap_add") and not side.get("ports")
    # Nothing is made until the workstation is switched on.
    assert "PANTHEON_WORKSTATION_VM_IMAGE=${PANTHEON_WORKSTATION_VM_IMAGE:-on_first_use}" in side["environment"]
    env = stack["services"]["pantheon"]["environment"]
    assert "PANTHEON_WORKSTATION_VM_URL=http://workstation-vm:7040" in env
    assert "PANTHEON_WORKSTATION_VM_PAIRING=/workstation-vm-pairing" in env
    assert "workstation-vm-pairing:/workstation-vm-pairing:ro" in stack["services"]["pantheon"]["volumes"]
    assert {"workstation-vm", "workstation-vm-pairing"} <= set(stack["volumes"])
    for name in ("workstation-vm.yml", "workstation-both.yml"):
        overlay = yaml.safe_load((ROOT / "docker" / name).read_text())
        assert set(overlay["services"]) == {"pantheon"}, name
        assert "volumes" not in overlay, name


def test_compose_resolves_both_backends_side_by_side():
    """As compose itself reads them (`Law 20`): the container's overlay, this
    one, and the host-Docker opt-in together — three workstation services, a
    pairing volume each, and Pantheon told where both daemons are."""
    import os
    import shutil
    import subprocess
    if not shutil.which("docker"):
        pytest.skip("the docker CLI is not installed here")
    env = {k: v for k, v in os.environ.items() if k != "COMPOSE_FILE"}
    argv = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker/workstation.yml",
            "-f", "docker/workstation-both.yml", "-f", "docker/host-docker.yml",
            "config", "--format", "json"]
    done = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    if done.returncode != 0 and "is not a docker command" in done.stderr:
        pytest.skip("docker compose is not installed here")
    assert done.returncode == 0, done.stderr
    cfg = json.loads(done.stdout)
    assert {"workstation", "workstation-net", "workstation-vm"} <= set(cfg["services"])
    vm = cfg["services"]["workstation-vm"]
    assert [(m["source"], m["target"]) for m in vm["volumes"]][:2] == [
        ("workstation-vm", "/var/lib/pantheon-workstation-vm"),
        ("workstation-vm-pairing", "/workstation-pairing")]
    env_ = cfg["services"]["pantheon"]["environment"]
    assert env_["PANTHEON_WORKSTATION_VM_URL"] == "http://workstation-vm:7040"
    assert env_["PANTHEON_WORKSTATION_URL"] == "http://workstation:7040"
    targets = {m["target"]: m.get("read_only") for m in cfg["services"]["pantheon"]["volumes"]}
    assert targets["/workstation-vm-pairing"] is True and targets["/workstation-pairing"] is True


def test_at_start_up_the_admins_backend_is_put_back(engine, monkeypatch):
    """A `compose up -d` starts both; the start-up hold stops the one the admin
    switched away from and starts the chosen one's stopped services."""
    e, api = engine
    for c in e.containers:
        if c["Labels"][wctl.SERVICE_LABEL] == "workstation-vm":
            c["State"] = "running"
    monkeypatch.setattr(wctl, "own_project", lambda api, hostname=None: PROJECT)
    out = wctl.hold("container", api)
    assert out["steps"] == ["stopped workstation-vm"]
    assert wctl.hold("container", api)["steps"] == [], "nothing to do the second time"


# ── which daemon Pantheon talks to, and sudo by backend (`D-2026-10-25-04` §4) ──

@pytest.fixture
def both(monkeypatch, tmp_path):
    import src.workstation_client as wc
    vm_pair = tmp_path / "vm-pairing"
    vm_pair.mkdir()
    (vm_pair / "token").write_text("pws_vm\n")
    ct_pair = tmp_path / "ct-pairing"
    ct_pair.mkdir()
    (ct_pair / "token").write_text("pws_container\n")
    monkeypatch.setenv("PANTHEON_WORKSTATION_URL", "http://workstation:7040")
    monkeypatch.setenv("PANTHEON_WORKSTATION_PAIRING", str(ct_pair))
    monkeypatch.setenv("PANTHEON_WORKSTATION_VM_URL", "http://workstation-vm:7040")
    monkeypatch.setenv("PANTHEON_WORKSTATION_VM_PAIRING", str(vm_pair))
    stored = {}
    monkeypatch.setattr(wc, "_setting", lambda key, default="": stored.get(key, default))
    wc.forget_vm_accel()
    return wc, stored


@pytest.mark.parametrize("choice, accel, backend, url, token", [
    ("auto", "kvm", "vm", "http://workstation-vm:7040", "pws_vm"),
    ("auto", "tcg", "container", "http://workstation:7040", "pws_container"),
    ("auto", None, "container", "http://workstation:7040", "pws_container"),
    ("container", "kvm", "container", "http://workstation:7040", "pws_container"),
    ("vm", None, "vm", "http://workstation-vm:7040", "pws_vm"),
])
def test_the_choice_decides_which_daemon_answers(both, monkeypatch, choice, accel, backend, url, token):
    wc, stored = both
    stored["workstation_backend"] = choice
    monkeypatch.setattr(wc, "vm_accel", lambda: accel)
    assert wc.effective_backend() == backend
    assert wc.resolve_base() == (url, wc.SOURCE_ENVIRONMENT)
    assert wc.resolve_token() == (token, wc.SOURCE_PAIRING)


@pytest.mark.parametrize("accel", ["kvm", "tcg", None])
def test_the_stacks_vm_alone_is_the_workstation_whatever_it_runs_on(both, monkeypatch, accel):
    """The stack ships the VM host and no container (2026-10-31): `auto` is the
    VM even on TCG — with nothing else configured, any other answer is a
    workstation that is "on but has no address", which is what *turning it on
    does nothing* was."""
    wc, stored = both
    monkeypatch.delenv("PANTHEON_WORKSTATION_URL")
    monkeypatch.setattr(wc, "vm_accel", lambda: accel)
    assert wc.effective_backend() == "vm"
    assert wc.resolve_base() == ("http://workstation-vm:7040", wc.SOURCE_ENVIRONMENT)
    assert wc.resolve_token() == ("pws_vm", wc.SOURCE_PAIRING)


def test_an_address_typed_for_another_machine_still_wins(both, monkeypatch):
    wc, stored = both
    stored.update(workstation_backend="vm", workstation_url="https://ws.example:7040")
    assert wc.resolve_base() == ("https://ws.example:7040", wc.SOURCE_SETTING)


@pytest.mark.parametrize("stored_sudo, backend, want", [
    (None, "vm", True), (None, "container", False), (None, "remote", False),
    (True, "container", True), (False, "vm", False),
])
def test_sudo_by_backend_unless_the_admin_said(monkeypatch, stored_sudo, backend, want):
    import src.workstation_access as wa
    monkeypatch.setattr(wa, "_setting", lambda key: stored_sudo if key == "workstation_sudo" else None)
    assert wa.sudo_wanted(backend) is want


def test_the_shipped_defaults_are_auto_and_by_backend():
    import src.settings as S
    import src.workstation_access as wa
    assert S.DEFAULT_SETTINGS["workstation_backend"] == "auto"
    assert S.DEFAULT_SETTINGS["workstation_sudo"] is None
    assert wa.validate_setting("workstation_backend", "auto") == "auto"
    assert wa.validate_setting("workstation_sudo", None) is None
    with pytest.raises(ValueError):
        wa.validate_setting("workstation_backend", "kubernetes")


def test_the_panel_switches_through_the_route_and_lists_the_machines():
    js = (ROOT / "static" / "js" / "workstation.js").read_text(encoding="utf-8")
    assert "fetch('/api/workstation/backend'" in js
    assert "onChange('ws-backend'" not in js, "the backend select no longer only saves a word"
    assert "/api/workstation/machines" in js
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="ws-machines"' in html


from tests.test_the_workstation_is_admin_controlled import (  # noqa: E402,F401 — fixtures
    ADMIN, app, as_user, auth, datadir)


def test_an_admin_can_put_sudo_back_to_automatic(app):
    import src.settings as S
    client = as_user(app, ADMIN)
    assert client.post("/api/auth/settings", json={"workstation_sudo": True}).status_code == 200
    assert S.load_settings().get("workstation_sudo") is True
    r = client.post("/api/auth/settings", json={"workstation_sudo": None})
    assert r.status_code == 200, r.text
    assert S.load_settings().get("workstation_sudo") is None


def test_choosing_a_backend_without_the_hosts_docker_saves_it_and_says_how(app, monkeypatch):
    import src.settings as S
    import src.workstation_control as wctl_mod
    monkeypatch.setattr(wctl_mod, "available", lambda: False)
    client = as_user(app, ADMIN)
    r = client.post("/api/workstation/backend", json={"backend": "vm"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["choice"] == "vm" and "docker/host-docker.yml" in body["sentence"]
    assert S.load_settings().get("workstation_backend") == "vm"
    assert client.post("/api/workstation/backend", json={"backend": "mainframe"}).status_code == 400
    machines = client.get("/api/workstation/machines").json()
    assert machines["available"] is False and "docker/host-docker.yml" in machines["sentence"]
