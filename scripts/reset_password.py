#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Set a person's password where Pantheon's data lives — the way back from a
lost admin password (`B1272`, `D-2026-10-26-01` §3).

    python scripts/reset_password.py <username> [--disable-2fa] [--password-stdin]

**Stop Pantheon first, and start it again after.** It reads its accounts when
it starts, so a server left running keeps answering the old password — and can
write its own copy back over this one.

    docker compose stop pantheon
    docker compose run --rm pantheon python scripts/reset_password.py ada
    docker compose start pantheon

The new password is asked for twice and never echoed; `--password-stdin` reads
one line instead (for a script). It is never taken from the command line, where
`ps` would show it. Every session the person had is signed out. `--disable-2fa`
also turns their two-factor sign-in off, for a lost authenticator. Nothing else
about the account — its admin rights, its privileges, its data — changes.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read_password(from_stdin: bool, stdin=None, prompt=getpass.getpass) -> str:
    if from_stdin:
        line = (stdin or sys.stdin).readline()
        return line.rstrip("\r\n")
    first = prompt("New password: ")
    again = prompt("Again: ")
    if first != again:
        raise SystemExit("The two passwords differ. Nothing was changed.")
    return first


def main(argv=None, *, stdin=None, prompt=getpass.getpass, auth_path=None) -> int:
    ap = argparse.ArgumentParser(prog="reset_password.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("username")
    ap.add_argument("--disable-2fa", action="store_true", help="also turn two-factor sign-in off")
    ap.add_argument("--password-stdin", action="store_true", help="read the password from one line of stdin")
    args = ap.parse_args(argv)

    from core.auth import DEFAULT_AUTH_PATH, AuthManager
    from src.constants import PASSWORD_MIN_LENGTH

    path = auth_path or DEFAULT_AUTH_PATH
    if not os.path.exists(path):
        print(f"There is no account file at {path}. Run this where Pantheon's data is "
              "(in Docker: `docker compose run --rm pantheon python scripts/reset_password.py …`).",
              file=sys.stderr)
        return 2
    mgr = AuthManager(path)
    if mgr._load_error:
        print(f"{path} could not be read ({mgr._load_error}). Repair it first; nothing was changed.",
              file=sys.stderr)
        return 2
    name = args.username.strip().lower()
    if name not in mgr.users:
        known = ", ".join(sorted(mgr.users)) or "none"
        print(f"There is no account “{args.username}”. The accounts are: {known}.", file=sys.stderr)
        return 1
    password = read_password(args.password_stdin, stdin=stdin, prompt=prompt)
    if len(password) < PASSWORD_MIN_LENGTH:
        print(f"A password is at least {PASSWORD_MIN_LENGTH} characters. Nothing was changed.",
              file=sys.stderr)
        return 1
    ended = mgr.reset_password(name, password, disable_2fa=args.disable_2fa)
    extra = " Two-factor sign-in is off; they can turn it on again in Settings → Account." \
        if args.disable_2fa else ""
    print(f"Done: {name}'s password is set, and {ended} session(s) were signed out.{extra} "
          "Start Pantheon again — it reads accounts when it starts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
