# SPDX-License-Identifier: AGPL-3.0-or-later
"""Adversarial phone file transfers and image-bound saved data.

The application router, document DB, auth store and workstation HTTP layer
are real. Android/ADB is an explicitly substituted boundary which records
the bytes it receives and answers checksum probes. These tests prove neither
Android execution nor VM/kernel isolation; those require separate acceptance.
"""
from __future__ import annotations

import base64
import asyncio
import contextlib
import hashlib
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from src.workstation_client import account_for
from workstation import phone as PH
from workstation import protocol as P
from test_the_workstation_is_admin_controlled import (  # noqa: F401 - shared real auth fixtures
    ADMIN, ALLOWED, ALSO, PLAIN, app, as_user, auth, datadir, switch_on, ws,
)


class LiveProcess:
    def poll(self):
        return None


class AdbBoundary:
    """No Android here: record sync bytes, emulate only adb's return shape."""

    def __init__(self):
        self.calls = []
        self.files = {}
        self.staged = []
        self.fail_push = False
        self.bad_digest = False

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        if args[0] == "push":
            source = Path(args[1])
            self.staged.append(source)
            assert source.is_file() and not source.is_symlink()
            if os.name == "posix":
                assert source.stat().st_mode & 0o777 == 0o600
                assert source.parent.stat().st_mode & 0o777 == 0o700
            if self.fail_push:
                raise PH.PhoneError("unavailable", "fixture adb push failed")
            self.files[args[2]] = source.read_bytes()
            return "1 file pushed"
        if args[:2] == ["shell", "sha256sum"]:
            destination, = shlex.split(args[-1])
            digest = hashlib.sha256(self.files[destination]).hexdigest()
            return ("0" * 64 if self.bad_digest else digest) + "  " + destination
        if args[:3] == ["shell", "rm", "-f"]:
            destination, = shlex.split(args[-1])
            self.files.pop(destination, None)
        return ""


def make_phone(root, *, backend="vm"):
    root.mkdir(parents=True, exist_ok=True)
    system = SimpleNamespace(backend=backend, home=lambda account: root,
                             uid=lambda account: 12000, files_as=lambda account: contextlib.nullcontext())
    phone = PH.AccountPhone(system, account_for("transfer-test"), None)
    phone.state, phone.emulator = "on", LiveProcess()
    phone.android_why = lambda: None
    phone.adb = AdbBoundary()
    return phone


@pytest.fixture
def phone(tmp_path):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("The real Linux no-follow staging contract needs Linux")
    return make_phone(tmp_path / "home")


@pytest.mark.parametrize("name", ["", " ", ".", "..", " . ", "../bob.txt", "bob/secret", "bob\\secret",
                                 "-option", "null\x00.txt", "line\nname", "\x7f", "\ud800.txt", "\u202eexe.txt",
                                 "a" * 181, "界" * 61, None, 7])
def test_hostile_names_are_refused_before_any_adb_or_file_write(phone, name):
    with pytest.raises(PH.PhoneError) as error:
        phone.transfer(name, base64.b64encode(b"secret").decode())
    assert error.value.code == "bad_request"
    assert phone.adb.calls == [] and phone.adb.staged == []


@pytest.mark.parametrize("data", ["?not-base64", "Zg", "Zg==\n", None, 7])
def test_malformed_base64_is_refused_before_staging(phone, data):
    with pytest.raises(PH.PhoneError) as error:
        phone.transfer("okay.txt", data)
    assert error.value.code == "bad_request" and not phone.adb.calls


def test_decoded_and_encoded_limits_are_enforced(phone, monkeypatch):
    monkeypatch.setattr(P, "MAX_FILE_BYTES", 17)
    for raw in (b"x" * 18, b"x" * 40):
        with pytest.raises(PH.PhoneError) as error:
            phone.transfer("large.bin", base64.b64encode(raw).decode())
        assert error.value.code == "bad_request"
    assert not phone.adb.calls


def test_exact_binary_bytes_are_verified_then_private_staging_is_removed(phone):
    data = b"\x00\xffbinary\r\n" + bytes(range(256))
    result = phone.transfer("photo and notes.bin", base64.b64encode(data).decode())
    assert result["ok"] and result["bytes"] == len(data)
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    assert result["destination"].startswith(PH.TRANSFER_DEST + "/")
    assert result["destination"].endswith("/photo and notes.bin")
    assert phone.adb.files == {result["destination"]: data}
    assert phone.adb.staged and all(not p.parent.exists() for p in phone.adb.staged)


