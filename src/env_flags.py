# SPDX-License-Identifier: AGPL-3.0-or-later
# src/env_flags.py
"""What did this string mean by *yes*? One rule per boundary (`B91`, `B97`).

**Four boundaries, four rules, one file.** `B91` built the first of them and this
module was named for it; `B97` counted the rest. An environment variable is typed
by the operator, an HTTP field is sent by our own JavaScript, a tool argument is
written by a model that will cheerfully invent `"enabled"`, and skill frontmatter
is a file somebody edited. **They are not one vocabulary and must not become
one** (`Law 14`) — the trust boundaries differ and so does the strictness. What
they share is that each boundary gets *exactly one* rule, and until `B97` none of
them did: 16 sites answered the question three different ways with no shared rule
between them, and two private half-helpers existed that neither other boundary
could reach.

    boundary                  owner                       trust
    ────────────────────────  ──────────────────────────  ───────────────────────
    environment               `env_flag` / `env_truthy`   the operator typed it
    HTTP request field        `request_truthy`            our own front end sent it
    model tool argument       `tool_arg_truthy`           a model wrote it
    skill frontmatter         `skill_format._parse_scalar`  a person edited a file

The frontmatter owner stays where it is on purpose. It is a YAML-1.1 scalar
parser, not a flag helper — its `true`/`yes` reading is one branch of *parsing a
scalar*, and lifting that branch out here would be the second form of a thing
that already exists, which is the defect this row is about (`Law 14`). It is
named here so the boundary has a written owner, and `.pantheon/check-env-declared.py`
knows the name.

The module keeps the name `env_flags` rather than growing a sibling: 22 modules
import `env_flag` from it, the checker's SPELLING rule skips this path by name,
and a rename would be churn in front of every one of them for a docstring's sake.

── The environment rule (`B91`) ───────────────────────────────────────────────

Counted 2026-09-15 across every tracked `.py` outside `tests/` and `.pantheon/`,
by AST rather than by grep: **38 environment booleans, 10 incompatible rules**.
`PANTHEON_STARTUP_WARMUPS=1` was on and `IMAP_STARTTLS=1` was off, in the same
process. `LOCALHOST_BYPASS=yes` was off and `PANTHEON_ALLOW_PRIVATE_CALDAV=yes`
was on. `AUTH_ENABLED=0` left authentication **enabled**, because only the
literal string `false` disabled it. `CLEANUP_ENABLED=" true"` was off, because
that one site was the only one that never called `.strip()`. Nothing errored,
nothing logged, and `.env.example` documented none of it — it cannot document
ten rules it does not know about.

The two helpers that existed covered four sites between them and neither was
this: `src/runtime_limits._truthy` reads an environment variable (2 sites) and
`routes/model_routes._truthy` parses an HTTP request field (3 sites). `B91`
counted them as one pair that "disagree with each other". They answer different
questions about different inputs and unifying them would be `Law 14`; what this
module replaces is the first one only.

**The vocabulary is derived, not invented.** ON is the union of every on-set
already accepted somewhere in this tree; OFF is the union of every off-set. No
token is admitted that no site accepted before, so adopting this rule can only
make a site agree with a sibling it already disagreed with — it can never
invent a spelling nobody has typed.

    ON   1  true  yes  on
    OFF  0  false no   off

Case-folded and whitespace-stripped, because 37 of the 38 sites already did both
and the one that did not was a defect.

**Blank means unset, and that is not a new decision** — `settings.env_backed`
already settled it for the string half of this question and says so in its own
docstring. An operator who wants a switch *off* on a host whose environment
defines it should unset it in the environment, which is where it was set. Three
sites read `""` as OFF and six read it as ON; one answer had to win and this one
was already written down.

**Unrecognised is unset too**, which is what makes adoption nearly
behaviour-preserving: a site spelled `== "true"` is *off unless true* and a site
spelled `not in ("0","false","no")` is *on unless one of these*, so passing that
site's own documented default through `env_flag` reproduces its answer for every
value except the ones it had never heard of. The widenings that remain are
enumerated in `B91`, site by site, with the direction of each.

Stdlib only, and it must stay that way: `src/runtime_limits` is imported lazily
from `src/tool_utils`, which forbids project imports to avoid a cycle, and it is
one of the callers.
"""
from __future__ import annotations

import os

# Sorted for reading; membership is what matters. See the module docstring for
# where each token came from — every one of these is a spelling some site in
# this tree already accepted on 2026-09-15.
ON_VALUES = frozenset({"1", "on", "true", "yes"})
OFF_VALUES = frozenset({"0", "false", "no", "off"})


