# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-09` / `P22-17` — may outside data fill this slot? The one place that
answers (`Law 7`). Pure.

`D-2026-10-01-05` §4: a step the author configured runs without a card when
outside data fills only its `value` slots; destination, command, recipient, URL
and host slots can never be mapped. **The adversary (`Law 17`)** is whoever
writes an inbound mail or webhook body, and through a model's output whoever
steered it: their bytes may reach a `value` slot; they must never choose the
tool, the destination, a recipient, a URL, a host or a command.

So every setting of every kind of step declares `value` or `never`, here:

  * `NODE_SLOTS[kind][field]` — the static fields (`SLICE-CD-DESIGN` § 2's
    table). A field nobody declared is `never` (`slot_for` fails closed).
  * an action's parameter declares its own mapping on the parameter
    (`builtin_actions._prompt_param(..., mapping=MAPPING_NEVER)`), read by
    `action_param_slots`; an action prompt with no declared parameter (the
    email actions' account JSON) is `never`.
  * an MCP argument or an HTTP query/body key is classified by
    `classify_argument` against an **allowlist** of words that only ever name
    text a person reads — anything else is `never`. Names are written by the
    author (HTTP) or the server's schema (MCP), never by outside data, so
    classifying on a name is classifying on trusted input.

The save routes, the walker at run, the dry run and the palette all ask this
module; the browser is handed its answers and derives nothing.

`render_call` builds a deterministic step's call as a dict and `json.dumps` it,
so a filled value is a dict value and can never become JSON structure; a
`never` slot is copied verbatim, and a reference found in one raises
`SlotError` — defence in depth for a document written straight to the
database, after the save already refused it.
"""

from __future__ import annotations

import json
import re
from typing import NamedTuple
from urllib.parse import quote

from src.workflow_refs import (
    MISSING,
    Ref,
    RefError,
    as_text,
    parse_template,
    references_in_text,
    render_text,
    render_value,
    resolve,
)

# ── Stored words (`FORBIDDEN.md` Part 1 at the merge) ────────────────────────
MAPPING_VALUE = "value"
MAPPING_NEVER = "never"
MAPPINGS = (MAPPING_VALUE, MAPPING_NEVER)

# How a `value` reaches what uses it. INLINE: it becomes part of a
# deterministic call (an HTTP body, an MCP argument, a Set field, a condition,
# Code's stdin). CONTEXT: it reaches a model only inside the untrusted-context
# block, never spliced into the prompt (`render_named_slots`).
CARRY_INLINE = "inline"
CARRY_CONTEXT = "context"
CARRIES = (CARRY_INLINE, CARRY_CONTEXT)

# The sentence a `never` field shows, one per category (§ 1.2), plus the
# classifier's: it cannot say WHICH of the three a name it does not know is,
# only that it is not on the list of words for text a person reads (`Law 10`).
WHY_WHERE = ("This says where the step's work goes, so it only takes what you type "
             "here, never a value from another step.")
WHY_WHAT = ("This decides what the step does, so it only takes what you type here, "
            "never a value from another step.")
WHY_WHEN = ("This decides when the step runs, so it only takes what you type here, "
            "never a value from another step.")
# `P23-05` (Doc 2 § 5): the reason in one line, under the setting it is on.
WHY_NOT_TEXT = "Typed only: this could be an address or a command."
# `B1882`: a Code step's source is typed only like the rest, but code holds
# `{{` of its own (a Python f-string's `f"{{item}}"` reads as a reference and
# was refused, with no way to write it). There, and only there, `\{{` is the
# text `{{`: the reference after it is passed over when the step is saved
# (`references_in_text(escapes=True)`) and the backslash is taken out before
# the code runs (`workflow_refs.unescape_references`). The sentence says so,
# since a person meets the rule only when their code is refused.
WHY_CODE = ("This is the code the step runs, so it only takes what you type here, never "
            "a value from another step. Where the code's own {{ reads as a field, as in "
            "f\"{{item}}\", write \\{{ there; the \\ is taken out before it runs.")
WHYS = (WHY_WHERE, WHY_WHAT, WHY_WHEN, WHY_NOT_TEXT, WHY_CODE)


class Slot(NamedTuple):
    """What a setting may be filled with. `mapping` is a `MAPPINGS` word,
    `carry` a `CARRIES` word for a `value` slot and `None` for `never`, `why`
    the sentence a `never` field shows (empty for `value`). `opened`
    (`B1884`): a `never` setting its author opened to a value from an earlier
    step (`FILLED_KEY`) — `value` while it is, and every value that fills it
    arms the gate (`RenderedCall.opened`)."""
    mapping: str
    carry: str | None
    why: str
    opened: bool = False


VALUE_CONTEXT = Slot(MAPPING_VALUE, CARRY_CONTEXT, "")
VALUE_INLINE = Slot(MAPPING_VALUE, CARRY_INLINE, "")
NEVER_WHERE = Slot(MAPPING_NEVER, None, WHY_WHERE)
NEVER_WHAT = Slot(MAPPING_NEVER, None, WHY_WHAT)
NEVER_WHEN = Slot(MAPPING_NEVER, None, WHY_WHEN)
NEVER_NOT_TEXT = Slot(MAPPING_NEVER, None, WHY_NOT_TEXT)
# `B1884`: a `never` setting its author opened.
OPENED_INLINE = Slot(MAPPING_VALUE, CARRY_INLINE, "", True)
# `B1882`: the one `never` slot that takes `\{{` as the text `{{` (above).
NEVER_CODE = Slot(MAPPING_NEVER, None, WHY_CODE)
# A setting no table names. Fail closed.
UNDECLARED = NEVER_WHAT


class _Rule(NamedTuple):
    """A field whose slot is decided per entry rather than by the table."""
    name: str


# `query[i].value` / `body[i].value`: classified by `query[i].name`.
BY_ENTRY_NAME = _Rule("by_entry_name")
# `args.<name>`: classified by the name against the MCP tool's input schema.
BY_SCHEMA = _Rule("by_schema")
# An action's `prompt`: the declaration on the action's parameter.
BY_PARAM = _Rule("by_param")
# A For-each's `step.config`: the inner step's own kind's slots.
INNER = _Rule("inner")
# `B1885`. A text inside an HTTP step's `raw_body` (the JSON the author writes
# whole): classified by the name of the key it is under, as an entry is by its
# name. A text under no name — an item of a top-level list — is `never`.
BY_LEAF_NAME = _Rule("by_leaf_name")

# `B1885` (`http-body-strings-no-headers`). Stored words (`FORBIDDEN.md` Part 1
# lists them with the other setting words). An HTTP step's body was only ever
# its fields, each sent as text, so `brightness: 128` went as "128" and
# `enabled: true` as "true" — which Home Assistant, ntfy's priority and JSON:API
# refuse. Now:
#
#   * a body field may say its `type` — text (the default, and what a field
#     with no `type` is, as before), a number, yes/no, or JSON — and is sent as
#     that type. A field filled from another step is coerced to it and refused
#     when it is not one; a typed one is checked at save.
#   * `body_mode` `raw` sends `raw_body`, the JSON the author writes whole.
#     Every name in it is the author's; a text under a name that only ever
#     holds words may be a reference, exactly as a field of that name may.
#
# A JSON field is never filled from another step, whatever its name: an object
# or a list from outside data would be structure the author did not write —
# the rule `classify_argument` already holds for an MCP argument.
BODY_MODE_RAW = "raw"
ENTRY_TYPE_TEXT = "text"
ENTRY_TYPE_NUMBER = "number"
ENTRY_TYPE_YES_NO = "yes/no"
ENTRY_TYPE_JSON = "json"
ENTRY_TYPES = (ENTRY_TYPE_TEXT, ENTRY_TYPE_NUMBER, ENTRY_TYPE_YES_NO, ENTRY_TYPE_JSON)

# ── `B1884` (`identifiers-cannot-be-mapped`): a setting its author opens ─────
#
# Every `never` setting stayed the author's to type, so "close the ticket the
# webhook names", "fetch /items/<the id the mail carried>" and "wait until the
# time the form said" could not be built at all: `ticket_id`, `issue_number`,
# an HTTP path and a Wait's time are not words a person reads, so the
# allowlist said `never`, and nothing but the allowlist could say otherwise.
#
# Now the author may OPEN one, on the step, with a box that says what it means
# (`FILLED_KEY`: the fields opened, named as a panel names them). Only:
#
#   * an MCP argument that is one text, number or whole number — never an
#     object, a list, a choice (an `enum` or a yes/no: the form draws those as
#     a choice), an address `format` or any `format` but a date, a time or an
#     id (`OPEN_FORMATS`);
#   * an HTTP step's query or body value (not one sent as JSON);
#   * an HTTP step's path, whose first part stays typed (`/items/…`), each
#     value written into it URL-encoded on its own (`quote(…, safe="")`), so
#     a value is never a `/`, a `?`, a `#`, a `..` or a new host;
#   * a Wait's time, when it waits until a time — a time of day or a date
#     and time, at most `workflow_wait_max_hours` away, as a typed one is.
#
# and, of the first two, only one whose NAME says nothing about who the work
# reaches, where it is written (a repository, a calendar, a document, a
# project — a place someone else could share with the owner, so naming it
# would be naming a recipient), a host, a command, a file, a key, an access
# level or what the step does (`CLOSED_WORDS`, every part as `name_parts`
# splits it; a credential `key` by `_KEY_QUALIFIERS`). So `ticket_id`,
# `issue_number`, `order_id`, `query`, `page`, `status` and `due_date` open;
# `to`, `chat_id`, `channel`, `recipients`, `url`, `host`, `webhook`, `repo`,
# `calendar_id`, `owner`, `command`, `sql`, `path`, `api_key`, `role` and
# `force` never do, whatever the author ticks — the document rule refuses the
# tick at save, with why, on that field.
#
# **The adversary (`Law 17`)** is still whoever writes the inbound mail or
# webhook body, and through a model's output whoever steered it. What they
# may now choose is which ticket, which item, which day — never who receives
# the work, where it is sent, a host, a command or a key. And because an
# opened setting decides WHICH thing the step acts on, every call whose opened
# setting a reference filled is built tainted (`RenderedCall.opened`, read by
# `tool_capabilities.authored_call_context`): the person's approval rung
# applies exactly as it does after a model has read a web page — at the
# default rung a step that writes, deletes or calls an Integration parks on a
# card with the exact call, and Allow replays that call once. Pantheon cannot
# prove a value did not come from outside (a Set step may pass a webhook's
# words on), so EVERY filled opened setting is read as outside text: fail
# closed. A Wait makes no call; its time from data only moves when the run
# goes on, within the same cap.
#
# A draft the model writes never opens a setting (`workflow_assist`), and a
# fix may not change `filled` (`FIX_FIELDS` does not name it).
FILLED_KEY = "filled"
FILLED_MAX = 100
# Every part of a name is checked against these, after `name_parts` splits it.
CLOSED_WORDS = frozenset({
    # who the work reaches
    "to", "cc", "bcc", "from", "recipient", "recipients", "email", "emails", "mail", "mailbox",
    "address", "addresses", "addr", "phone", "mobile", "sms", "fax", "channel", "channels", "chat",
    "chats", "room", "rooms", "user", "users", "username", "usernames", "login", "member",
    "members", "account", "accounts", "contact", "contacts", "sender", "target", "targets",
    "dest", "destination", "destinations", "webhook", "webhooks", "group", "groups", "owner",
    "owners", "assignee", "assignees", "reviewer", "reviewers", "invite", "invitee", "invitees",
    "attendee", "attendees", "participant", "participants", "subscriber", "subscribers",
    "follower", "followers", "collaborator", "collaborators", "mention", "mentions", "notify",
    "share", "forward", "audience", "team", "teams", "org", "orgs", "organization",
    "organisation", "tenant",
    # where it is written: a place someone else could share with the owner
    "repo", "repos", "repository", "repositories", "bucket", "buckets", "calendar", "calendars",
    "drive", "drives", "doc", "docs", "document", "documents", "sheet", "sheets", "spreadsheet",
    "spreadsheets", "notebook", "notebooks", "board", "boards", "project", "projects",
    "workspace", "workspaces", "space", "spaces", "inbox", "queue", "queues", "topic", "topics",
    "list", "lists", "playlist", "album", "feed", "feeds", "container", "parent", "database",
    "databases", "db", "table", "tables", "collection", "collections", "namespace",
    "conversation", "conversations", "cluster", "region", "zone", "env", "environment",
    # where it goes on the network
    "url", "urls", "uri", "uris", "href", "link", "links", "endpoint", "endpoints", "host",
    "hosts", "hostname", "server", "servers", "domain", "domains", "port", "ip", "base",
    "proxy", "callback", "redirect", "origin", "remote", "upstream", "dns", "site", "registry",
    # a command or code
    "command", "commands", "cmd", "script", "scripts", "code", "sql", "shell", "exec", "eval",
    "program", "expression", "expr", "template", "regex", "pattern", "jq",
    # a file
    "path", "paths", "file", "files", "filename", "filepath", "dir", "directory", "folder",
    "folders", "cwd", "workdir", "mount", "volume",
    # a credential
    "token", "tokens", "secret", "secrets", "password", "passwd", "passphrase", "auth",
    "authorization", "cookie", "cookies", "credential", "credentials", "apikey", "session",
    "signature", "otp", "pin", "cert", "certificate",
    # an access level
    "role", "roles", "permission", "permissions", "scope", "scopes", "access", "visibility",
    "public", "private", "admin", "acl", "grant", "privilege", "privileges",
    # what the step does
    "tool", "tools", "action", "actions", "function", "method", "operation", "op", "verb",
    "mode", "force", "confirm", "confirmed", "overwrite", "recursive", "cascade", "purge",
    "permanent", "unsafe", "sudo", "dry", "header", "headers",
})
# `key` names a credential (`api_key`, `private_key`, a lone `key`) or the
# thing a step acts on (`issue_key`, `project_key`): closed alone or beside
# one of these.
_KEY_WORDS = frozenset({"key", "keys"})
_KEY_QUALIFIERS = frozenset({
    "api", "access", "private", "public", "secret", "ssh", "signing", "encryption", "license",
    "licence", "client", "app", "master", "auth", "gpg", "pgp", "session", "service",
    "bearer", "deploy", "webhook", "account", "user", "host", "server", "crypto",
})
# The string formats an opened argument may have: none of them an address.
OPEN_FORMATS = frozenset({"date", "date-time", "time", "uuid", "duration"})
# Why a field cannot be opened — the sentence the save refuses with, after the
# step and the field (`workflow_document._filled_problem`).
OPEN_NOT_HERE = ("Only an MCP argument, an HTTP step's path, query or body value, and a "
                 "Wait's time can be filled from an earlier step.")
OPEN_CLOSED_NAME = ("Its name says who or where the step's work goes, a command, a file, a "
                    "key, an access level or what the step does, so it only takes what you "
                    "type, even when you choose otherwise.")
OPEN_NOT_ONE_VALUE = ("It takes JSON, a list or an object, so an earlier step could hand it "
                      "names you did not write; it only takes what you type.")
OPEN_CHOICE = "It is a choice you pick here, so it only takes what you choose."
OPEN_FORMAT = ("Its tool says it is an address, or text of a kind Pantheon cannot check, so "
               "it only takes what you type.")
OPEN_UNKNOWN = "Pantheon does not know what this tool takes here, so it only takes what you type."
OPEN_NO_ENTRY = "This step has no such field."
OPEN_WAIT_FOR = "Only a Wait until a time takes its time from an earlier step."
OPEN_PATH_HEAD = ("A path filled from an earlier step starts with a part you type, such as "
                  "/items/{{ steps.read.data.id }}.")
# The longest value an opened path takes from one reference.
PATH_VALUE_MAX = 1_000

# ── The table (`SLICE-CD-DESIGN` § 2) ───────────────────────────────────────
#
# Keys are field patterns: `.` between keys, `[]` for any position in a list,
# `*` for any key of a map. A path is answered by the LONGEST declared pattern
# that is a prefix of it, so `answer_fields` covers every key inside it.
_LLM = {
    "prompt": VALUE_CONTEXT,
    "model": NEVER_WHAT,
    "endpoint_url": NEVER_WHERE,
    "character_id": NEVER_WHAT,
    "crew_member_id": NEVER_WHAT,
    "max_steps": NEVER_WHAT,
    "output_target": NEVER_WHERE,
    "tools": NEVER_WHAT,
    "answer_fields": NEVER_WHAT,
}
_CONDITION = {
    "left": VALUE_INLINE,
    "right": VALUE_INLINE,
    "op": NEVER_WHAT,
}
NODE_SLOTS = {
    "llm": _LLM,
    "research": {
        "prompt": VALUE_INLINE,
        "model": NEVER_WHAT,
        "endpoint_url": NEVER_WHERE,
        "output_target": NEVER_WHERE,
    },
    "action": {
        "action": NEVER_WHAT,
        "prompt": BY_PARAM,
        "output_target": NEVER_WHERE,
    },
    "run_task": {
        "task_id": NEVER_WHAT,
    },
    "if": {
        "conditions": NEVER_WHAT,
        **{f"conditions[].{k}": v for k, v in _CONDITION.items()},
        "join": NEVER_WHAT,
    },
    "switch": {
        "cases": NEVER_WHAT,
        "cases[].id": NEVER_WHAT,
        "cases[].label": NEVER_WHAT,
        "cases[].join": NEVER_WHAT,
        "cases[].conditions": NEVER_WHAT,
        **{f"cases[].conditions[].{k}": v for k, v in _CONDITION.items()},
    },
    "set": {
        "fields": NEVER_WHAT,
        "fields[].name": NEVER_WHAT,
        "fields[].value": VALUE_INLINE,
        "on_missing": NEVER_WHAT,        # `B1881`: stop, or leave it empty
    },
    "merge": {
        "mode": NEVER_WHAT,
    },
    "wait": {
        "mode": NEVER_WHEN,
        "minutes": NEVER_WHEN,
        "time": NEVER_WHEN,
        "tz": NEVER_WHEN,
        # `B1884`: the settings its author opened (here, its time).
        "filled": NEVER_WHAT,
    },
    "foreach": {
        "list": VALUE_INLINE,
        "on_error": NEVER_WHAT,
        "step": NEVER_WHAT,
        "step.config": INNER,
    },
    "http": {
        "integration": NEVER_WHERE,
        "method": NEVER_WHERE,
        "path": NEVER_WHERE,
        "headers": NEVER_WHERE,
        # `B1885`: said per row, so the Headers list's boxes say why they are
        # typed only (the whole list was already `never`).
        "headers[].name": NEVER_WHERE,
        "headers[].value": NEVER_WHERE,
        "query": NEVER_WHERE,
        "query[].name": NEVER_WHERE,
        "query[].value": BY_ENTRY_NAME,
        "body": NEVER_WHERE,
        "body[].name": NEVER_WHERE,
        "body[].value": BY_ENTRY_NAME,
        "body[].type": NEVER_WHAT,
        "body_mode": NEVER_WHAT,
        "raw_body": BY_LEAF_NAME,
        "response": NEVER_WHAT,
        # `B1884`: the settings its author opened to a value from an earlier
        # step — its path, a query or body value.
        "filled": NEVER_WHAT,
    },
    "mcp": {
        "tool": NEVER_WHAT,
        "args": NEVER_NOT_TEXT,
        "args.*": BY_SCHEMA,
        # `B1884`: the arguments its author opened.
        "filled": NEVER_WHAT,
    },
    "skill": {
        "skill": NEVER_WHAT,
        "prompt": VALUE_CONTEXT,
        "model": NEVER_WHAT,
        "endpoint_url": NEVER_WHERE,
        "max_steps": NEVER_WHAT,
        "output_target": NEVER_WHERE,
    },
    "code": {
        "language": NEVER_WHAT,
        "source": NEVER_CODE,            # `B1882`: `\{{` is the text `{{`
        "timeout_seconds": NEVER_WHEN,
        "input": NEVER_WHAT,
        "input[].name": NEVER_WHAT,
        "input[].value": VALUE_INLINE,
    },
}


def _pattern(text: str) -> tuple:
    """`"cases[].conditions[].left"` → `("cases", "[]", "conditions", "[]", "left")`."""
    out = []
    for key in text.split("."):
        lists = 0
        while key.endswith("[]"):
            key = key[:-2]
            lists += 1
        if key:
            out.append(key)
        out.extend(["[]"] * lists)
    return tuple(out)


_PATTERNS = {kind: sorted(((_pattern(p), rule) for p, rule in table.items()),
                          key=lambda pr: -len(pr[0]))
             for kind, table in NODE_SLOTS.items()}


def declared_fields(kind: str) -> frozenset:
    """The top-level settings `NODE_SLOTS` declares for `kind`."""
    return frozenset(p[0] for p, _ in _PATTERNS.get(kind, ()))


def _matches(pattern: tuple, path: tuple) -> bool:
    if len(pattern) > len(path):
        return False
    for want, got in zip(pattern, path):
        if want == "[]":
            if type(got) is not int:
                return False
        elif want == "*":
            if type(got) is not str:
                return False
        elif want != got:
            return False
    return True


# ── Action parameters ────────────────────────────────────────────────────────

def action_param_slots(action: str | None) -> dict:
    """`{param name: Slot}` for a built-in action, read off the parameter's own
    `mapping` (`builtin_actions._prompt_param`). A parameter that declares no
    mapping, or declares a word that is not one, is `never` (fail closed)."""
    from src.builtin_actions import BUILTIN_ACTION_META

    out = {}
    for param in (BUILTIN_ACTION_META.get(action or "") or {}).get("params") or ():
        mapping = param.get("mapping")
        out[param.get("name")] = (VALUE_INLINE if mapping == MAPPING_VALUE else NEVER_WHAT)
    return out


def _action_prompt_slot(action: str | None) -> Slot:
    from src.builtin_actions import BUILTIN_ACTION_META

    params = [p for p in (BUILTIN_ACTION_META.get(action or "") or {}).get("params") or ()
              if p.get("source") == "prompt"]
    if len(params) != 1:
        # No declared parameter (the email actions read account JSON out of
        # `prompt`), or more than one sharing it: never.
        return NEVER_WHAT
    return action_param_slots(action).get(params[0].get("name"), NEVER_WHAT)


# ── The classifier ───────────────────────────────────────────────────────────
#
# An ALLOWLIST. A name is split on snake, kebab and camel boundaries and EVERY
# part must be one of these words; a name with any other character, an empty
# part, a digit or a word not here is `never`. So `to`, `chat_id`, `channel`,
# `url`, `host`, `path`, `command`, `query`, `action`, `id` — and every name
# nobody thought of — are `never` without being listed (§ 5.2 holds that by
# fuzzing). Only the words below can carry outside data.
CONTENT_WORDS = frozenset({
    "text", "message", "msg", "body", "content", "subject", "title", "summary",
    "description", "details", "note", "notes", "comment", "caption", "reply",
    "answer", "markdown", "html",
})
FORMAT_WORDS = frozenset({"text", "html", "markdown", "md", "plain"})
ARGUMENT_WORDS = CONTENT_WORDS | FORMAT_WORDS
ARGUMENT_TYPES = ("string", "number", "integer", "boolean")
# A string `format` that names an address — a destination, however the name
# reads. Any OTHER format is `never` too (fail closed); these are the ones that
# get the "where it goes" sentence.
ADDRESS_FORMATS = frozenset({
    "uri", "uri-reference", "iri", "iri-reference", "email", "idn-email",
    "hostname", "idn-hostname", "ipv4", "ipv6", "uri-template",
})
_NAME_CHARS = re.compile(r"[A-Za-z0-9_-]{1,64}")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
# The schema a key with no schema is read as: an HTTP query or body value is
# text in the request.
TEXT_SCHEMA = {"type": "string"}
# `B1885`. The schema an HTTP body field of each `type` is classified and
# coerced by. JSON's is an object or a list, so `classify_argument` says
# `never` for it by its type, whatever the name.
ENTRY_TYPE_SCHEMAS = {
    ENTRY_TYPE_TEXT: TEXT_SCHEMA,
    ENTRY_TYPE_NUMBER: {"type": "number"},
    ENTRY_TYPE_YES_NO: {"type": "boolean"},
    ENTRY_TYPE_JSON: {"type": ["object", "array"]},
}


def name_parts(name) -> tuple:
    """`name` split on `_`, `-` and camel-case boundaries, lower-cased — or
    `()` for anything that is not plain ASCII letters, digits, `_` and `-`."""
    if not isinstance(name, str) or not _NAME_CHARS.fullmatch(name):
        return ()
    parts = []
    for chunk in re.split(r"[_-]+", name):
        if not chunk:
            continue
        pieces = _CAMEL.findall(chunk)
        if "".join(pieces) != chunk:
            return ()
        parts.extend(p.lower() for p in pieces)
    return tuple(parts)


def _schema_types(schema) -> tuple:
    kind = schema.get("type")
    if isinstance(kind, str):
        return (kind,)
    if isinstance(kind, list) and all(isinstance(k, str) for k in kind):
        return tuple(kind)
    return ()


# `B1886` (`anyof-optional-args-never`). The two keys a JSON schema writes an
# "either this or nothing" with. pydantic v2 and FastMCP — which most Python
# MCP servers are built on — describe `message: str | None = None` as
#
#     {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null}
#
# with no `type` of its own, so `_schema_types` read no type and
# `classify_argument` said `never`: every optional text argument on those
# servers could not take a value from an earlier step, even one named `text`
# or `message`, and the form called a whole number "text".
_EITHER_KEYS = ("anyOf", "oneOf")


def effective_schema(schema):
    """`schema` as the classifier and the coercion read it (`B1886`): an
    `anyOf`/`oneOf` of ONE schema and `{"type": "null"}` is that one schema
    with `null` added to its type — its `format`, `enum` and the rest kept, so
    `{"anyOf": [{"type": "string", "format": "uri"}, {"type": "null"}]}` is
    still an address and still `never`. The outer schema's own words (its
    `description`, `default`, `title`) stay on top.

    Anything else is handed back as it is, so it reads exactly as before:
    a choice of two real types, a member that is a `$ref` (no `type`, so
    `never`), a schema that also names a `type` beside its `anyOf`. Fail
    closed is the point — this only ever turns the one shape a person means
    by "optional" into the shape it stands for."""
    if not isinstance(schema, dict) or "type" in schema:
        return schema
    keys = [k for k in _EITHER_KEYS if isinstance(schema.get(k), list)]
    if len(keys) != 1:
        return schema
    members = schema[keys[0]]
    real = [m for m in members if not (isinstance(m, dict) and m.get("type") == "null"
                                       and len(m) == 1)]
    if len(real) != 1 or len(members) != 2 or not isinstance(real[0], dict):
        return schema
    member = real[0]
    member_types = _schema_types(member)
    if not member_types or any(k in member for k in _EITHER_KEYS):
        return schema
    out = {k: v for k, v in schema.items() if k != keys[0]}
    for key, value in member.items():
        if key != "type":
            out.setdefault(key, value)
    out["type"] = [*member_types, *(() if "null" in member_types else ("null",))]
    return out


def classify_argument(name, schema) -> Slot:
    """May outside data fill the argument `name`, whose JSON schema is
    `schema`? Fails closed: `value` only when every part of the name is in
    `ARGUMENT_WORDS`, the type is text, a number or a yes/no, and the schema
    names no `format`. Everything else is `never` — any object, any list, any
    address format, any schema that is missing or not an object.

    `B1886`: an optional argument (`anyOf` of one type and `null`) is read as
    that type (`effective_schema`), so `message: str | None` is answered as
    `message: str` is — and an optional address is still an address."""
    parts = name_parts(name)
    if not parts or any(p not in ARGUMENT_WORDS for p in parts):
        return NEVER_NOT_TEXT
    if not isinstance(schema, dict):
        return NEVER_NOT_TEXT
    schema = effective_schema(schema)
    types = [t for t in _schema_types(schema) if t != "null"]
    if not types or any(t not in ARGUMENT_TYPES for t in types):
        return NEVER_NOT_TEXT
    fmt = schema.get("format")
    if fmt is not None:
        return NEVER_WHERE if fmt in ADDRESS_FORMATS else NEVER_NOT_TEXT
    return VALUE_INLINE


# ── Which slot a setting is ──────────────────────────────────────────────────

def _entry_name(config: dict, path: tuple):
    try:
        return config[path[0]][path[1]]["name"]
    except (KeyError, IndexError, TypeError):
        return None


def entry_schema(kind, config: dict, path: tuple):
    """`B1885`. The schema the entry at `path` is classified and coerced by: an
    HTTP body field's by its `type` (none is text, as before; a word that is
    not one is `None`, so `never`), every other entry's is text."""
    if kind != "http" or not path or path[0] != "body":
        return TEXT_SCHEMA
    try:
        word = config[path[0]][path[1]].get("type")
    except (KeyError, IndexError, TypeError, AttributeError):
        return TEXT_SCHEMA
    if word is None:
        return TEXT_SCHEMA
    return ENTRY_TYPE_SCHEMAS.get(word) if isinstance(word, str) else None


