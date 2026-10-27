# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P27-05` · An account made for the agent, on a service the person runs.

The owner (2026-10-24): *"the user can map a URL on a local domain even, and
configure a local account on that service (assign rbac etc) and then store the
login details for the agent to login and automate."*

**What happens.** On a login the person already keeps for a service's
admin, *Set up an agent account*: they pick the kind of service, the role and
a user name, and press the button — that press is the yes. Pantheon then, from
where the person's shell runs (their workstation, `git_tools._Place`):

  1. makes a password nobody types (`secrets.token_urlsafe`),
  2. calls the service's own admin API with the admin login **by reference**
     — its values only in that one command's environment, as
     `shell_with_login` does — to create the user and give it the role,
  3. saves the new account as a vault item marked *agent account*, at the
     admin login's addresses, set to ask once per chat.

The password goes from step 1 to the service and the vault and nowhere else:
not the screen, not a transcript, not a log; the command's output is scrubbed
of every value before anything reads it.

**Templates**, one per service whose API makes a user and sets a role:
Grafana (org role Viewer, Editor or Admin), Gitea and Forgejo (a user, or a
site admin), Nextcloud (a user, optionally in the admin group). A service not
listed is stored, not configured: make the account in its own admin page and
add it as a login.
"""

from __future__ import annotations

import re
import secrets
from typing import Any, Dict, List, Optional

TIMEOUT_S = 30.0
USERNAME_RE = re.compile(r"[a-z][a-z0-9_.-]{1,38}")

# Each template: its roles (the service's own words) and the commands that make
# the user and give the role. `$A_USER`/`$A_PASS` are the admin login, `$N_USER`/
# `$N_PASS` the new account, `$URL` the service. Every command fails on an HTTP
# error (`--fail-with-body`), so a refusal stops the plan and is said.
_CURL = "curl -sS --fail-with-body -k --max-time 20"

TEMPLATES: Dict[str, Dict[str, Any]] = {
    "grafana": {
        "label": "Grafana",
        "roles": ["Viewer", "Editor", "Admin"],
        "steps": lambda role: [
            # Make the user, then set its role in the default organisation.
            (f'{_CURL} -u "$A_USER:$A_PASS" -H "Content-Type: application/json" '
             '-X POST "$URL/api/admin/users" '
             '-d "{\\"name\\":\\"$N_USER\\",\\"login\\":\\"$N_USER\\",\\"password\\":\\"$N_PASS\\",'
             '\\"email\\":\\"$N_USER@agent.invalid\\"}"'),
            (f'id=$({_CURL} -u "$A_USER:$A_PASS" "$URL/api/users/lookup?loginOrEmail=$N_USER" '
             '| python3 -c "import json,sys;print(json.load(sys.stdin)[\\"id\\"])") && '
             f'{_CURL} -u "$A_USER:$A_PASS" -H "Content-Type: application/json" -X PATCH '
             f'"$URL/api/org/users/$id" -d \'{{"role":"{role}"}}\''),
        ],
    },
    "gitea": {
        "label": "Gitea or Forgejo",
        "roles": ["User", "Site admin"],
        "steps": lambda role: [
            (f'{_CURL} -u "$A_USER:$A_PASS" -H "Content-Type: application/json" '
             '-X POST "$URL/api/v1/admin/users" '
             '-d "{\\"username\\":\\"$N_USER\\",\\"password\\":\\"$N_PASS\\",\\"email\\":\\"$N_USER@agent.invalid\\",'
             '\\"must_change_password\\":false}"'),
        ] + ([
            (f'{_CURL} -u "$A_USER:$A_PASS" -H "Content-Type: application/json" -X PATCH '
             '"$URL/api/v1/admin/users/$N_USER" '
             '-d "{\\"login_name\\":\\"$N_USER\\",\\"source_id\\":0,\\"admin\\":true}"'),
        ] if role == "Site admin" else []),
    },
    "nextcloud": {
        "label": "Nextcloud",
        "roles": ["User", "Admin"],
        "steps": lambda role: [
            (f'{_CURL} -u "$A_USER:$A_PASS" -H "OCS-APIRequest: true" -X POST '
             '"$URL/ocs/v1.php/cloud/users" --data-urlencode "userid=$N_USER" '
             '--data-urlencode "password=$N_PASS"'),
        ] + ([
            (f'{_CURL} -u "$A_USER:$A_PASS" -H "OCS-APIRequest: true" -X POST '
             '"$URL/ocs/v1.php/cloud/users/$N_USER/groups" --data-urlencode "groupid=admin"'),
        ] if role == "Admin" else []),
    },
}


class AccountRefused(ValueError):
    def __init__(self, sentence: str, status: int = 400):
        super().__init__(sentence)
        self.sentence = sentence
        self.status = status


def templates_public() -> List[Dict[str, Any]]:
    return [{"id": k, "label": t["label"], "roles": list(t["roles"])} for k, t in TEMPLATES.items()]


def plan(template: str, role: str) -> List[str]:
    t = TEMPLATES.get(template)
    if not t:
        raise AccountRefused(f"“{template}” is not a service Pantheon can configure. It sets up "
                             + ", ".join(x["label"] for x in TEMPLATES.values()) + ".")
    if role not in t["roles"]:
        raise AccountRefused(f"{t['label']}'s roles are {', '.join(t['roles'])}.")
    return t["steps"](role)


async def set_up(db, owner: Optional[str], admin_item: str, body: Dict[str, Any], *,
                 station_workspace: Optional[str] = None) -> Dict[str, Any]:
    """Make the account and keep it. Answers the new vault item (public)."""
    from src import vault as V
    from src.agent_tools.git_tools import _Place

    template = str(body.get("template") or "")
    role = str(body.get("role") or "")
    username = str(body.get("username") or "").strip().lower()
    steps = plan(template, role)
    if not USERNAME_RE.fullmatch(username):
        raise AccountRefused("The user name is 2–39 lower-case letters, digits, dots, dashes or underscores, "
                             "starting with a letter.")
    label = str(body.get("label") or "").strip() or f"{TEMPLATES[template]['label']} ({username})"
    from src.vault_names import with_db

    def check(session):
        if any(x.lower() == label.lower() for x in V.labels(session, owner)):
            raise AccountRefused(f"You already have an item named “{label}”; pick another name first.", 409)
        return V.for_use(session, owner, admin_item, by="agent account setup")
    # `B1223`: `db` None — the vault is read, and the new item kept, in
    # sessions of their own off the event loop, none held across the service's
    # answers.
    admin = await with_db(db, check)
    if admin["kind"] != "login" or not admin["origins"]:
        raise AccountRefused("Set up an agent account from a login with the service's address.")
    url = admin["origins"][0]
    new_password = secrets.token_urlsafe(24)
    place = _Place(owner, station_workspace)
    refused = await place.open()
    if refused is not None:
        raise AccountRefused(refused.get("error") or "Your workstation did not answer.", 503)
    if not place.in_workstation:
        from src.tool_security import blocked_tools_for_owner
        if "bash" in blocked_tools_for_owner(owner):
            raise AccountRefused("Setting up an account runs from your workstation, and this account has "
                                 "none turned on. Ask an admin for one.", 409)
    env = {"A_USER": admin["username"], "A_PASS": admin["secret"], "N_USER": username,
           "N_PASS": new_password, "URL": url}
    values = [admin["username"], admin["secret"], new_password]
    for n, command in enumerate(steps, 1):
        r = await place.run("set -o pipefail; " + command, place.base(), env, TIMEOUT_S)
        if r.get("timed_out") or r.get("exit_code") != 0:
            said = V.scrub(((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip(), values)
            first = "made the user" if n > 1 else "made nothing"
            raise AccountRefused(f"{TEMPLATES[template]['label']} refused step {n} of {len(steps)} "
                                 f"({first}): {said[-400:] or 'no answer'}", 502)
    item = await with_db(db, lambda session: V.create(
        session, owner, {"kind": "login", "label": label, "addresses": admin["origins"],
                         "username": username, "secret": new_password, "agent_account": True,
                         "use": "chat",
                         "notes": f"Made by Pantheon on {url} as {TEMPLATES[template]['label']} "
                                  f"role {role}, from “{admin['label']}”."}))
    from src.events import record_event
    record_event("vault_agent_account", name=label, owner=owner,
                 detail={"service": template, "role": role, "url": url, "from": admin["id"]})
    return item


def describe_plan(template: str, role: str) -> str:
    """For the confirmation the person reads: what will be called."""
    t = TEMPLATES[template]
    return (f"Pantheon will sign in to {t['label']} as your admin login, create the user, "
            f"give it the role {role}, and keep its password in your vault — you never type it.")


__all__ = ["TEMPLATES", "AccountRefused", "templates_public", "plan", "set_up", "describe_plan"]
