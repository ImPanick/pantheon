# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2170`: every DNS-pinned fetch sends through one transport, with one trust.

Four copies of the pinned transport had drifted: an integration's `api_call`
and the skill importer verified against certifi's bundle (or `SSL_CERT_FILE`
when set), web fetch and webhook delivery against the system's store. With no
`SSL_CERT_FILE`, a CA that only one of the two stores holds verified for half
the product and failed for the other half. The owner's pick
(`D-2026-11-24-02`): certifi plus `SSL_CERT_FILE` everywhere, in one transport
(`src/pinned_transport.py`).

Before the change, with `SSL_CERT_FILE` unset, the webhook and web-fetch
transports do not trust certifi's bundle, and four modules define a pinned
network backend. `SSL_CERT_FILE` itself was honoured by all four (OpenSSL reads
it for the system store too) and still is.
"""

from __future__ import annotations

import ast
import datetime as dt
import ipaddress
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
IP = ipaddress.ip_address("93.184.216.34")
CA_NAME = "Pantheon B2170 Test Corporate Root"


@pytest.fixture
def corporate_ca(tmp_path, monkeypatch):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    pem = tmp_path / "corporate-root.pem"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    monkeypatch.setenv("SSL_CERT_FILE", str(pem))
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    return pem


@pytest.fixture
def certifi_holds_only_the_corporate_ca(corporate_ca, monkeypatch):
    """certifi's bundle is a file holding just the test CA, and nothing names
    another store, so a transport trusts the test CA only if it reads certifi."""
    import certifi

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(certifi, "where", lambda: str(corporate_ca))
    return corporate_ca


def _trusted_names(transport) -> set[str]:
    ctx = transport._pool._ssl_context
    names = set()
    for cert in ctx.get_ca_certs():
        for rdn in cert.get("subject", ()):
            for key, value in rdn:
                if key == "commonName":
                    names.add(value)
    return names


def _transports():
    from services.memory import skill_importer
    from src import integrations, outbound_fetch, webhook_manager

    return {
        "web fetch": outbound_fetch._PinnedTransport(IP),
        "webhook delivery": webhook_manager._PinnedAsyncTransport(IP),
        "integration api_call": integrations._PinnedAsyncTransport([IP]),
        "skill importer": skill_importer._PinnedTransport([IP]),
    }


def test_every_pinned_transport_trusts_certifi_when_ssl_cert_file_is_unset(
        certifi_holds_only_the_corporate_ca):
    ignoring = [what for what, t in _transports().items() if CA_NAME not in _trusted_names(t)]
    assert not ignoring, f"these pinned transports do not trust certifi's bundle: {ignoring}"


def test_every_pinned_transport_trusts_the_ca_in_ssl_cert_file(corporate_ca):
    missing = [what for what, t in _transports().items() if CA_NAME not in _trusted_names(t)]
    assert not missing, f"these pinned transports ignore SSL_CERT_FILE: {missing}"


def test_every_pinned_transport_is_the_one_shared_transport():
    from src.pinned_transport import PinnedAsyncTransport, PinnedTransport

    for what, transport in _transports().items():
        assert isinstance(transport, (PinnedTransport, PinnedAsyncTransport)), what


def _defines_a_pinned_backend(tree: ast.AST) -> list[str]:
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                text = ast.unparse(base)
                if text.endswith(("NetworkBackend", "AsyncNetworkBackend")):
                    hits.append(node.name)
    return hits


def test_one_module_defines_the_pinned_network_backend():
    owners = {}
    for root in ("src", "routes", "core", "services", "mcp_servers"):
        for path in (REPO / root).rglob("*.py"):
            hits = _defines_a_pinned_backend(ast.parse(path.read_text(encoding="utf-8")))
            if hits:
                owners[path.relative_to(REPO).as_posix()] = hits
    assert set(owners) == {"src/pinned_transport.py"}, owners