def test_shell_metacharacters_stay_one_remote_filename(phone, tmp_path):
    if shutil.which("sh") is None:
        pytest.skip("A shell is needed to exercise the exact adb shell quoting")
    name = "$(touch PWNED); 'quoted'.txt"
    result = phone.transfer(name, base64.b64encode(b"safe").decode())
    checksum = next(args for args, _ in phone.adb.calls if args[:2] == ["shell", "sha256sum"])
    # adb shell joins its arguments into a remote shell command. Execute that
    # quoting with printf, in a fresh directory, to catch real substitution.
    seen = subprocess.run(["sh", "-c", "printf '%s' " + checksum[-1]], cwd=tmp_path,
                          capture_output=True, text=True, check=True)
    assert seen.stdout == result["destination"]
    assert not (tmp_path / "PWNED").exists()
    assert phone.adb.files[result["destination"]] == b"safe"


@pytest.mark.parametrize("fault", ["push", "digest"])
def test_failure_removes_staging_and_does_not_claim_success(phone, fault):
    phone.adb.fail_push = fault == "push"
    phone.adb.bad_digest = fault == "digest"
    with pytest.raises(PH.PhoneError) as error:
        phone.transfer("private.txt", base64.b64encode(b"private bytes").decode())
    assert error.value.code == "unavailable"
    assert phone.adb.staged and all(not p.parent.exists() for p in phone.adb.staged)
    assert not phone.adb.files


def test_failed_transfer_cleanup_keeps_the_selected_emulator_serial(phone):
    phone.port = 5586
    boundary = phone.adb
    boundary.fail_push = True
    cleanup_ports = []

    def observe(args, **kwargs):
        if args[:3] == ["shell", "rm", "-f"]:
            cleanup_ports.append(phone.port)
        return boundary(args, **kwargs)

    phone.adb = observe
    with pytest.raises(PH.PhoneError):
        phone.transfer("private.txt", base64.b64encode(b"private").decode())
    assert cleanup_ports == [5586], "Cleanup must address this emulator, not adb's default device"


def test_a_preexisting_staging_symlink_is_not_followed(phone, tmp_path, monkeypatch):
    victim = tmp_path / "victim"
    victim.write_bytes(b"untouched")
    stage = tmp_path / "malicious-stage"
    stage.mkdir()
    (stage / "payload").symlink_to(victim)
    cleaned = []
    monkeypatch.setattr(PH.tempfile, "TemporaryDirectory", lambda **kwargs:
                        SimpleNamespace(name=str(stage), cleanup=lambda: cleaned.append(True)))
    with pytest.raises(FileExistsError):
        phone.transfer("private.txt", base64.b64encode(b"replacement").decode())
    assert victim.read_bytes() == b"untouched" and cleaned == [True]
    assert not any(args[0] == "push" for args, _ in phone.adb.calls)


@pytest.mark.parametrize("backend,mobile,state", [("container", False, "on"), ("remote", False, "on"),
                                                  ("vm", True, "on"), ("vm", False, "off")])
def test_transfers_require_real_android_inside_the_per_user_vm(tmp_path, backend, mobile, state):
    p = make_phone(tmp_path / "h", backend=backend)
    p.state = state
    if mobile:
        p.mobile = SimpleNamespace(proc=LiveProcess())
    with pytest.raises(PH.PhoneError) as error:
        p.transfer("data.txt", base64.b64encode(b"x").decode())
    assert error.value.code == "unavailable" and not p.adb.calls


def test_switching_image_preserves_both_disks_and_reuses_only_matching_legacy_data(phone, monkeypatch):
    monkeypatch.setattr(phone, "_stop_locked", lambda: None)
    monkeypatch.setattr(phone, "info", lambda action="status": {"edition": phone.edition})
    device = phone.device
    root = phone.home() / ".android" / "avd"
    legacy = root / (PH.avd_name(device) + ".avd")
    legacy.mkdir(parents=True)
    (legacy / "config.ini").write_text(PH.avd_config(device, PH.DEFAULT_IMAGE), encoding="utf-8")
    (legacy / "userdata-qemu.img").write_bytes(b"original signed-in data")
    assert phone._avd_slot(PH.DEFAULT_IMAGE) == PH.avd_name(device)
    phone.select_edition("google_play")
    phone._write_avd()
    play = root / (phone.avd + ".avd")
    assert play != legacy and PH.image_parts(PH.PLAY_IMAGE)["sysdir"] in (play / "config.ini").read_text()
    (play / "userdata-qemu.img").write_bytes(b"separate Play data")
    phone.select_edition("standard")
    phone._write_avd()
    assert phone.avd == PH.avd_name(device)
    assert (legacy / "userdata-qemu.img").read_bytes() == b"original signed-in data"
    assert (play / "userdata-qemu.img").read_bytes() == b"separate Play data"


