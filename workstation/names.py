# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P27-04` · A person's names and pinned certificates, in their workstation.
`D-2026-10-24-03`.

Pantheon sends the account's whole set at once (`ROUTES["names"]`):
`{"map": {name: address}, "pins": [{"origin", "pem"}]}`. This module keeps it
under the person's home (`.pantheon/names/`) and makes it so:

  * **the proxy** (`workstation/name_proxy.py`), started as the account with
    its `run_as` prefix while any name is mapped, stopped when none is;
  * **a PAC file** naming the mapped hosts only, which the person's Firefox is
    pointed at (`browser.py` adds the two prefs when it starts);
  * **the trusted file** — the system's CA bundle and the pinned certificates
    — that commands are given (`SSL_CERT_FILE`, `CURL_CA_BUNDLE`,
    `REQUESTS_CA_BUNDLE`, `GIT_SSL_CAINFO`), and for the browser its own
    exception list (`cert_override.txt`), each pin for its host and port and
    that certificate's fingerprint only. Measured: Firefox refuses a
    self-signed certificate imported into its store as a trusted peer
    (`MOZILLA_PKIX_ERROR_SELF_SIGNED_CERT`); the exception list is what it
    honours.

The answer says what commands should be given: `{"proxy": "http://127.0.0.1:N"
| null, "ca_file": path | null, "digest", "changed": bool}`. A change to what
the browser reads restarts the browser on its next action.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

NAMES_DIR = ".pantheon/names"
MAP_FILE = "map.json"
PAC_FILE = "names.pac"
TRUST_FILE = "trusted.pem"
PORT_FILE = "proxy.port"
PIN_DIR = "pins"
SYSTEM_BUNDLES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
                  "/etc/ssl/cert.pem")
NAMES_MAX = 64
PINS_MAX = 64
PEM_MAX = 16 * 1024
_NAME_RE = re.compile(r"[a-z0-9]([a-z0-9-]{0,62})(\.[a-z0-9]([a-z0-9-]{0,62}))*")
_PEM_RE = re.compile(r"-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----\s*")


