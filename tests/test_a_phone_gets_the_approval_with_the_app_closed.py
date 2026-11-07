# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1830`–`B1832` — Web Push to a person's own devices, and a tool approval
answered from the notification.

Driven, not grepped (`Law 20`): the encryption against RFC 8291's own test
vector and a decrypt; the signed token against its public key; the push
routes through FastAPI; the approval store's new listener with a real card;
the chat route with exactly the form the service worker sends; and
`static/sw.js` itself in node, with a fake worker scope around it.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import src.tool_approvals as tool_approvals
from src import web_push
from src.auth_helpers import require_user
from src.tool_capabilities import capabilities_for_action

ROOT = Path(__file__).resolve().parent.parent
FCM = "https://fcm.googleapis.com/fcm/send/abc123"


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(web_push, "VAPID_FILE", str(tmp_path / "push_vapid.json"))
    monkeypatch.setattr(web_push, "SUBSCRIPTIONS_FILE", str(tmp_path / "push_subscriptions.json"))
    monkeypatch.delenv(web_push.PUSH_HOSTS_ENV, raising=False)
    yield tmp_path
    tool_approvals.clear_approval_created_listeners()


def _device():
    """A browser's half: its key pair and auth secret, and the subscription it hands over."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    sub = {"endpoint": FCM + os.urandom(4).hex(),
           "keys": {"p256dh": web_push.b64url(public), "auth": web_push.b64url(auth)}}
    return private, auth, sub


def _decrypt(record: bytes, private, auth: bytes) -> bytes:
    """RFC 8291 from the receiving side, written out separately from `encrypt`."""
    salt, rs, idlen = record[:16], int.from_bytes(record[16:20], "big"), record[20]
    as_public = record[21:21 + idlen]
    ciphertext = record[21 + idlen:]
    assert rs == 4096 and idlen == 65
    ua_public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    secret = private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), as_public))
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth,
               info=b"WebPush: info\x00" + ua_public + as_public).derive(secret)
    cek = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt,
               info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt,
                 info=b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


# ── the message and the token ────────────────────────────────────────────────

def test_encryption_matches_rfc_8291s_own_example():
    d = web_push.b64url_decode
    sender = ec.derive_private_key(
        int.from_bytes(d("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1())
    record = web_push.encrypt(
        b"When I grow up, I want to be a watermelon",
        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
        "BTBZMqHH6r4Tts7J_aSIgg",
        salt=d("DGv6ra1nlYgDCS1FRnbzlw"), sender_private=sender)
    assert web_push.b64url(record) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS"
        "6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Q"
        "ulcy4a-fN")


def test_a_fresh_message_decrypts_on_the_device():
    private, auth, sub = _device()
    record = web_push.encrypt(b'{"type":"test"}', sub["keys"]["p256dh"], sub["keys"]["auth"])
    assert _decrypt(record, private, auth) == b'{"type":"test"}'


def test_the_key_is_made_once_kept_private_and_never_replaced_over_a_bad_file(data_dir):
    first = web_push.public_key()
    assert web_push.public_key() == first
    assert len(web_push.b64url_decode(first)) == 65
    if os.name == "posix":
        assert (os.stat(web_push.VAPID_FILE).st_mode & 0o777) == 0o600
    Path(web_push.VAPID_FILE).write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        web_push.public_key()
    assert Path(web_push.VAPID_FILE).read_text(encoding="utf-8") == "{not json"


def test_the_signed_token_names_the_push_service_and_verifies():
    header = web_push.vapid_header(FCM, now=1_000_000)
    token = header.split("t=", 1)[1].split(",", 1)[0]
    key = header.split("k=", 1)[1]
    assert key == web_push.public_key()
    head, claims, sig = token.split(".")
    raw = web_push.b64url_decode(sig)
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), web_push.b64url_decode(key))
    public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                  f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    body = json.loads(web_push.b64url_decode(claims))
    assert body["aud"] == "https://fcm.googleapis.com"
    assert body["exp"] == 1_000_000 + web_push.TOKEN_LIFETIME_SECONDS
    assert body["sub"].startswith(("mailto:", "https://"))


# ── who may be pushed to ─────────────────────────────────────────────────────

@pytest.mark.parametrize("endpoint", [
    FCM,
    "https://updates.push.services.mozilla.com/wpush/v2/gAAAA",
    "https://web.push.apple.com/QGuQ",
    "https://wns2-par02p.notify.windows.com/w/?token=x",
])
def test_the_browser_makers_push_services_are_accepted(endpoint):
    assert web_push.check_endpoint(endpoint) == endpoint


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/x",       # not https
    "https://127.0.0.1/hook",                      # the operator's own box
    "https://192.168.1.10/",                       # the LAN
    "https://fcm.googleapis.com.evil.example/x",   # a look-alike
    "https://evilfcm.googleapis.com.example/x",
    "https://fcm.googleapis.com:8443/x",           # another port
    "https://user:pw@fcm.googleapis.com/x",
    "",
])
def test_any_other_address_is_refused(endpoint):
    with pytest.raises(web_push.PushError):
        web_push.check_endpoint(endpoint)


def test_an_operator_can_add_their_own_push_service(monkeypatch):
    monkeypatch.setenv(web_push.PUSH_HOSTS_ENV, "push.example.org")
    assert web_push.check_endpoint("https://push.example.org/x")


def test_each_person_sees_and_removes_only_their_own_devices():
    _, _, a = _device()
    _, _, b = _device()
    web_push.subscribe("Alice", a, label="Pixel")
    web_push.subscribe("bob", b)
    assert [d["label"] for d in web_push.list_devices("alice")] == ["Pixel"]
    bobs = web_push.list_devices("bob")
    assert not web_push.unsubscribe("alice", device_id=bobs[0]["id"])
    assert web_push.list_devices("bob")
    assert web_push.unsubscribe("bob", endpoint=b["endpoint"])
    assert not web_push.list_devices("bob")


def test_a_bad_subscription_is_refused():
    _, _, sub = _device()
    with pytest.raises(web_push.PushError):
        web_push.subscribe("alice", {**sub, "keys": {"p256dh": "AAAA", "auth": "AAAA"}})
    with pytest.raises(web_push.PushError):
        web_push.subscribe("", sub)


# ── the routes ───────────────────────────────────────────────────────────────

class _Sent:
    def __init__(self, status=201):
        self.status = status
        self.calls = []

    async def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return SimpleNamespace(status_code=self.status, headers={}, text="")


@pytest.fixture()
def client(monkeypatch):
    from routes.push_routes import setup_push_routes
    app = FastAPI()
    app.include_router(setup_push_routes())
    app.dependency_overrides[require_user] = lambda: "alice"
    return TestClient(app)


def test_turn_on_test_and_remove_through_the_routes(client, monkeypatch):
    from src import paced_http
    sent = _Sent()
    monkeypatch.setattr(paced_http, "post", sent)
    assert len(web_push.b64url_decode(client.get("/api/push/key").json()["public_key"])) == 65
    assert client.post("/api/push/test", json={}).status_code == 404
    private, auth, sub = _device()
    device = client.post("/api/push/subscriptions", json={"subscription": sub, "label": "Pixel"}).json()["device"]
    assert client.get("/api/push/subscriptions").json()["devices"][0]["id"] == device["id"]
    results = client.post("/api/push/test", json={}).json()["results"]
    assert results == [{"id": device["id"], "label": "Pixel", "ok": True, "status": 201}]
    (url, kw), = sent.calls
    assert url == sub["endpoint"]
    assert kw["headers"]["Content-Encoding"] == "aes128gcm" and kw["headers"]["Urgency"] == "high"
    assert kw["headers"]["Authorization"].startswith("vapid t=")
    assert json.loads(_decrypt(kw["content"], private, auth))["type"] == "test"
    assert client.request("DELETE", "/api/push/subscriptions", json={"id": device["id"]}).json() == {"removed": True}


def test_a_lan_address_cannot_be_registered(client):
    _, _, sub = _device()
    res = client.post("/api/push/subscriptions",
                      json={"subscription": {**sub, "endpoint": "https://10.0.0.5/x"}})
    assert res.status_code == 400


def test_a_device_the_push_service_says_is_gone_is_removed(client, monkeypatch):
    from src import paced_http
    monkeypatch.setattr(paced_http, "post", _Sent(410))
    _, _, sub = _device()
    web_push.subscribe("alice", sub)
    result, = client.post("/api/push/test", json={}).json()["results"]
    assert not result["ok"] and "removed" in result["error"]
    assert web_push.list_devices("alice") == []


def test_a_token_cannot_reach_the_push_routes():
    from routes.push_routes import setup_push_routes
    app = FastAPI()
    app.include_router(setup_push_routes())

    @app.middleware("http")
    async def as_token(request, call_next):
        request.state.api_token = True
        return await call_next(request)

    assert TestClient(app).get("/api/push/subscriptions").status_code == 403


# ── a card reaches the phone ─────────────────────────────────────────────────

def _card(store, *, owner="alice", session="session-1", held=False):
    return store.create(
        owner=owner, session_id=session, origin_run_id="run-1",
        tool_name="bash", content="rm -rf /srv/old\necho done", workspace=None,
        external_untrusted_context_seen=False,
        capabilities=capabilities_for_action("bash", "rm -rf /srv/old"),
        held_by_run=held,
    )


def test_a_new_card_is_pushed_to_its_owners_devices(monkeypatch):
    from src import paced_http
    sent = _Sent()
    monkeypatch.setattr(paced_http, "post", sent)
    private, auth, sub = _device()
    web_push.subscribe("alice", sub)
    web_push.install()
    store = tool_approvals.ToolApprovalStore(ttl_seconds=600)

    async def mint():
        card = _card(store, owner="Alice")
        await asyncio.gather(*list(web_push._pending_tasks))
        return card

    card = asyncio.run(mint())
    (url, kw), = sent.calls
    msg = json.loads(_decrypt(kw["content"], private, auth))
    assert msg["type"] == "tool_approval" and msg["can_answer"] is True
    assert msg["approval_id"] == card.approval_id and msg["session_id"] == "session-1"
    assert "rm -rf /srv/old" in msg["body"] and "echo done" not in msg["body"]
    assert kw["headers"]["Urgency"] == "high"
    assert 30 <= int(kw["headers"]["TTL"]) <= 600


def test_a_card_with_no_device_or_no_chat_sends_nothing(monkeypatch):
    from src import paced_http
    sent = _Sent()
    monkeypatch.setattr(paced_http, "post", sent)
    _, _, sub = _device()
    web_push.subscribe("alice", sub)
    web_push.install()
    store = tool_approvals.ToolApprovalStore(ttl_seconds=600)
    _card(store, owner="bob")
    _card(store, session="")
    assert not web_push._pending_tasks and sent.calls == []


def test_a_workflow_runs_question_only_opens_pantheon():
    store = tool_approvals.ToolApprovalStore(ttl_seconds=600)
    msg = web_push.approval_message(_card(store, held=True))
    assert msg["can_answer"] is False


def test_a_listener_that_fails_does_not_stop_the_card():
    def broken(_pending):
        raise RuntimeError("boom")
    tool_approvals.register_approval_created_listener(broken)
    store = tool_approvals.ToolApprovalStore(ttl_seconds=600)
    card = _card(store)
    assert store.peek(card.approval_id, owner="alice", session_id="session-1") is card


# ── the answer goes through the card's own route ─────────────────────────────

SW_FORM = {"message": "", "session": "session-1", "mode": "agent"}


@pytest.mark.asyncio
async def test_deny_from_the_notification_consumes_the_card(monkeypatch):
    import routes.chat_routes as chat_routes
    from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint

    store = tool_approvals.ToolApprovalStore(ttl_seconds=600)
    monkeypatch.setattr(chat_routes, "tool_approval_store", store)
    card = _card(store)
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {})
    request = _RouteRequest("agent")
    request._form = {**SW_FORM, "tool_approval_id": card.approval_id, "tool_approval_decision": "deny"}
    response = await endpoint(request)
    assert response.media_type == "text/event-stream"
    assert store.peek(card.approval_id, owner="alice", session_id="session-1") is None


@pytest.mark.asyncio
async def test_a_token_cannot_answer_from_a_notification_either(monkeypatch):
    import routes.chat_routes as chat_routes
    from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint

    store = tool_approvals.ToolApprovalStore(ttl_seconds=600)
    monkeypatch.setattr(chat_routes, "tool_approval_store", store)
    card = _card(store)
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {})
    request = _RouteRequest("agent")
    request.state.api_token = True
    request._form = {**SW_FORM, "tool_approval_id": card.approval_id, "tool_approval_decision": "approve_task"}
    with pytest.raises(HTTPException) as refused:
        await endpoint(request)
    assert refused.value.status_code == 403
    assert store.peek(card.approval_id, owner="alice", session_id="session-1") is card


# ── the service worker, run ──────────────────────────────────────────────────

_needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node binary not on PATH")

_HARNESS = textwrap.dedent(r"""
const fs = require('fs'); const vm = require('vm');
const src = fs.readFileSync('static/sw.js', 'utf8');
const handlers = {}; const shown = []; const fetched = []; const opened = [];
const cmd = JSON.parse(fs.readFileSync(0, 'utf8'));
const self = {
  location: new URL('https://pantheon.example/'),
  addEventListener: (t, f) => { handlers[t] = f; },
  registration: { showNotification: async (title, opts) => { shown.push({ title, opts }); } },
  clients: { matchAll: async () => [], openWindow: async (u) => { opened.push(u); } },
  skipWaiting: () => {},
};
const fetchStub = async (url, init = {}) => {
  const form = init.body instanceof FormData ? Object.fromEntries(init.body.entries()) : init.body;
  fetched.push({ url, method: init.method, form });
  const status = cmd.status || 200;
  return { ok: status < 300, status, json: async () => ({ detail: cmd.detail || '' }),
           body: { getReader: () => ({ read: async () => ({ done: true }), cancel: async () => {} }) } };
};
vm.runInNewContext(src, { self, caches: {}, fetch: fetchStub, URL, FormData, console, setTimeout, Response, Request, Headers, Map, Set });
(async () => {
  const waits = [];
  const ev = (extra) => ({ waitUntil: (p) => waits.push(p), ...extra });
  const data = cmd.payload;
  handlers.push(ev({ data: { json: () => data, text: () => JSON.stringify(data) } }));
  await Promise.all(waits.splice(0));
  if (cmd.action !== undefined) {
    handlers.notificationclick(ev({ action: cmd.action, notification: { data: shown[0].opts.data, close() {} } }));
    await Promise.all(waits.splice(0));
  }
  process.stdout.write(JSON.stringify({ shown, fetched, opened }));
})();
""")


def _sw(command: dict) -> dict:
    proc = subprocess.run(["node", "-e", _HARNESS], input=json.dumps(command), capture_output=True,
                          text=True, cwd=str(ROOT), timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


APPROVAL = {"type": "tool_approval", "title": "Pantheon is asking before it acts",
            "body": "Run a shell command: ls", "approval_id": "abc", "session_id": "s-1",
            "can_answer": True, "tag": "approval-abc"}


@_needs_node
def test_the_notification_offers_approve_and_deny():
    shown = _sw({"payload": APPROVAL})["shown"]
    assert [a["action"] for a in shown[0]["opts"]["actions"]] == ["approve", "deny"]
    assert shown[0]["opts"]["requireInteraction"] is True


@_needs_node
def test_a_runs_question_has_no_buttons():
    shown = _sw({"payload": {**APPROVAL, "can_answer": False}})["shown"]
    assert "actions" not in shown[0]["opts"]


@_needs_node
@pytest.mark.parametrize(("action", "decision", "word"), [
    ("approve", "approve_task", "Approved"), ("deny", "deny", "Denied")])
def test_a_button_answers_through_the_cards_route(action, decision, word):
    out = _sw({"payload": APPROVAL, "action": action})
    (call,) = out["fetched"]
    assert call["url"] == "/api/chat_stream" and call["method"] == "POST"
    assert call["form"] == {**SW_FORM, "session": "s-1", "tool_approval_id": "abc",
                            "tool_approval_decision": decision}
    assert out["shown"][-1]["title"] == word


@_needs_node
def test_a_refused_answer_says_why():
    out = _sw({"payload": APPROVAL, "action": "approve", "status": 409,
               "detail": "This approval expired. Ask again."})
    assert out["shown"][-1]["title"] == "That answer did not go through"
    assert "Ask again" in out["shown"][-1]["opts"]["body"]


@_needs_node
def test_tapping_the_notification_opens_the_chat():
    out = _sw({"payload": APPROVAL, "action": ""})
    assert out["fetched"] == [] and out["opened"] == ["/#s-1"]