def test_operator_configured_play_image_needs_play_consent_even_under_standard_edition(phone, monkeypatch):
    import json
    from routes.workstation_routes import _phone_state
    monkeypatch.setenv(PH.IMAGE_ENV, PH.PLAY_IMAGE)
    monkeypatch.setattr(PH, "license_accepted", lambda: True)  # Existing SDK agreement, no Play choice yet.
    monkeypatch.setattr(PH, "tools_installed", lambda: True)
    monkeypatch.setattr(PH, "image_installed", lambda package: True)
    phone.state, phone.emulator = "off", None
    before = phone.info()
    assert phone.edition == "standard" and before["android"] == PH.PLAY_IMAGE
    assert before["google_play"] and before["image_kind"] == before["standard_image_kind"] == "google_play"
    assert before["license"]["accepted"] is False
    for action in (phone.start, lambda: phone.install(then_start=False)):
        with pytest.raises(PH.PhoneError) as error:
            action()
        assert error.value.code == "license"
    accepted = phone.install(accept=True, then_start=False)
    assert phone._accepted_editions == {"google_play"}
    assert accepted["license"]["accepted"] and accepted["edition"] == "standard"
    assert accepted["google_play"] and accepted["image_kind"] == "google_play"
    shaped = _phone_state(accepted)
    assert shaped["google_play"] and shaped["image_kind"] == shaped["standard_image_kind"] == "google_play"
    stored = json.loads((phone.home() / PH.PREFS_FILE).read_text())
    assert stored["edition"] == "standard" and stored["accepted_editions"] == ["google_play"]
    restored = make_phone(phone.home())
    assert restored.edition == "standard" and restored._edition_accepted()
    assert restored._accepted_editions == {"google_play"}


def test_configured_aosp_is_truthful_and_image_data_stays_bound_to_the_package(phone, monkeypatch):
    from routes.workstation_routes import _phone_state
    aosp = "system-images;android-35;default;x86_64"
    monkeypatch.setenv(PH.IMAGE_ENV, aosp)
    monkeypatch.setattr(phone, "_stop_locked", lambda: None)
    info = phone.info()
    assert info["android"] == aosp and info["google_play"] is False
    assert info["image_kind"] == info["standard_image_kind"] == "aosp"
    assert _phone_state(info)["image_kind"] == "aosp"
    phone._write_avd()
    aosp_slot = phone.avd
    root = phone.home() / ".android" / "avd"
    (root / (aosp_slot + ".avd") / "userdata-qemu.img").write_bytes(b"AOSP data")
    phone.select_edition("google_play")
    play = phone.info()
    assert play["android"] == PH.PLAY_IMAGE and play["google_play"]
    assert play["image_kind"] == "google_play" and play["standard_image_kind"] == "aosp"
    phone._write_avd()
    play_slot = phone.avd
    assert play_slot != aosp_slot
    (root / (play_slot + ".avd") / "userdata-qemu.img").write_bytes(b"Play data")
    phone.select_edition("standard")
    phone._write_avd()
    assert phone.avd == aosp_slot and phone.info()["image_kind"] == "aosp"
    assert (root / (aosp_slot + ".avd") / "userdata-qemu.img").read_bytes() == b"AOSP data"
    assert (root / (play_slot + ".avd") / "userdata-qemu.img").read_bytes() == b"Play data"


def test_unknown_custom_image_is_not_advertised_as_google_play_from_a_substring(phone, monkeypatch):
    monkeypatch.setenv(PH.IMAGE_ENV, "system-images;android-35;vendor_playstore;x86_64")
    info = phone.info()
    assert info["image_kind"] == info["standard_image_kind"] == "custom"
    assert info["google_play"] is False


