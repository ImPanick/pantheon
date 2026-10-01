#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Install the showcase's fictional skill package into a data directory.

Run by `capture.py` in the **server's** interpreter (the one with Pantheon's
requirements), before the server starts:

    python scripts/showcase/offline_package.py --data-dir /tmp/x --owner rowan

Why this is not a request: the import route fetches the package from GitHub and
a capture must not reach the internet (`Law 16`). This hands the importer's own
`install_package` — what the route calls after its fetch — a package built
from `seed.PACKAGE`. See `seed.py`'s docstring.
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--owner", required=True)
    args = ap.parse_args(argv)
    # The data directory is read when `src.constants` is first imported, so it
    # is set before anything from the product is.
    os.environ["PANTHEON_DATA_DIR"] = args.data_dir
    sys.path[:0] = [str(ROOT), str(HERE)]
    import seed

    out = seed.install_demo_package(args.data_dir, owner=args.owner)
    print(json.dumps({"installed": out.get("installed"), "package": (out.get("package") or {}).get("id")
                      if isinstance(out.get("package"), dict) else out.get("package")}))
    return 0 if out.get("installed") else 1


if __name__ == "__main__":
    sys.exit(main())
