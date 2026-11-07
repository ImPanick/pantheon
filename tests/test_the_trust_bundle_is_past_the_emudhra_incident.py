# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1925` — the CA bundle HTTPS is checked against is one from after the
eMudhra incident.

**Before the fix** `requirements.txt` named no `certifi`, so a venv took the
release that was current the day it was made and kept it: the launchers
reinstall only when this file changes, and never upgrade. httpx checks HTTPS
against that bundle, a model provider's calls among them
(`src/tls_overrides.llm_verify` falls through to httpx's default). Every
release from 2025.11.12 to 2026.7.22 still trusts emSign ECC Root CA - G3, a
root of the incident, and none came out between the fork (2026-08-20) and
2026-10-18, so a venv made in that window holds one of them.

Now `certifi==2026.10.23` is pinned, which also makes an old venv take the new
bundle on its next launch. It is a pin, not upstream Odysseus's `>=2026.10.19`
range, because `check-pins.py` refuses a range (`B320`), and it says why it is
there with nothing importing it (`B1548`). Ported from upstream a98013dd
(#6785).

Read from the file, through `check-pins.py`'s own functions; nothing here
imports `certifi`, which would make its `Not imported:` note untrue.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / ".pantheon" / "check-pins.py"

#: Upstream #6785's floor, the first release it took as past the incident.
FLOOR = (2026, 10, 19)


def _checker():
    spec = importlib.util.spec_from_file_location("_pantheon_check_pins_b1925", CHECKER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_trust_bundle_is_pinned_past_the_emudhra_incident():
    pins = _checker()
    path = ROOT / "requirements.txt"
    found = [(number, spec) for number, _line, name, spec in pins.parse_requirements(path)
             if (name or "").lower() == "certifi"]
    assert found, "requirements.txt pins no certifi, so a venv keeps the bundle it was made with"
    number, spec = found[0]
    assert spec.startswith("==") and not spec.startswith("==="), spec
    version = tuple(int(part) for part in spec[2:].strip().split(".")[:3])
    assert version >= FLOOR, spec
    note = pins._comment_block_above(path.read_text(encoding="utf-8").splitlines(), number)
    assert note.startswith("Not imported:") and "emSign" in note, note
