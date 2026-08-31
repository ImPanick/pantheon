#!/usr/bin/env python3
"""Update the bundled skill library from upstream. Explicit, never automatic.

    python3 scripts/update-skill-library.py --check     # what would change
    python3 scripts/update-skill-library.py --apply     # do it

`Law 16` is why this is a script you run and not a job that runs. Pantheon ships
286 skills that work with no network at all; keeping them current is a thing an
operator chooses to do, on a day they choose, not something the product does to
itself on boot. An auto-updating bundle is an external dependency wearing a
different hat -- and it is also a supply-chain hole, because it turns "review
the diff" into "hope upstream is fine".

What this does:
  * fetches the upstream tree through the outbound limiter (`P15`), so the
    update is paced and honours a rate limit like everything else;
  * writes SKILL.md files only -- no scripts, no assets, no docs. We ship prose
    an agent reads, not third-party code that runs on the user's machine;
  * regenerates MANIFEST.json with the new commit and per-file checksums, so
    the next reviewer can see exactly what moved.

It never touches `data/skills/` -- the user's own skills are a separate layer
and a bundled skill of the same name is already shadowed by theirs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
LIB = REPO / "library" / "ecc"
UPSTREAM = "https://github.com/affaan-m/ECC"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _load_manifest() -> dict:
    try:
        return json.loads((LIB / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _pace() -> None:
    """Same politeness as every other outbound call in this product."""
    sys.path.insert(0, str(REPO))
    try:
        from src.rate_limiter import outbound

        outbound.acquire("github.com")
    except Exception:
        pass


def _fetch(dest: pathlib.Path) -> tuple[str, str]:
    """Shallow-clone upstream. Returns (commit, version)."""
    _pace()
    subprocess.run(
        ["git", "clone", "--depth", "1", f"{UPSTREAM}.git", str(dest)],
        check=True, capture_output=True, text=True, timeout=600,
    )
    commit = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    version_file = dest / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "unknown"
    return commit, version


def _collect(src: pathlib.Path) -> dict[str, str]:
    """name -> SKILL.md text, for every skill directory upstream."""
    out: dict[str, str] = {}
    skills = src / "skills"
    if not skills.is_dir():
        return out
    for d in sorted(p for p in skills.iterdir() if p.is_dir()):
        f = d / "SKILL.md"
        if f.exists():
            out[d.name] = f.read_text(encoding="utf-8", errors="replace")
    return out


def _diff(current: dict, incoming: dict[str, str]) -> tuple[list, list, list]:
    have = set(current.get("files", {}))
    now = set(incoming)
    added = sorted(now - have)
    removed = sorted(have - now)
    changed = sorted(
        n for n in (have & now)
        if current["files"][n] != _digest(incoming[n])
    )
    return added, removed, changed


def _parses(text: str) -> bool:
    """Would Pantheon's own parser accept this? A skill it cannot read is not an
    update, it is a regression, and the check is two lines."""
    sys.path.insert(0, str(REPO))
    try:
        from services.memory.skill_format import Skill

        sk = Skill.from_markdown(text)
        return bool(sk.name and (sk.description or "").strip())
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the update (default is a dry run)")
    ap.add_argument("--check", action="store_true", help="dry run; exit 1 if an update is available")
    args = ap.parse_args()

    current = _load_manifest()
    print(f"installed: {current.get('version', '?')} @ {current.get('commit', '?')[:12]} "
          f"({current.get('skills', 0)} skills)")

    with tempfile.TemporaryDirectory() as tmp:
        dest = pathlib.Path(tmp) / "ecc"
        try:
            commit, version = _fetch(dest)
        except subprocess.CalledProcessError as e:
            print(f"fetch failed: {(e.stderr or '').strip()[:300]}", file=sys.stderr)
            return 2
        except subprocess.TimeoutExpired:
            print("fetch timed out", file=sys.stderr)
            return 2

        incoming = _collect(dest)
        print(f"upstream : {version} @ {commit[:12]} ({len(incoming)} skills)")

        if commit == current.get("commit"):
            print("\nalready up to date.")
            return 0

        added, removed, changed = _diff(current, incoming)
        unreadable = sorted(n for n, t in incoming.items() if not _parses(t))

        print(f"\n  + {len(added)} added   ~ {len(changed)} changed   - {len(removed)} removed")
        for label, names in (("+", added), ("~", changed), ("-", removed)):
            for n in names[:10]:
                print(f"    {label} {n}")
            if len(names) > 10:
                print(f"    {label} ... and {len(names) - 10} more")
        if unreadable:
            print(f"\n  !! {len(unreadable)} upstream skills do NOT parse with this "
                  f"product's reader and would be shipped broken:")
            for n in unreadable[:10]:
                print(f"    !! {n}")
            print("  Refusing to apply. Fix the reader or exclude them deliberately.")
            return 3

        if not args.apply:
            print("\ndry run. re-run with --apply to write it.")
            return 1

        skills_dir = LIB / "skills"
        if skills_dir.exists():
            shutil.rmtree(skills_dir)
        for name, text in incoming.items():
            d = skills_dir / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(text, encoding="utf-8")
        lic = dest / "LICENSE"
        if lic.exists():
            shutil.copy(lic, LIB / "LICENSE")
            shutil.copy(lic, REPO / "licenses" / "ECC-MIT.txt")

        files = {n: _digest(t) for n, t in sorted(incoming.items())}
        content = hashlib.sha256("".join(f"{n}:{h}" for n, h in files.items()).encode()).hexdigest()
        manifest = {
            "source": UPSTREAM,
            "licence": "MIT",
            "copyright": current.get("copyright", "Copyright (c) 2026 Affaan Mustafa"),
            "version": version,
            "commit": commit,
            "vendored_at": __import__("datetime").date.today().isoformat(),
            "skills": len(files),
            "content_sha256": content,
            "vendored": "SKILL.md files only — no scripts, assets or docs",
            "files": files,
        }
        (LIB / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                           encoding="utf-8")
        print(f"\nupdated to {version} @ {commit[:12]}. Review the diff before committing.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
