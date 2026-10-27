# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1556` — the non-streamed model call trusts `LLM_CA_BUNDLE` as the
streamed one does.

`src/tls_overrides.py` exists for a provider whose certificate is signed by a
private root (GigaChat, an on-premise gateway): the operator points
`LLM_CA_BUNDLE` at that root and `llm_verify()` layers it over the default
trust store. The streamed path's shared clients were built with it
(`_get_http_client`, `_client_for`); the plain call — `llm_call`, which every
background job and the chat fallback use — went through `_post_routed`, whose
`httpx.Client` took the default trust store. So the same provider answered a
chat and failed a summary with `CERTIFICATE_VERIFY_FAILED`.

Driven, not grepped (`Law 20`): a CA and a leaf it signed for `127.0.0.1` are
minted here, a real TLS listener speaks the OpenAI shape with that leaf, and
the real `llm_call` is pointed at it — once with the bundle (it answers), once
without (it is refused), so the bundle is shown to be what makes the
difference rather than assumed to be.
"""
from __future__ import annotations

import datetime
import ipaddress
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import HTTPException

import src.llm_core as llm_core
import src.tls_overrides as tls_overrides

_PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
               "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy")


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    """A private root, and a server certificate it signed for 127.0.0.1."""
    root = tmp_path_factory.mktemp("private-ca")
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = (x509.CertificateBuilder()
          .subject_name(_name("Pantheon test private root")).issuer_name(_name("Pantheon test private root"))
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - datetime.timedelta(minutes=5))
          .not_valid_after(now + datetime.timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                       content_commitment=False, key_encipherment=False,
                                       data_encipherment=False, key_agreement=False,
                                       encipher_only=False, decipher_only=False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (x509.CertificateBuilder()
            .subject_name(_name("model.test")).issuer_name(ca.subject)
            .public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                           critical=False)
            .sign(ca_key, hashes.SHA256()))
    ca_pem = root / "private-root.pem"
    ca_pem.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_pem = root / "server.pem"
    cert_pem.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_pem = root / "server.key"
    key_pem.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM,
                                               serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
    return ca_pem, cert_pem, key_pem


@pytest.fixture
def provider(pki):
    """A model server on TLS, its certificate signed by the private root only.
    Answers the OpenAI chat shape, and records what it was asked."""
    _, cert_pem, key_pem = pki
    asked = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 — http.server's spelling
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            asked.append((self.path, json.loads(body or b"{}")))
            out = json.dumps({"choices": [{"message": {"role": "assistant",
                                                       "content": "signed by a root you named"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert_pem), str(key_pem))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_address[1]}/v1", asked
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _quiet_wire(monkeypatch):
    """The listener is on loopback; no proxy of this machine's may sit between
    (the same call in CI and here), and no earlier answer is served from the
    response cache."""
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(llm_core, "_response_cache", {})


def _trust(monkeypatch, bundle):
    """`LLM_CA_BUNDLE` as the process reads it at start: the path, and the
    context `_build_ssl_context` makes from it (`None` when unset)."""
    monkeypatch.setattr(tls_overrides, "_extra_bundle_path", str(bundle) if bundle else None)
    monkeypatch.setattr(tls_overrides, "_SHARED_SSL_CONTEXT", tls_overrides._build_ssl_context())


def test_the_plain_model_call_trusts_the_operators_bundle(monkeypatch, pki, provider):
    """The row's `Verify:` — `llm_call` to a TLS server the test CA signed,
    with `LLM_CA_BUNDLE` set to that CA, succeeds."""
    ca_pem, _, _ = pki
    url, asked = provider
    _trust(monkeypatch, ca_pem)
    assert isinstance(tls_overrides.llm_verify(), ssl.SSLContext), "the bundle did not load"
    got = llm_core.llm_call(url, "private-model", [{"role": "user", "content": "are you there"}])
    assert got == "signed by a root you named"
    assert asked and asked[-1][0] == "/v1/chat/completions"
    assert asked[-1][1]["model"] == "private-model"


def test_control_without_the_bundle_the_same_call_is_refused(monkeypatch, provider):
    """The premise: the certificate really is untrusted by default, so the
    passing case above is the bundle's doing. The refusal names the cause."""
    url, asked = provider
    _trust(monkeypatch, None)
    assert tls_overrides.llm_verify() is True
    with pytest.raises(HTTPException) as e:
        llm_core.llm_call(url, "private-model", [{"role": "user", "content": "are you there"}])
    assert e.value.status_code == 502
    assert "CERTIFICATE_VERIFY_FAILED" in str(e.value.detail), e.value.detail
    assert asked == []