def leaf_name(path: tuple):
    """`B1885`. The name a text inside `raw_body` sits under: the nearest key
    above it (`("raw_body", "message", "text")` → `text`, `("raw_body",
    "notes", 0)` → `notes`), or `None` for one under no name."""
    for seg in reversed(tuple(path)[1:]):
        if isinstance(seg, str):
            return seg
    return None


def _closed_name(parts: tuple) -> bool:
    """`B1884`. Whether a name, split by `name_parts`, says who or where the
    work goes, a command, a file, a key, an access level or what the step
    does (`CLOSED_WORDS`). A `key` is closed alone or beside a word that
    makes it a credential (`api_key`), and open beside one that makes it the
    thing acted on (`issue_key`)."""
    if not parts or any(p in CLOSED_WORDS for p in parts):
        return True
    if any(p in _KEY_WORDS for p in parts):
        others = [p for p in parts if p not in _KEY_WORDS]
        return not others or any(p in _KEY_QUALIFIERS for p in others)
    return False


def argument_opening_problem(name, schema, *, choice_ok: bool = False) -> str | None:
    """`B1884`. Why the argument or entry `name`, of JSON schema `schema`,
    cannot be opened to a value from an earlier step — or `None` when it can.
    `choice_ok`: an HTTP field drawn as a text box may be a yes/no; an MCP
    argument with a choice (`enum`, a yes/no) is drawn as one, and is not.
    Fails closed, as `classify_argument` does: a name off `name_parts`, a
    schema that is not one, a type that is not one value, a `format` not in
    `OPEN_FORMATS`."""
    if _closed_name(name_parts(name)):
        return OPEN_CLOSED_NAME
    if not isinstance(schema, dict):
        return OPEN_UNKNOWN
    schema = effective_schema(schema)
    types = [t for t in _schema_types(schema) if t != "null"]
    if not types or any(t not in ARGUMENT_TYPES for t in types):
        return OPEN_NOT_ONE_VALUE
    if not choice_ok and ("boolean" in types or isinstance(schema.get("enum"), list)):
        return OPEN_CHOICE
    fmt = schema.get("format")
    if fmt is not None and fmt not in OPEN_FORMATS:
        return OPEN_FORMAT
    return None