def env_truthy(raw: object) -> bool | None:
    """The vocabulary, as a three-valued answer.

    `None` means *the environment did not say* — absent, blank, whitespace, or a
    word outside the vocabulary. It is a third answer rather than a second
    falsehood because two callers genuinely need it: `SECURE_COOKIES` falls
    through to scheme auto-detection when nothing was configured, and `B90`'s
    three settings keys need "the operator stored nothing" to read differently
    from "the operator stored no".

    A non-string is returned as its own truthiness. A stored `False` arrives
    here typed, from `settings.json`, and `bool(False)` is the right answer;
    what must never happen is the string `"false"` being judged that way, and
    `bool("false")` is `True` — the trap `B20` named and `routes/email_helpers.
    _starttls` was written to avoid.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        return bool(raw)
    token = raw.strip().lower()
    if token in ON_VALUES:
        return True
    if token in OFF_VALUES:
        return False
    return None


def env_flag(name: str, default: bool = False) -> bool:
    """Is `name` on? `default` answers when the environment does not.

    `default` is the site's own documented default and not a house preference:
    passing it is what makes adoption reproduce the site's existing behaviour
    for every value that site already recognised.
    """
    answer = env_truthy(os.environ.get(name))
    return bool(default) if answer is None else answer


# ── The HTTP request-field rule (`B97`) ────────────────────────────────────
#
# Derived the way the environment set was derived, and from the same tree: every
# token below is one an HTTP site here already accepted on 2026-09-15.
# `routes/model_routes._truthy` read `("true", "1", "yes", "on")` at three body
# fields and `routes/model_routes.py:1442` read `("false", "0", "no", "off")` at
# one — so the eight words are not a preference, they are what the largest
# existing owner of this boundary already answered to.
REQUEST_ON_VALUES = ON_VALUES
REQUEST_OFF_VALUES = OFF_VALUES


def request_truthy(raw: object) -> bool | None:
    """The HTTP rule, as a three-valued answer. `None` means *the field did not
    say* — absent, blank, or a word outside the vocabulary.

    Three-valued for the same reason `env_truthy` is: a caller that needs the
    third answer genuinely needs it. `routes/model_routes._parse_supports_tools`
    is the one here — `supports_tools` is a tri-state where unrecognised must
    stay *work it out* rather than become `False`, because guessing `False`
    silently takes native tool support away from an endpoint that had it
    (`P3-22`). `request_flag` is the two-valued half for the other sixteen.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        # `B190`. 1 and 0 are the two integers a request field means by; any
        # other is a value nobody meant, which is what `None` is for.
        return True if raw == 1 else (False if raw == 0 else None)
    if not isinstance(raw, str):
        # `B190`. **Not `bool(raw)`.** The first spelling of this rule coerced
        # every non-string by its own truthiness, which reads a definite answer
        # out of an object that never gave one: `_parse_supports_tools({})`
        # returned `None` for eight months and started returning `False` — the
        # exact "quietly take tools away from an endpoint that had them" this
        # function's tri-state exists to prevent (`P3-22`) — and a direct call
        # to `read_email_by_uid` saw `full=Query(False)`, a truthy object, and
        # fetched whole message bodies where it had fetched a truncated one.
        # An unrecognised object did not say, the same as an unrecognised word.
        return None
    token = raw.strip().lower()
    if token in REQUEST_ON_VALUES:
        return True
    if token in REQUEST_OFF_VALUES:
        return False
    return None


def request_flag(raw: object, default: bool = False) -> bool:
    """Is this HTTP request field on? `default` answers when it does not say.

    `B97`. Thirteen sites spelled this `str(x).lower() == "true"` and two private
    half-helpers spelled it two other ways, neither reachable from the other's
    callers. The producer of nearly all of it is our own JavaScript, and our own
    JavaScript sends the literal strings `'true'` and `'false'` — measured across
    `static/js/` on 2026-09-15 — so adopting one rule changes nothing the product
    itself sends. What it changes is the answer given to a hand-written API call
    that says `plan_mode=1`, which used to mean *no*.

    **Widening only, and that is the whole safety argument** (`Law 1`): every
    site this replaces read `== "true"`, so nothing that was ON becomes OFF. Two
    sites are *not* converted because for them widening would loosen a gate
    rather than honour an intent — `allow_bash` in `routes/chat_routes.py` and
    `tool_policy.tool_toggle_enabled`. Each carries its reason at its own line
    in the form `.pantheon/check-env-declared.py` reads, which is the same hold
    `B91` gave the nine environment sites it could not move.

    A non-string is judged by its own truthiness: FastAPI has usually already
    coerced `?full=1` to a real `bool` before this sees it, and `bool(False)` is
    the right answer for that. A *string* never is — `bool("false")` is `True`,
    the trap `B20` named.
    """
    answer = request_truthy(raw)
    if answer is not None:
        return answer
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # A number outside {0, 1} is still a number, and its truthiness is a
        # real answer — `bool(2)` was this site's behaviour before `B97` and
        # `Law 1` keeps it. An arbitrary object's is not (`B190`).
        return bool(raw)
    return bool(default)


# ── The model tool-argument rule (`B97`) ───────────────────────────────────
#
# The union of the three answers this tree already gave, and nothing else:
# `src/ai_interaction.py:652` took ("on","true","1","yes","enable","enabled"),
# `:810` took four of those, and `src/builtin_actions.py:2782` took
# ("1","true","yes","y"). Three sites, three vocabularies, one question.
#
# Wider than the operator's set on purpose, and this is the boundary where the
# asymmetry is right: a model asked for a boolean writes `"enabled"` or `"y"`
# without being told to, and reading its `yes` as `no` is a silent
# misunderstanding of an instruction the user gave in words. An operator who
# types `y` into a `.env` file gets told it is not a spelling we take (`B91`
# settled that, deliberately, and it stays settled).
TOOL_ARG_ON_VALUES = frozenset(ON_VALUES | {"y", "enable", "enabled"})


def tool_arg_truthy(raw: object, default: bool = False) -> bool:
    """Did the model mean yes? `default` answers when the argument is absent.

    `B97`. Anything that is not one of `TOOL_ARG_ON_VALUES` is *no*, because all
    three sites this replaces were `in (...)` tests with no off-list at all —
    there is no third answer to preserve, and inventing one would change what
    every one of them does with an unrecognised word.

    A real `bool` or a number arrives from JSON already typed and is believed;
    `src/builtin_actions.py` was already doing that by hand before this existed.
    """
    if raw is None:
        return bool(default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if not isinstance(raw, str):
        return bool(raw)
    return raw.strip().lower() in TOOL_ARG_ON_VALUES