class NamesRefused(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def clean(body: Dict[str, Any]) -> Dict[str, Any]:
    raw_map = body.get("map") or {}
    raw_pins = body.get("pins") or []
    if not isinstance(raw_map, dict) or len(raw_map) > NAMES_MAX:
        raise NamesRefused(f"“map” is at most {NAMES_MAX} names, each to an address.")
    if not isinstance(raw_pins, list) or len(raw_pins) > PINS_MAX:
        raise NamesRefused(f"“pins” is at most {PINS_MAX} certificates.")
    out_map: Dict[str, str] = {}
    for name, addr in raw_map.items():
        n = str(name).strip().lower().rstrip(".")
        if not _NAME_RE.fullmatch(n) or len(n) > 253:
            raise NamesRefused(f"“{str(name)[:60]}” is not a host name.")
        try:
            out_map[n] = str(ipaddress.ip_address(str(addr).strip()))
        except ValueError:
            raise NamesRefused(f"“{str(addr)[:60]}” is not an address.") from None
    pins = []
    for p in raw_pins:
        if not isinstance(p, dict) or not isinstance(p.get("pem"), str) or len(p["pem"]) > PEM_MAX \
                or not _PEM_RE.fullmatch(p["pem"].strip() + "\n"):
            raise NamesRefused("A pin is {origin, pem}: one PEM certificate.")
        pins.append({"origin": str(p.get("origin") or "")[:300], "pem": p["pem"].strip() + "\n"})
    return {"map": dict(sorted(out_map.items())), "pins": pins}


def pac(names: Dict[str, str], port: int) -> str:
    hosts = json.dumps(sorted(names))
    return ("// Written by the Pantheon workstation (`workstation/names.py`): the names this\n"
            "// person mapped go through their own proxy; everything else is direct.\n"
            "function FindProxyForURL(url, host) {\n"
            f"  var mapped = {hosts};\n"
            "  if (mapped.indexOf(host.toLowerCase()) >= 0) return 'PROXY 127.0.0.1:" + str(port) + "';\n"
            "  return 'DIRECT';\n}\n")


class AccountNames:
    """One account's names: files, proxy process, and what was last applied."""

    def __init__(self, home: Path, prefix: List[str], env: Dict[str, str],
                 own: Optional[Callable[[List[Path]], None]] = None):
        self.dir = Path(home) / NAMES_DIR
        self.prefix = prefix
        self.env = dict(env)
        self.own = own
        self.proc: Optional[subprocess.Popen] = None
        self.port: Optional[int] = None
        self.digest = ""
        self.lock = threading.Lock()

    # -- what the browser reads ------------------------------------------------

    def browser_prefs(self) -> str:
        pac_path = self.dir / PAC_FILE
        if not (self.port and pac_path.exists()):
            return ""
        return ('user_pref("network.proxy.type", 2);\n'
                f'user_pref("network.proxy.autoconfig_url", "{pac_path.as_uri()}");\n')

    def pins(self) -> List[Path]:
        d = self.dir / PIN_DIR
        return sorted(d.glob("*.pem")) if d.exists() else []

    def import_pins(self, profile: Path) -> List[str]:
        """Trust each pinned certificate in the browser profile, as that
        server's certificate only: Firefox's own exception list
        (`cert_override.txt`, keyed by host, port and the certificate's SHA-256
        — what *Accept the risk* writes), so a different certificate at the
        same address is still refused. Answers what could not be done."""
        pins = self.pins()
        overrides = []
        meta = self.dir / PIN_DIR / "origins.json"
        try:
            by_file = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        except ValueError:
            by_file = {}
        for pem in pins:
            origin = by_file.get(pem.stem, "")
            hostport = origin.split("://", 1)[-1].rstrip("/")
            if not hostport:
                continue
            if ":" not in hostport.rsplit("]", 1)[-1]:
                hostport += ":443"
            overrides.append(f"{hostport}:\tOID.2.16.840.1.101.3.4.2.1\t{_fingerprint(pem)}\t")
        override = profile / "cert_override.txt"
        if overrides:
            _write(override, "# PSM Certificate Override Settings file\n# Written by the Pantheon workstation "
                             "(`workstation/names.py`): the certificates this person pinned.\n"
                             + "\n".join(overrides) + "\n")
            if self.own:
                self.own([override])
        elif override.exists():
            override.unlink()
        return []

    # -- applying a set --------------------------------------------------------

    def apply(self, body: Dict[str, Any]) -> Dict[str, Any]:
        got = clean(body)
        digest = hashlib.sha256(json.dumps(got, sort_keys=True).encode()).hexdigest()[:16]
        with self.lock:
            changed = digest != self.digest
            self.dir.mkdir(parents=True, exist_ok=True)
            made = [self.dir.parent, self.dir]
            map_path = self.dir / MAP_FILE
            _write(map_path, json.dumps({"map": got["map"]}))
            made.append(map_path)
            pin_dir = self.dir / PIN_DIR
            if pin_dir.exists():
                for old in pin_dir.glob("*.pem"):
                    old.unlink()
            trust = self.dir / TRUST_FILE
            if got["pins"]:
                pin_dir.mkdir(exist_ok=True)
                made.append(pin_dir)
                origins = {}
                for p in got["pins"]:
                    f = pin_dir / (hashlib.sha256(p["pem"].encode()).hexdigest()[:16] + ".pem")
                    _write(f, p["pem"])
                    made.append(f)
                    origins[f.stem] = p["origin"]
                _write(pin_dir / "origins.json", json.dumps(origins))
                made.append(pin_dir / "origins.json")
                system = next((Path(b) for b in SYSTEM_BUNDLES if Path(b).exists()), None)
                bundle = (system.read_text(encoding="utf-8", errors="replace") if system else "")
                _write(trust, bundle + "\n" + "".join(p["pem"] for p in got["pins"]))
                made.append(trust)
            elif trust.exists():
                trust.unlink()
            if got["map"]:
                self._start_proxy(map_path)
                _write(self.dir / PAC_FILE, pac(got["map"], self.port))
                made.append(self.dir / PAC_FILE)
            else:
                self._stop_proxy()
                if (self.dir / PAC_FILE).exists():
                    (self.dir / PAC_FILE).unlink()
            if self.own:
                self.own([p for p in made if p.exists()])
            self.digest = digest
            return {"proxy": f"http://127.0.0.1:{self.port}" if self.port else None,
                    "ca_file": str(trust) if got["pins"] else None,
                    "names": sorted(got["map"]), "pins": len(got["pins"]),
                    "digest": digest, "changed": changed}

    def _start_proxy(self, map_path: Path) -> None:
        if self.proc is not None and self.proc.poll() is None and self.port:
            return   # it re-reads the map file on every request
        port_file = self.dir / PORT_FILE
        if port_file.exists():
            port_file.unlink()
        if self.own:
            self.own([self.dir])
        env = dict(self.env)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        argv = self.prefix + [sys.executable, "-m", "workstation.name_proxy",
                              "--map", str(map_path), "--port-file", str(port_file)]
        self.proc = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
        end = time.monotonic() + 10
        while time.monotonic() < end:
            if port_file.exists():
                try:
                    self.port = int(port_file.read_text().strip())
                    return
                except ValueError:
                    pass   # the file is being written; read it again
            if self.proc.poll() is not None:
                break
            time.sleep(0.05)
        self._stop_proxy()
        raise NamesRefused("The names proxy did not start in this workstation.")

    def _stop_proxy(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.port = None

    def stop(self) -> None:
        with self.lock:
            self._stop_proxy()


def _fingerprint(pem_file: Path) -> str:
    """`AB:CD:…`, the SHA-256 of the certificate's DER, as Firefox writes it."""
    import base64
    body = "".join(l for l in pem_file.read_text().splitlines() if l and "CERTIFICATE" not in l)
    return ":".join(f"{b:02X}" for b in hashlib.sha256(base64.b64decode(body)).digest())


def _write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