def argument_opens(name, schema) -> bool:
    """`B1884`. Whether the MCP argument `name` is one its author may open: it
    is `never` by `classify_argument` and nothing in `argument_opening_problem`
    stops it. What the palette says on each argument (`openable`)."""
    return (classify_argument(name, schema).mapping == MAPPING_NEVER
            and argument_opening_problem(name, schema) is None)


def opening_problem(node: dict, path, *, mcp_schema=None) -> str | None:
    """`B1884`. Why the setting at `path` of `node` cannot be opened to a value
    from an earlier step, or `None` when it can (see `FILLED_KEY`)."""
    path = tuple(path)
    kind = node.get("kind") if isinstance(node, dict) else None
    config = (node.get("config") if isinstance(node, dict) else None) or {}
    if not isinstance(config, dict):
        return OPEN_NOT_HERE
    if kind == "mcp" and len(path) == 2 and path[0] == "args" and isinstance(path[1], str):
        props = mcp_schema.get("properties") if isinstance(mcp_schema, dict) else None
        prop = props.get(path[1]) if isinstance(props, dict) else None
        return argument_opening_problem(path[1], prop)
    if kind == "http":
        if path == ("path",):
            return None
        if (len(path) == 3 and path[0] in ("query", "body") and type(path[1]) is int
                and path[2] == "value"):
            entries = config.get(path[0])
            if not isinstance(entries, list) or not 0 <= path[1] < len(entries) \
                    or not isinstance(entries[path[1]], dict):
                return OPEN_NO_ENTRY
            return argument_opening_problem(_entry_name(config, path),
                                            entry_schema(kind, config, path), choice_ok=True)
    if kind == "wait" and path == ("time",):
        return None if config.get("mode") == "until" else OPEN_WAIT_FOR
    return OPEN_NOT_HERE


