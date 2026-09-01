#!/usr/bin/env python3
"""Vendor Pyodide into static/lib/pyodide/ from a checksum-verified artifact.

Pyodide used to load from cdn.jsdelivr.net at the moment a user ran a Python
block -- and it did not work, because the CSP that let the *script* through
blocked the `.wasm` fetch that follows it. So the request left the machine and
the feature failed anyway: a leak with nothing to show for it (`P16-07`).

This script is how the bytes get here, and it is deliberately not a loop of five
`curl`s at a CDN. It downloads **one** artifact -- the npm registry tarball --
whose SHA-512 the registry publishes as `dist.integrity`, checks the archive
against that before opening it, and then checks every extracted file against a
hash pinned in this file. Two independent statements have to agree before
anything is written:

    registry says      : the tarball hashes to <dist.integrity>
    this file says     : each extracted file hashes to PINNED[name]

A CDN GET can only ever tell you what that CDN served you.

    python3 scripts/fetch-pyodide.py            # fetch, verify, write
    python3 scripts/fetch-pyodide.py --check     # verify what is on disk, write nothing
    python3 scripts/fetch-pyodide.py --version 0.28.0   # a different release

Run with no network and nothing on disk, it fails loudly rather than leaving a
half-populated directory -- Pyodide with a missing `python_stdlib.zip` starts
and then breaks on the first import, which is the worse failure.

WHY THE FIVE FILES AND NOT THE `full/` DISTRIBUTION. `full/` is ~250 packages
and hundreds of MB; these five are the runtime and the Python standard library,
nothing else. `codeRunner.js` never calls `loadPackage`, so nothing else was
ever being fetched -- `import numpy` raised `ModuleNotFoundError` against the
CDN too. Vendoring does not narrow what worked; it makes what already happened
happen locally. Adding a package later means adding its wheel here, on purpose,
which is the `Law 16` shape: nothing arrives without someone choosing it.
"""
import argparse
import hashlib
import io
import json
import pathlib
import shutil
import sys
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEST = ROOT / "static" / "lib" / "pyodide"
REGISTRY = "https://registry.npmjs.org/pyodide"

VERSION = "0.27.5"

# SHA-256 of each vendored file, recorded when it was first vendored
# (2026-09-01) and cross-checked: the bytes below are byte-identical to what
# cdn.jsdelivr.net serves at v0.27.5/full/, verified file by file. Two
# independent origins, one set of hashes.
PINNED = {
    "pyodide.js":
        "7fdbe66e53f68f6a4e93c295a667371759be093d2bd402bb44545514584039b6",
    "pyodide.asm.js":
        "3a889f073e628c2196c705b42fa0e955ba2e25c034b1e3dd589c35be675bc01b",
    "pyodide.asm.wasm":
        "f7fefe563134714a17abd65516d94960e8dbd96fe6778a7a842947fc9686b3a1",
    "python_stdlib.zip":
        "6030964967e447c887abc46c5f0967c55688644d759496de82a3ef09f49f5cba",
    "pyodide-lock.json":
        "be1807745da93daa09d360b109c17a0e526e74d664d1f1b9870aafcce98ce426",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_on_disk(pinned=PINNED) -> int:
    """Verify what is already vendored. No network, no writes."""
    bad = []
    for name, want in sorted(pinned.items()):
        f = DEST / name
        if not f.is_file():
            bad.append(f"MISSING  {name}")
            continue
        got = sha256(f.read_bytes())
        if got != want:
            bad.append(f"MISMATCH {name}\n         want {want}\n         got  {got}")
    for line in bad:
        print(line)
    if bad:
        print(f"\nFAIL: {len(bad)} problem(s). Run without --check to re-fetch.")
        return 1
    print(f"OK — Pyodide {VERSION}, {len(pinned)} files, every hash matches.")
    return 0


def fetch(version: str) -> int:
    print(f"pyodide {version} — asking the registry what the tarball should hash to")
    with urllib.request.urlopen(f"{REGISTRY}/{version}", timeout=60) as r:
        meta = json.load(r)
    tarball = meta["dist"]["tarball"]
    integrity = meta["dist"].get("integrity", "")

    print(f"  {tarball}")
    with urllib.request.urlopen(tarball, timeout=300) as r:
        blob = r.read()
    print(f"  {len(blob):,} bytes")

    # The registry's own statement about its own artifact, checked before the
    # archive is opened -- a tarfile is parsed code, and verifying after
    # extracting verifies nothing.
    if integrity.startswith("sha512-"):
        import base64
        want = integrity.split("-", 1)[1]
        got = base64.b64encode(hashlib.sha512(blob).digest()).decode()
        if got != want:
            print(f"FAIL: tarball integrity mismatch\n  want {want}\n  got  {got}")
            return 1
        print("  integrity OK (sha512 matches dist.integrity)")
    else:
        print(f"FAIL: registry published no sha512 integrity for {version}")
        return 1

    extracted = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for name in PINNED:
            member = tf.extractfile(f"package/{name}")
            if member is None:
                print(f"FAIL: {name} is not in the tarball")
                return 1
            extracted[name] = member.read()

    problems = []
    for name, data in extracted.items():
        got = sha256(data)
        want = PINNED.get(name)
        if want and got != want:
            problems.append(f"  {name}\n    want {want}\n    got  {got}")
    if problems:
        print("FAIL: extracted files do not match the pinned hashes.")
        print("\n".join(problems))
        print("\nIf this is an intended version bump, update PINNED and say so in "
              "the commit.\nIf it is not, something replaced bytes the registry "
              "already vouched for.")
        return 1

    # Everything verified: only now does anything touch the working tree.
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    for name, data in sorted(extracted.items()):
        (DEST / name).write_bytes(data)
        print(f"  wrote {name}  ({len(data):,} bytes)")

    (DEST / "MANIFEST.json").write_text(json.dumps({
        "package": "pyodide",
        "version": version,
        "licence": "MPL-2.0",
        "source": "https://registry.npmjs.org/pyodide",
        "tarball": tarball,
        "tarball_integrity": integrity,
        "files": {n: sha256(d) for n, d in sorted(extracted.items())},
        "note": ("Runtime and Python standard library only — no packages. "
                 "codeRunner.js never calls loadPackage; adding one means "
                 "vendoring its wheel here deliberately."),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"  wrote MANIFEST.json")
    print(f"\nOK — Pyodide {version} vendored to static/lib/pyodide/")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="verify what is on disk; no network, no writes")
    ap.add_argument("--version", default=VERSION)
    args = ap.parse_args()
    if args.check:
        return check_on_disk()
    return fetch(args.version)


if __name__ == "__main__":
    sys.exit(main())
