#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
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
    python3 scripts/fetch-pyodide.py --version 314.0.9  # a different release

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

VERSION = "314.0.8"

# SHA-256 of each vendored file. First recorded 2026-09-01 for 0.27.5 and
# cross-checked against cdn.jsdelivr.net. `B2215`, 2026-11-24: 314.0.8, the
# newest release on npm (`dist-tags.latest`, the CPython-aligned line: Python
# 3.14), read out of the tarball whose sha512 the registry publishes. The
# runtime's JavaScript half is `pyodide.asm.mjs` from 0.28 on, an ES module
# `pyodide.js` loads with `import()` -- `pyodide.asm.js` is gone -- so the file
# list moved as well as the hashes.
PINNED = {
    "pyodide.js":
        "d4e1e0f06c29162eadf0c3f323c746884242b257d1faa94760442a4ac929e9a1",
    "pyodide.asm.mjs":
        "22514b8be6980e28a02c8b1d6387ce8dfe666fc4edf8d547cff5dce29ff4d972",
    "pyodide.asm.wasm":
        "e14d49ceca9b4a0e274ea918f3a898de2d3880b6e5573a6cfe1a2267ecc70329",
    "python_stdlib.zip":
        "2bd3394a145bfbbe5bbc9d9d6ab9136abbb986c6fef6c142b3a2962227aa5c28",
    "pyodide-lock.json":
        "5dc2fc119108bc148c7457dc86e7675b5c87e1cafd420b9c34c1eaef7b36c010",
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

    # newline="\n" is load-bearing on Windows. `write_text` opens in text mode,
    # which translates every \n to os.linesep -- so the same script run on the
    # two machines this repo is developed on produced files that differed by
    # 16 bytes. It survived only because `.gitattributes` normalises text in the
    # index, which is git covering for the script rather than the script being
    # right, and this is the one file in the tree whose whole job is recording
    # exact bytes.
    (DEST / "MANIFEST.json").open("w", encoding="utf-8", newline="\n").write(json.dumps({
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
    }, indent=2, sort_keys=True) + "\n")
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