def test_unknown_data_is_kept_and_incompatible_named_slots_are_refused(phone):
    root = phone.home() / ".android" / "avd"
    legacy = root / (PH.avd_name(phone.device) + ".avd")
    legacy.mkdir(parents=True)
    (legacy / "userdata-qemu.img").write_bytes(b"unknown legacy data")
    slot = phone._avd_slot(PH.DEFAULT_IMAGE)
    assert slot != PH.avd_name(phone.device)
    other = root / (slot + ".avd")
    other.mkdir()
    (other / "config.ini").write_text(PH.avd_config(phone.device, PH.PLAY_IMAGE), encoding="utf-8")
    (other / "userdata-qemu.img").write_bytes(b"do not reinterpret")
    with pytest.raises(PH.PhoneError):
        phone._write_avd()
    assert (legacy / "userdata-qemu.img").read_bytes() == b"unknown legacy data"
    assert (other / "userdata-qemu.img").read_bytes() == b"do not reinterpret"
    assert PH.image_parts(PH.PLAY_IMAGE)["sysdir"] in (other / "config.ini").read_text()


@pytest.mark.parametrize("device", [[], {}, ["pixel_8"], {"name": "pixel_8"}, None, False, 9])
def test_malformed_saved_device_preferences_recover_without_touching_device_data(tmp_path, device):
    import json
    root = tmp_path / "home"
    prefs = root / PH.PREFS_FILE
    prefs.parent.mkdir(parents=True)
    prefs.write_text(json.dumps({"device": device, "edition": [], "accepted_editions": [{}, 7]}), encoding="utf-8")
    original = prefs.read_bytes()
    p = make_phone(root)
    assert p.device == P.PHONE_DEFAULT_DEVICE and p.edition == "standard"
    assert not p._accepted_editions
    assert prefs.read_bytes() == original


@pytest.mark.parametrize("device", [[], {}, ["pixel_8"], {"name": "pixel_8"}])
def test_malformed_device_actions_are_bad_requests_not_server_errors(phone, device):
    for choose in (phone.start, phone.install):
        with pytest.raises(PH.PhoneError) as error:
            choose(device)
        assert error.value.code == "bad_request"


def test_invalid_utf8_in_legacy_config_never_rewrites_legacy_userdata(phone):
    root = phone.home() / ".android" / "avd"
    legacy = root / (PH.avd_name(phone.device) + ".avd")
    legacy.mkdir(parents=True)
    (legacy / "config.ini").write_bytes(b"\xffcorrupt config")
    (legacy / "userdata-qemu.img").write_bytes(b"old unknown data")
    phone._write_avd()
    assert phone.avd != PH.avd_name(phone.device)
    assert (legacy / "config.ini").read_bytes() == b"\xffcorrupt config"
    assert (legacy / "userdata-qemu.img").read_bytes() == b"old unknown data"


def test_bad_named_slot_is_actionable_and_releases_the_console_port(phone, monkeypatch):
    root = phone.home() / ".android" / "avd"
    slot = phone._avd_slot(PH.DEFAULT_IMAGE)
    folder = root / (slot + ".avd")
    folder.mkdir(parents=True)
    (folder / "config.ini").write_bytes(b"\xffbroken")
    (folder / "userdata-qemu.img").write_bytes(b"preserve me")
    phone.state, phone.emulator, phone.screen = "off", None, object()
    monkeypatch.setattr(phone, "installed", lambda *a: True)
    monkeypatch.setattr(phone, "_stop_locked", lambda: None)
    phone._claim_port = lambda account: 5586
    released = []
    phone._release_port = lambda account: released.append(account)
    with pytest.raises(PH.PhoneError) as error:
        phone.start()
    assert error.value.code == "unavailable"
    assert phone.port is None and released == [phone.account]
    assert (folder / "userdata-qemu.img").read_bytes() == b"preserve me"


@pytest.fixture
def route_phone(app, ws, monkeypatch, tmp_path):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("Real workstation filesystem staging requires Linux")
    # The application explicitly grants this fixture endpoint the VM role;
    # the fake producer's own metadata is not enough to establish trust.
    switch_on(app, ws, workstation_backend="vm")
    phones = {}
    ws.system.backend = "vm"  # Explicit runtime fixture, not a real VM/kernel.
    ws.system.uid = lambda account: 12000
    ws.system.files_as = lambda account: contextlib.nullcontext()

    def get(account):
        if account not in phones:
            ws.system.ensure(account)
            p = PH.AccountPhone(ws.system, account, None)
            p.state, p.emulator = "on", LiveProcess()
            p.android_why = lambda: None
            p.adb = AdbBoundary()
            phones[account] = p
        return phones[account]

    ws.station.phones.get = get
    return phones, get