def filled_fields(node: dict) -> frozenset:
    """`B1884`. The settings `node`'s author opened (`FILLED_KEY`), as paths;
    an entry that is not a field as a panel names it is left out (the
    document rule refuses it at save)."""
    config = (node.get("config") if isinstance(node, dict) else None) or {}
    listed = config.get(FILLED_KEY) if isinstance(config, dict) else None
    if not isinstance(listed, list):
        return frozenset()
    return frozenset(p for p in (path_of(f) for f in listed if isinstance(f, str)) if p)


def opened_path_problem(text) -> str | None:
    """`B1884`. An opened HTTP path holding a reference starts with a part the
    author typed (`/items/…`), so a value never chooses the API it reaches —
    `OPEN_PATH_HEAD` — or `None`. A path with no reference is the author's."""
    if not isinstance(text, str):
        return None
    try:
        template = parse_template(text)
    except RefError:
        return None  # the rule says what is wrong with the reference itself
    if not template.refs:
        return None
    first = template.parts[0] if template.parts and isinstance(template.parts[0], str) else ""
    return None if _OPEN_PATH_HEAD.match(first) else OPEN_PATH_HEAD


_OPEN_PATH_HEAD = re.compile(r"/[^/?#{}\s]+/")


def slot_for(node: dict, path, *, mcp_schema=None) -> Slot:
    """The `Slot` for the setting at `path` (a tuple of keys and positions
    under `config`) in `node`. A path the table does not declare is `never`.
    `mcp_schema` is an MCP step's tool `input_schema`; without it every
    argument is `never`.

    `B1884`: a `never` setting the author opened (`FILLED_KEY`) that may be
    opened (`opening_problem`) is `OPENED_INLINE` — `value`, and marked."""
    slot = _declared_slot(node, path, mcp_schema=mcp_schema)
    if slot.mapping == MAPPING_NEVER and tuple(path) in filled_fields(node) \
            and opening_problem(node, path, mcp_schema=mcp_schema) is None:
        return OPENED_INLINE
    return slot


