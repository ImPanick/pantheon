# SPDX-License-Identifier: AGPL-3.0-or-later
# src/env_flags.py
"""One vocabulary for "is this environment variable on?" (`B91`).

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
