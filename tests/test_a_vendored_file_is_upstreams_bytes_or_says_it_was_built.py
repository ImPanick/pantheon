# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B426` — a vendored script that is secretly a bundle fails the freshness job.

`check-licences.py` rule 8 checks a `single` answer — *upstream's own artifact
for one package* — two ways: derivation finds no module paths, and every legal
comment in the file is claimed. A bundler that strips both produces exactly
that absence (`qrcode.min.js` was such a file: esbuild `--minify`, no
`node_modules/` strings, no `/*!` block, `dijkstrajs` inside it), so rule 8
made a self-built artifact *declarable* and not *detectable*.

Option (b), under `Law 16` in the network job rather than the offline gate:
`.pantheon/vendored-freshness.py` downloads the tarball each record's `source`
names and finds every shipped file's bytes in it. A file it does not hold is
listed under *Shipped bytes upstream's own artifact does not contain* and fails
the run; a `build` entry is ours by declaration and is not asked.

Driven offline: the real `tarball_digests` reading a `.tgz` written here
(through a `file://` URL), the real `ask`/`decide`, and the real record export.
Measured against the registry on 2026-10-27: all 34 files shipped from the nine
tarball-sourced records are upstream's bytes; SheetJS, whose source is a CDN
directory, is named under *Could not be asked*.
"""
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".pantheon" / "vendored-freshness.py"
CHECKER = ROOT / ".pantheon" / "check-vendored-versions.py"

UPSTREAM_JS = b"/*! tiny v1.0.0 | MIT */\n!function(){window.tiny=1}();\n"
# What esbuild --minify makes of two packages: no module path, no legal comment.
SECRET_BUNDLE = b'(()=>{var a=function(e){return e*2};window.tiny=a(1)})();\n'


@pytest.fixture(scope="module")
def vf():
    spec = importlib.util.spec_from_file_location("_vendored_freshness_b426", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def tgz(tmp_path):
    path = tmp_path / "tiny-1.0.0.tgz"
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo("package/dist/tiny.min.js")
        info.size = len(UPSTREAM_JS)
        tar.addfile(info, io.BytesIO(UPSTREAM_JS))
    return path.as_uri()


def _rec(source, files, built=False):
    return {"entry": "tiny", "package": "tiny", "version": "1.0.0", "registry": "npm",
            "source": source, "behind_ok": "", "osv_known": {}, "contains": [],
            "built": built, "files": files}


def _ask(vf, recs):
    return vf.ask(recs, dist_tags=lambda p: {"latest": "1.0.0"}, advisories=lambda p, v: [])


def test_upstreams_own_bytes_are_found_and_pass(vf, tgz):
    found = _ask(vf, [_rec(tgz, {"static/lib/tiny.min.js": _sha(UPSTREAM_JS)})])
    assert found["upstream"] == ["tiny: static/lib/tiny.min.js = package/dist/tiny.min.js"]
    assert found["foreign"] == [] and vf.decide(found) == 0


def test_a_secret_bundle_answering_single_fails_the_job(vf, tgz, capsys):
    """The row's `Verify:`. No module paths, no legal comments — rule 8 has
    nothing to object to — and upstream's tarball does not hold these bytes."""
    rc = vf.main(records=[_rec(tgz, {"static/lib/tiny.min.js": _sha(SECRET_BUNDLE)})],
                 dist_tags=lambda p: {"latest": "1.0.0"}, advisories=lambda p, v: [],
                 tarball=vf.tarball_digests)
    out = capsys.readouterr().out
    assert rc == 1
    assert "tiny: static/lib/tiny.min.js is in no file of" in out
    assert "answers `build`, not `single`" in out


def test_a_file_we_built_is_not_asked(vf, tgz):
    found = _ask(vf, [_rec(tgz, {"static/lib/tiny.min.js": _sha(SECRET_BUNDLE)}, built=True)])
    assert found["foreign"] == [] and found["upstream"] == []


def test_a_source_with_no_tarball_is_named_not_skipped(vf):
    found = _ask(vf, [_rec("https://cdn.example.invalid/tiny-1.0.0/",
                           {"static/lib/tiny.min.js": _sha(UPSTREAM_JS)})])
    assert any("no tarball named" in line for line in found["unknown"])
    assert vf.decide(found) == 0


def test_an_unreadable_tarball_is_unanswered_not_a_pass(vf, tmp_path):
    bad = tmp_path / "broken.tgz"
    bad.write_bytes(b"not a gzip")
    found = _ask(vf, [_rec(bad.as_uri(), {"static/lib/tiny.min.js": _sha(UPSTREAM_JS)})])
    assert any("could not be read" in line for line in found["unknown"])
    assert found["upstream"] == []


def test_the_record_exports_what_it_ships():
    """The real record carries each library's files and hashes to the job —
    the manifest-backed ones (Pyodide, Swagger UI) resolved from their
    manifests."""
    out = subprocess.run([sys.executable, str(CHECKER), "--json"], capture_output=True,
                         text=True, check=True, cwd=str(ROOT)).stdout
    records = {r["entry"]: r for r in json.loads(out)}
    assert records["Mermaid"]["files"] == {
        "static/lib/mermaid.min.js": _sha((ROOT / "static/lib/mermaid.min.js").read_bytes())}
    assert any(p.endswith("pyodide.asm.wasm") for p in records["Pyodide"]["files"])
    assert all(r["files"] for r in records.values())