def _declared_slot(node: dict, path, *, mcp_schema=None) -> Slot:
    path = tuple(path)
    kind = node.get("kind") if isinstance(node, dict) else None
    config = (node.get("config") if isinstance(node, dict) else None) or {}
    if not path:
        return UNDECLARED
    for pattern, rule in _PATTERNS.get(kind, ()):
        if not _matches(pattern, path):
            continue
        if isinstance(rule, Slot):
            return rule
        if rule is BY_PARAM:
            return _action_prompt_slot(config.get("action") if isinstance(config, dict) else None)
        if rule is BY_ENTRY_NAME:
            return classify_argument(_entry_name(config, path),
                                     entry_schema(kind, config, path))
        if rule is BY_LEAF_NAME:
            return classify_argument(leaf_name(path), TEXT_SCHEMA)
        if rule is BY_SCHEMA:
            props = mcp_schema.get("properties") if isinstance(mcp_schema, dict) else None
            prop = props.get(path[1]) if isinstance(props, dict) else None
            return classify_argument(path[1], prop)
        if rule is INNER:
            inner = config.get("step") if isinstance(config, dict) else None
            if not isinstance(inner, dict) or inner.get("kind") == "foreach":
                return UNDECLARED
            return slot_for(inner, path[len(pattern):], mcp_schema=mcp_schema)
        return UNDECLARED
    return UNDECLARED


