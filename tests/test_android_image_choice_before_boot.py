# SPDX-License-Identifier: AGPL-3.0-or-later
"""Image choice is a saved preference, independent of Android availability.

Real client, HTTP daemon and phone preference files; no Android guest boots.
These checks establish persistence and the unchanged VM execution boundary.
"""
import asyncio
from contextlib import nullcontext

import pytest

from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers.workstation_daemon import running_workstation


ACCOUNT = account_for("image-choice-owner")


def call(client, action, **fields):
    return asyncio.run(client.phone(ACCOUNT, action, holder="person", **fields))


def test_developer_image_survives_polling_and_daemon_restart_without_booting_android(tmp_path, monkeypatch):
    with running_workstation(tmp_path) as station:
        # The temporary single-user daemon has no Unix account adapter.
        # Its private files are written as this test's own process identity.
        monkeypatch.setattr(station.system, "uid", lambda _: 1000, raising=False)
        monkeypatch.setattr(station.system, "files_as", lambda _: nullcontext(), raising=False)
        client = WorkstationClient(station.url, station.token)
        assert call(client, "status")["state"] == "unavailable"
        selected = call(client, "edition", edition="google_play")
        assert selected["edition"] == "google_play"
        with pytest.raises(WorkstationError) as invalid:
            call(client, "edition", edition="unknown-image")
        assert invalid.value.code == "bad_request"
        for _ in range(2):
            state = call(client, "status")
            assert state["edition"] == "google_play"
            assert state["mode"] is None and not state["can_start"]
        with pytest.raises(WorkstationError):
            call(client, "start")
        with pytest.raises(WorkstationError):
            call(client, "install", accept_license=True)

    with running_workstation(tmp_path) as station:
        monkeypatch.setattr(station.system, "uid", lambda _: 1000, raising=False)
        monkeypatch.setattr(station.system, "files_as", lambda _: nullcontext(), raising=False)
        client = WorkstationClient(station.url, station.token)
        state = call(client, "status")
        assert state["edition"] == "google_play"
        assert not state["available"] and not state["can_start"]
        assert call(client, "edition", edition="standard")["edition"] == "standard"


def test_selecting_an_android_edition_stops_preview_and_keeps_the_choice(tmp_path, monkeypatch):
    class Preview:
        stopped = False

        def __init__(self):
            self.proc = self

        def poll(self):
            return 0 if self.stopped else None

        def stop(self):
            self.stopped = True

    with running_workstation(tmp_path) as station:
        monkeypatch.setattr(station.system, "uid", lambda _: 1000, raising=False)
        monkeypatch.setattr(station.system, "files_as", lambda _: nullcontext(), raising=False)
        phone = station.station.phones.get(ACCOUNT)
        preview = phone.mobile = Preview()
        phone.state = "on"
        client = WorkstationClient(station.url, station.token)
        assert call(client, "status")["mode"] == "mobile_view"
        state = call(client, "edition", edition="google_play")
        assert preview.stopped and phone.mobile is None
        assert state["edition"] == "google_play" and state["mode"] is None
        assert call(client, "status")["edition"] == "google_play"
        assert phone.emulator is None