@pytest.fixture
def documents(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'transfer-documents.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", sessions)
    with sessions() as db:
        db.add(cdb.Session(id="legacy-session", owner=ALLOWED, name="legacy", model="m", endpoint_url="http://x"))
        db.add_all([
            cdb.Document(id="mine", owner=ALLOWED, title="My notes", language="markdown", current_content="# Current text\n"),
            cdb.Document(id="theirs", owner=ALSO, title="Bob private", current_content="Bob's private account data"),
            cdb.Document(id="legacy", owner=None, session_id="legacy-session", title="Legacy", current_content="legacy mine"),
            cdb.Document(id="marker", owner=ALLOWED, title="Source export", current_content='<!-- pdf_source upload_id="other-user-upload" -->\nCurrent text'),
        ])
        db.commit()
    yield sessions
    engine.dispose()


def test_route_transfers_only_the_callers_custom_bytes_despite_forged_query(app, route_phone):
    phones, get = route_phone
    body = b"\x00\xffcustom bytes"
    r = as_user(app, ALLOWED).post("/api/workstation/phone/files?name=custom.bin&owner=" + ALSO
                                  + "&account=" + account_for(ALSO) + "&path=/home/bob/private&destination=/etc/passwd",
                                  content=body, headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    assert phones[account_for(ALLOWED)].adb.files == {r.json()["destination"]: body}
    assert account_for(ALSO) not in phones
    assert r.json()["sha256"] == hashlib.sha256(body).hexdigest()


def test_missing_sdk_license_is_409_on_both_daemon_and_application_http(app, ws, route_phone, monkeypatch):
    import httpx
    p = route_phone[1](account_for(ALLOWED))
    monkeypatch.setattr(PH, "license_accepted", lambda: False)
    body = {"action": "install", "device": p.device, "holder": "person"}
    daemon = httpx.post(ws.url + f"/v1/users/{account_for(ALLOWED)}/phone", json=body,
                        headers={"Authorization": "Bearer " + ws.token})
    assert daemon.status_code == 409, daemon.text
    assert daemon.json()["error"] == "license"
    application = as_user(app, ALLOWED).post("/api/workstation/phone", json=body)
    assert application.status_code == 409, application.text
    assert "Android SDK License" in application.json()["detail"]
    assert not p.adb.calls


@pytest.mark.parametrize("owner,bearer,expected", [(None, None, 401), (PLAIN, None, 403),
                                                 (ALLOWED, ALLOWED, 403)])
def test_route_refuses_anonymous_unprivileged_and_bearer_callers(app, route_phone, owner, bearer, expected):
    client = as_user(app, owner)
    headers = {"Content-Type": "application/octet-stream"}
    if bearer:
        headers["X-Test-Bearer"] = bearer
    r = client.post("/api/workstation/phone/files?name=x", content=b"x", headers=headers)
    assert r.status_code == expected, r.text
    assert not route_phone[0]


@pytest.mark.parametrize("device", [[], {}, ["pixel_8"], {"name": "pixel_8"}])
def test_malformed_device_requests_get_http400_through_both_real_routes(app, route_phone, device):
    r = as_user(app, ALLOWED).post("/api/workstation/phone", json={"action": "device", "device": device})
    assert r.status_code == 400, r.text


@pytest.mark.parametrize("doc,owner,expected", [("mine", ALLOWED, 200), ("theirs", ALLOWED, 404),
                                              ("mine", ADMIN, 404), ("legacy", ALLOWED, 200),
                                              ("legacy", ALSO, 404), ("absent", ALLOWED, 404)])
def test_document_selection_uses_existing_owner_and_legacy_session_checks(app, route_phone, documents, doc, owner, expected):
    r = as_user(app, owner).post("/api/workstation/phone/files", json={"document_id": doc})
    assert r.status_code == expected, r.text
    phone = route_phone[1](account_for(owner))
    if expected == 200:
        assert phone.adb.files[r.json()["destination"]] in (b"# Current text\n", b"legacy mine")
        assert r.json()["name"].endswith(".md" if doc == "mine" else ".txt")
    else:
        assert not phone.adb.files


def test_document_source_markers_cannot_resolve_another_users_file(app, route_phone, documents):
    r = as_user(app, ALLOWED).post("/api/workstation/phone/files", json={"document_id": "marker"})
    assert r.status_code == 200, r.text
    assert route_phone[1](account_for(ALLOWED)).adb.files[r.json()["destination"]] == (
        b'<!-- pdf_source upload_id="other-user-upload" -->\nCurrent text')


@pytest.mark.parametrize("selection", [{"document_id": "mine", "owner": ALSO},
                                     {"document_id": "mine", "path": "/home/bob"},
                                     {"path": "/home/bob"}, {"document_id": ["mine"]}, [], None])
def test_document_selection_refuses_extra_paths_owners_and_bad_shapes(app, route_phone, documents, selection):
    # Explicit content avoids httpx's json=None shorthand for an absent body.
    import json
    r = as_user(app, ALLOWED).post("/api/workstation/phone/files", content=json.dumps(selection),
                                  headers={"Content-Type": "application/json"})
    assert r.status_code == 400, r.text
    assert not route_phone[1](account_for(ALLOWED)).adb.files


def test_raw_and_document_body_limits_are_bounded_before_transfer(app, route_phone, monkeypatch):
    monkeypatch.setattr(P, "MAX_FILE_BYTES", 17)
    client = as_user(app, ALLOWED)
    for mime, payload in (("application/octet-stream", b"x" * 18), ("application/json", b" " * 4097)):
        r = client.post("/api/workstation/phone/files?name=x", content=payload, headers={"Content-Type": mime})
        assert r.status_code == 413, r.text
    assert not route_phone[1](account_for(ALLOWED)).adb.files


@pytest.mark.parametrize("disconnect", [True, False])
def test_interrupted_and_over_limit_chunked_uploads_never_reach_adb(app, route_phone, monkeypatch, disconnect):
    from fastapi import HTTPException
    from starlette.requests import ClientDisconnect, Request
    from routes.workstation_routes import setup_workstation_routes
    monkeypatch.setattr(P, "MAX_FILE_BYTES", 17)
    # FastAPI may retain included routers lazily on the application. Take
    # the shipped handler from its factory, with this app still on Request.
    endpoint = next(r.endpoint for r in setup_workstation_routes().routes
                    if getattr(r, "path", "") == "/api/workstation/phone/files")
    events = iter([
        {"type": "http.request", "body": b"first ten!", "more_body": True},
        {"type": "http.disconnect"} if disconnect else
        {"type": "http.request", "body": b"over limit", "more_body": True},
        {"type": "http.request", "body": b"must not be read", "more_body": False},
    ])
    reads = []

    async def receive():
        event = next(events)
        reads.append(event)
        return event

    request = Request({"type": "http", "method": "POST", "path": "/api/workstation/phone/files",
                       "scheme": "http", "server": ("testserver", 80), "client": ("testclient", 1234),
                       "query_string": b"name=partial.bin", "app": app,
                       "headers": [(b"content-type", b"application/octet-stream")],
                       "state": {"current_user": ALLOWED, "api_token": False}}, receive)
    with pytest.raises(ClientDisconnect if disconnect else HTTPException) as error:
        asyncio.run(endpoint(request, name="partial.bin"))
    if not disconnect:
        assert error.value.status_code == 413
    assert len(reads) == 2
    assert not route_phone[1](account_for(ALLOWED)).adb.calls


def test_document_privilege_and_feature_flag_still_apply(app, route_phone, documents, monkeypatch):
    auth = app.state.auth_manager
    auth.set_privileges(ALLOWED, {"can_use_documents": False})
    try:
        r = as_user(app, ALLOWED).post("/api/workstation/phone/files", json={"document_id": "mine"})
        assert r.status_code == 403, r.text
    finally:
        auth.set_privileges(ALLOWED, {"can_use_documents": True})
    import src.feature_gate as FG
    monkeypatch.setattr(FG, "feature_enabled", lambda feature: False)
    r = as_user(app, ALLOWED).post("/api/workstation/phone/files", json={"document_id": "mine"})
    assert r.status_code == 403, r.text
    assert not route_phone[1](account_for(ALLOWED)).adb.files


@pytest.mark.parametrize("state,mode,isolation", [("on", "mobile_view", "per_user_vm"),
                                                ("off", "android", "per_user_vm"),
                                                ("on", "android", "shared")])
def test_route_requires_an_on_android_vm_before_accepting_upload_bytes(app, route_phone, monkeypatch, state, mode, isolation):
    p = route_phone[1](account_for(ALLOWED))
    monkeypatch.setattr(p, "info", lambda: {"state": state, "mode": mode, "isolation": isolation})
    r = as_user(app, ALLOWED).post("/api/workstation/phone/files?name=x", content=b"x",
                                  headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 409, r.text
    assert not p.adb.calls