def path_text(path) -> str:
    """`("conditions", 0, "left")` → `conditions[0].left` — the `field` a
    refusal names, so the panel can put the sentence on that field."""
    out = ""
    for seg in path:
        if type(seg) is int:
            out += f"[{seg}]"
        else:
            out += f".{seg}" if out else str(seg)
    return out


_FIELD_SEG = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


def path_of(field) -> tuple | None:
    """`conditions[0].left` → `("conditions", 0, "left")`: `path_text` read
    back, for a field a panel names (`B1099`). `None` for text that is not
    one — anything between the segments but a dot."""
    text = str(field or "")
    out, at = [], 0
    for m in _FIELD_SEG.finditer(text):
        gap = text[at:m.start()]
        index = m.group(2) is not None
        # A name follows a dot (or starts the field); an index follows
        # anything but a dot — exactly what `path_text` writes.
        if gap != ("" if index or not out else "."):
            return None
        out.append(int(m.group(2)) if index else m.group(1))
        at = m.end()
    if at != len(text) or not out:
        return None
    return tuple(out)


def config_leaves(value, path=()):
    """`(path, text)` for every text inside a step's settings, in order."""
    if isinstance(value, str):
        yield tuple(path), value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from config_leaves(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from config_leaves(item, (*path, index))


# ── A deterministic step's call (`P22-17`, the Run half) ────────────────────

SLOT_MAX_CHARS = 20_000
CALL_MAX_BYTES = 64 * 1024
CALL_KINDS = ("http", "mcp", "code", "action")
API_CALL_TOOL = "api_call"


class SlotError(ValueError):
    """A call that may not be made as configured. `sentence` is what the step
    log says; `field` the setting it is about (`path_text`)."""

    def __init__(self, sentence: str, field: str = ""):
        super().__init__(sentence)
        self.sentence = sentence
        self.field = field


class RenderedCall(NamedTuple):
    """One deterministic step's call, built by `render_call` and nothing else
    (`tool_capabilities.authored_call_context` refuses any other type). `tool`
    is the tool name (`api_call`, `mcp__…`), the action key, or Code's
    language; `content` the exact text dispatched (for Code: the stdin JSON);
    `value_paths` the settings outside data filled; `missing` the references
    that reached nothing; `opened` (`B1884`) the settings its author opened
    that a reference filled — when there are any, `authored_call_context`
    builds the call tainted, so the person's approval rung applies."""
    kind: str
    tool: str | None
    content: str
    value_paths: tuple
    missing: tuple
    opened: tuple = ()


_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_YES = frozenset({"true", "yes"})
_NO = frozenset({"false", "no"})


def _coerce(value, schema, label: str):
    """`value` as the schema's type, or `SlotError`. Text is `as_text` (an
    object or list arrives as a JSON string, never as keys); a number or a
    yes/no must parse; an `enum` must hold it. `schema` `None` is Code's
    stdin, which is data handed to the author's own code, not a call's
    structure: the JSON value as it is."""
    if schema is None:
        return value
    # `B1886`: an optional argument is coerced as the type it is optional of,
    # and `null` handed to it stays `null`.
    schema = effective_schema(schema) if isinstance(schema, dict) else schema
    types = [t for t in _schema_types(schema) if t != "null"] or ["string"]
    if value is None and "null" in _schema_types(schema):
        return None
    if "string" in types:
        out = as_text(value)
    elif "number" in types or "integer" in types:
        if isinstance(value, bool):
            out = None
        elif isinstance(value, (int, float)):
            out = value
        elif isinstance(value, str) and _NUMBER_RE.fullmatch(value.strip()):
            text = value.strip()
            out = float(text) if any(c in text for c in ".eE") else int(text)
        else:
            out = None
        if out is not None and "number" not in types:
            out = int(out) if float(out).is_integer() else None
        if out is None:
            raise SlotError(f"“{label}” needs a number, and it was handed "
                            f"“{as_text(value)[:40]}”.", label)
    elif "boolean" in types:
        if isinstance(value, bool):
            out = value
        elif isinstance(value, str) and value.strip().lower() in _YES | _NO:
            out = value.strip().lower() in _YES
        else:
            raise SlotError(f"“{label}” needs yes or no, and it was handed "
                            f"“{as_text(value)[:40]}”.", label)
    else:
        raise SlotError(f"“{label}” cannot take a value from another step.", label)
    enum = schema.get("enum") if isinstance(schema, dict) else None
    if isinstance(enum, list) and out not in enum:
        raise SlotError(f"“{label}” must be one of {', '.join(as_text(e) for e in enum[:8])}.",
                        label)
    return out


class _Renderer:
    def __init__(self, node: dict, ctx):
        self.node = node
        self.ctx = ctx
        self.value_paths = []
        self.missing = []
        # `B1884`: the opened settings a reference filled.
        self.opened = []

    def never(self, path: tuple, value, *, escapes: bool = False):
        """A `never` slot: the author's value, verbatim — refused if anything
        in it reads as a reference. `escapes` (`B1882`, a Code step's source
        only): a reference right after `\\` is the code's own text."""
        for leaf_path, text in config_leaves(value, path):
            if references_in_text(text, escapes=escapes):
                raise SlotError(f"“{path_text(leaf_path)}” only takes what you typed, and it "
                                f"holds a reference, so nothing was sent.",
                                path_text(leaf_path))
        return json.loads(json.dumps(value)) if isinstance(value, (dict, list)) else value

    def fill(self, path: tuple, raw, schema, *, opened: bool = False):
        """A `value` slot: its references resolved in one pass, then coerced.
        `opened` (`B1884`): a `never` setting its author opened — one a
        reference fills is noted, so the call is built tainted."""
        label = path_text(path)
        if isinstance(raw, str):
            try:
                template = parse_template(raw)
            except RefError as exc:
                raise SlotError(f"“{label}”: {exc.sentence}", label) from None
            if template.refs:
                self.value_paths.append(label)
                if opened:
                    self.opened.append(label)
            value, missing = render_value(template, self.ctx)
            self.missing.extend(missing)
        elif isinstance(raw, (dict, list)):
            if opened:
                # An opened setting takes one value; structure is the
                # author's to type, and a typed one holds no reference.
                return self.never(path, raw)
            value = self._fill_nested(path, raw)
        else:
            value = raw
        out = _coerce(value, schema, label)
        if isinstance(out, str) and len(out) > SLOT_MAX_CHARS:
            raise SlotError(f"“{label}” would be {len(out):,} characters; a step takes at "
                            f"most {SLOT_MAX_CHARS:,} in one setting.", label)
        return out

    def _fill_nested(self, path, raw):
        if isinstance(raw, dict):
            return {k: self._fill_nested((*path, k), v) for k, v in raw.items()}
        if isinstance(raw, list):
            return [self._fill_nested((*path, i), v) for i, v in enumerate(raw)]
        if isinstance(raw, str):
            try:
                template = parse_template(raw)
            except RefError as exc:
                raise SlotError(f"“{path_text(path)}”: {exc.sentence}", path_text(path)) from None
            if template.refs:
                self.value_paths.append(path_text(path))
            text, missing = render_text(template, self.ctx)
            self.missing.extend(missing)
            return text
        return raw

    def entries(self, key: str, *, schema_for_name, typed: bool = False):
        """An HTTP `query`/`body`, or Code's `input`: `[{name, value}]` → a
        dict, each value's slot decided by its name. `typed` (`B1885`, an
        HTTP body): each value is sent as its entry's `type` — filled and
        coerced to it, or the author's own text read as it."""
        config = self.node.get("config") or {}
        out = {}
        for index, entry in enumerate(config.get(key) or ()):
            if not isinstance(entry, dict):
                raise SlotError(f"“{key}” has an entry that is not a name and a value.", key)
            name = self.never((key, index, "name"), entry.get("name"))
            if not isinstance(name, str) or not name:
                raise SlotError(f"“{key}” has an entry with no name.", key)
            slot = slot_for(self.node, (key, index, "value"))
            raw = entry.get("value")
            word = self.never((key, index, "type"), entry.get("type")) if typed else None
            schema = (entry_schema(self.node.get("kind"), config, (key, index))
                      if typed else schema_for_name(name))
            if slot.mapping == MAPPING_VALUE:
                out[name] = self.fill((key, index, "value"), raw, schema, opened=slot.opened)
            else:
                out[name] = typed_literal(self.never((key, index, "value"), raw), word,
                                          path_text((key, index, "value")))
        return out

    def raw(self, path: tuple, value):
        """`B1885`. The JSON an HTTP step's author wrote whole (`raw_body`):
        every name and every non-text value as written; each text is a slot
        decided by the name it sits under (`BY_LEAF_NAME`). A text that is one
        reference alone takes the value's own type when it is a text, a
        number, a yes/no or nothing — and an object or a list arrives as its
        JSON text, so outside data never adds a name or an item."""
        if isinstance(value, dict):
            return {k: self.raw((*path, k), v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.raw((*path, i), v) for i, v in enumerate(value)]
        if not isinstance(value, str):
            return value
        if slot_for(self.node, path).mapping != MAPPING_VALUE:
            return self.never(path, value)
        label = path_text(path)
        try:
            template = parse_template(value)
        except RefError as exc:
            raise SlotError(f"“{label}”: {exc.sentence}", label) from None
        if not template.refs:
            return value
        self.value_paths.append(label)
        out, missing = render_value(template, self.ctx)
        self.missing.extend(missing)
        if isinstance(out, (dict, list)):
            out = as_text(out)
        if isinstance(out, str) and len(out) > SLOT_MAX_CHARS:
            raise SlotError(f"“{label}” would be {len(out):,} characters; a step takes at "
                            f"most {SLOT_MAX_CHARS:,} in one setting.", label)
        return out

    def path(self, raw):
        """`B1884`. An HTTP path its author opened: what they typed, as typed,
        and each reference's value URL-encoded on its own (`quote`, nothing
        kept), so a value is one piece of the path — never a `/`, a `?`, a
        `#`, a `:` or a `%` the server reads as one. Refused, with nothing
        sent: a path whose first part is not typed, a value that is a list or
        an object, nothing, or only dots (`.`/`..` would climb out of the
        path the author wrote), one longer than `PATH_VALUE_MAX`."""
        label = "path"
        if not isinstance(raw, str):
            return self.never(("path",), raw)
        try:
            template = parse_template(raw)
        except RefError as exc:
            raise SlotError(f"“{label}”: {exc.sentence}", label) from None
        if not template.refs:
            return raw
        if opened_path_problem(raw):
            raise SlotError(f"“{label}”: {OPEN_PATH_HEAD}", label)
        out = []
        for part in template.parts:
            if not isinstance(part, Ref):
                out.append(part)
                continue
            value = resolve(part, self.ctx)
            if value is MISSING:
                self.missing.append(part.text)
                continue
            if isinstance(value, (dict, list)):
                raise SlotError(f"“{label}” takes one piece of text or a number from "
                                f"{part.text}, and it was handed a list or an object, so "
                                f"nothing was sent.", label)
            text = as_text(value)
            if not text.strip(" .\t\r\n"):
                raise SlotError(f"“{label}” was handed “{text[:20]}” from {part.text}, which "
                                f"would change which address is called, so nothing was sent.",
                                label)
            if len(text) > PATH_VALUE_MAX:
                raise SlotError(f"“{label}” would take {len(text):,} characters from "
                                f"{part.text}; it takes at most {PATH_VALUE_MAX:,}.", label)
            out.append(quote(text, safe=""))
        self.value_paths.append(label)
        self.opened.append(label)
        return "".join(out)


def typed_literal(value, word, label: str):
    """`B1885`. What the author typed in an HTTP body field, as its `type`:
    no type (or text) is the value as typed, exactly as before; a number and a
    yes/no are read as one (`_coerce`'s rule), JSON is parsed. Anything that
    does not read as its type raises `SlotError` — the save refuses it first."""
    if word is None or word == ENTRY_TYPE_TEXT:
        return value
    if word == ENTRY_TYPE_JSON:
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except ValueError:
            raise SlotError(f"“{label}” is set to JSON, and what is typed is not JSON.",
                            label) from None
    schema = ENTRY_TYPE_SCHEMAS.get(word) if isinstance(word, str) else None
    if schema is None:
        raise SlotError(f"“{label}” has a type this Pantheon does not send.", label)
    return _coerce(value, schema, label)


def render_call(node: dict, ctx, *, mcp_schema=None) -> RenderedCall:
    """The call a deterministic step (`CALL_KINDS`) makes, with its `value`
    slots filled from `ctx` (`workflow_refs.build_context`). Raises
    `SlotError` for anything that may not be sent — a reference in a `never`
    slot, a value of the wrong type, a slot or call over its cap.

    The call is a dict, dumped once: a value is a dict value and can never
    become JSON structure. `never` slots are the author's, verbatim."""
    kind = node.get("kind") if isinstance(node, dict) else None
    config = (node.get("config") if isinstance(node, dict) else None) or {}
    r = _Renderer(node, ctx)
    if kind == "http":
        call = {
            "integration": r.never(("integration",), config.get("integration")),
            "method": r.never(("method",), config.get("method") or "GET"),
            # `B1884`: a path its author opened takes values from earlier
            # steps, each URL-encoded on its own (`_Renderer.path`).
            "path": (r.path(config.get("path") or "/") if slot_for(node, ("path",)).opened
                     else r.never(("path",), config.get("path") or "/")),
        }
        headers = {}
        for index, entry in enumerate(config.get("headers") or ()):
            entry = r.never(("headers", index), entry)
            if isinstance(entry, dict) and entry.get("name"):
                headers[entry["name"]] = as_text(entry.get("value"))
        if headers:
            call["headers"] = headers
        params = r.entries("query", schema_for_name=lambda _n: TEXT_SCHEMA)
        if params:
            call["params"] = params
        mode = r.never(("body_mode",), config.get("body_mode"))
        # `B1885`: what the step hands on is the walker's business, not the
        # request's — read here only so a reference in it is refused.
        r.never(("response",), config.get("response"))
        if mode == BODY_MODE_RAW:
            written = config.get("raw_body")
            if not isinstance(written, (dict, list)):
                raise SlotError("The body is set to JSON you write, and none is written, "
                                "so nothing was sent.", "raw_body")
            call["body"] = r.raw(("raw_body",), written)
        else:
            body = r.entries("body", schema_for_name=lambda _n: TEXT_SCHEMA, typed=True)
            if body:
                call["body"] = body
        # `P22-13`: `do_api_call` hands the parsed body back as data.
        call["structured"] = True
        tool = API_CALL_TOOL
    elif kind == "mcp":
        tool = r.never(("tool",), config.get("tool"))
        if not isinstance(tool, str) or not tool:
            raise SlotError("The step names no tool.", "tool")
        props = mcp_schema.get("properties") if isinstance(mcp_schema, dict) else None
        props = props if isinstance(props, dict) else {}
        args = config.get("args") or {}
        if not isinstance(args, dict):
            raise SlotError("“args” is not a set of named arguments.", "args")
        call = {}
        for name, raw in args.items():
            slot = slot_for(node, ("args", name), mcp_schema=mcp_schema)
            if slot.mapping == MAPPING_VALUE:
                call[name] = r.fill(("args", name), raw, props.get(name), opened=slot.opened)
            else:
                call[name] = r.never(("args", name), raw)
    elif kind == "code":
        for key in ("language", "source", "timeout_seconds"):
            r.never((key,), config.get(key), escapes=(key == "source"))
        tool = config.get("language")
        call = r.entries("input", schema_for_name=lambda _n: None)
    elif kind == "action":
        tool = r.never(("action",), config.get("action"))
        r.never(("output_target",), config.get("output_target"))
        if slot_for(node, ("prompt",)).mapping == MAPPING_VALUE:
            prompt = r.fill(("prompt",), config.get("prompt"), TEXT_SCHEMA)
        else:
            prompt = r.never(("prompt",), config.get("prompt"))
        content = prompt if isinstance(prompt, str) else ""
        return RenderedCall("action", tool, content, tuple(dict.fromkeys(r.value_paths)),
                            tuple(dict.fromkeys(r.missing)))
    else:
        raise SlotError(f"A {kind!r} step does not make a call.", "")
    content = json.dumps(call, ensure_ascii=False)
    if len(content.encode("utf-8")) > CALL_MAX_BYTES:
        raise SlotError(f"The call would be larger than {CALL_MAX_BYTES // 1024} KiB.", "")
    return RenderedCall(kind, tool, content, tuple(dict.fromkeys(r.value_paths)),
                        tuple(dict.fromkeys(r.missing)), tuple(dict.fromkeys(r.opened)))


def opened_text(node: dict, key: str, ctx):
    """`B1884`. A top-level setting that is not part of a call — a Wait's
    `time` — as a run reads it: the author's own text when it is not opened
    (a reference in it refused, as in any `never` slot), else filled as text
    from `ctx` (`workflow_refs.build_context`). Raises `SlotError`, naming a
    reference that reached nothing."""
    config = (node.get("config") if isinstance(node, dict) else None) or {}
    r = _Renderer(node, ctx)
    raw = config.get(key) if isinstance(config, dict) else None
    if not slot_for(node, (key,)).opened:
        return r.never((key,), raw)
    out = r.fill((key,), raw, TEXT_SCHEMA, opened=True)
    if r.missing:
        raise SlotError(f"“{key}” reads {', '.join(dict.fromkeys(r.missing))}, which reached "
                        f"nothing.", key)
    return out


__all__ = [
    "MAPPING_VALUE", "MAPPING_NEVER", "MAPPINGS", "CARRY_INLINE", "CARRY_CONTEXT",
    "CARRIES", "WHY_WHERE", "WHY_WHAT", "WHY_WHEN", "WHY_NOT_TEXT", "WHY_CODE",
    "NEVER_CODE", "WHYS", "Slot",
    "NODE_SLOTS", "CONTENT_WORDS", "FORMAT_WORDS", "ARGUMENT_WORDS", "ADDRESS_FORMATS",
    "classify_argument", "effective_schema", "action_param_slots", "slot_for", "declared_fields", "path_of",
    "path_text", "config_leaves", "name_parts", "SlotError", "RenderedCall",
    "render_call", "SLOT_MAX_CHARS", "CALL_MAX_BYTES", "MISSING",
    "BODY_MODE_RAW", "ENTRY_TYPE_TEXT", "ENTRY_TYPE_NUMBER", "ENTRY_TYPE_YES_NO", "ENTRY_TYPE_JSON",
    "ENTRY_TYPES", "ENTRY_TYPE_SCHEMAS", "entry_schema", "leaf_name", "typed_literal",
    "FILLED_KEY", "FILLED_MAX", "CLOSED_WORDS", "OPEN_FORMATS", "OPENED_INLINE",
    "argument_opening_problem", "argument_opens", "opening_problem", "filled_fields",
    "opened_path_problem", "opened_text", "PATH_VALUE_MAX",
]
