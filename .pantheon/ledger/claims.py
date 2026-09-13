# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every claim Pantheon makes about being better than the tree it forked from.

`P19`, from the owner: *"all improvements we have implemented so far over the
default Odysseus ... an evidence trail of how we are improving Odysseus as
Pantheon, and will serve as a proof ledger to set us aside as a no shit better
alternative."*

**A LEDGER IS WORTH EXACTLY WHAT ITS WEAKEST NUMBER IS WORTH.**

One figure that does not survive being checked is not one bad row — it is the row
a sceptic quotes, and everything above and below it then reads as the same kind of
thing. So the rule here is not *say impressive things carefully*. It is:

  1. Every claim names where its number came from (`provenance`).
  2. Every claim names a command a stranger can run (`repro`).
  3. Every claim names files that must still exist (`evidence`), so it cannot
     outlive the thing it cites.
  4. A number measured on a fixture says `fixture`, out loud, next to the number.

The fourth is the one that matters. `.pantheon/fixtures/retrieval_probe.json`
declares in its own file that *"pairs written from imagination test the
imagination"*. A ledger that states the retrieval numbers and **quotes that
caveat** cannot be ambushed with it. A ledger that states them and hides it can.

**THE FIRST THING THIS FILE DID WAS CORRECT ITS OWN HEADLINE.** The phase was
opened on *"memory ... where we improved efficiency from 0.31 to 0.77"*. Both
figures are real and they are different metrics: `0.319` is the **MRR** of the
lexical engine, `0.77` is today's **recall@5** on the manager path. As one ratio
it is wrong. The defensible pairs are `recall@5 0.40 -> 1.00` and
`MRR 0.319 -> 0.931` — a better result than the one claimed, and one that holds.

`PROVENANCE` in descending order of how much weight a row can carry:

  `diffed`   a diff against a named upstream ref. The strongest: the *before* is
             upstream's actual tree, not a memory of it.
  `measured` a command was run and its output recorded.
  `counted`  from counting this tree.
  `fixture`  measured, but on a corpus that declares itself a harness. The number
             describes the scorer, not the product, and the row says so.
  `cited`    a file, a line and a test. No number, and no number is claimed.
"""
from __future__ import annotations

from typing import NamedTuple, Tuple

# The fork point, measured 2026-09-11 on the deployment box, which is where the
# `upstream` remote lives. Every `diffed` row below is against this ref.
UPSTREAM_REMOTE = "pewdiepie-archdaemon/odysseus"
UPSTREAM_REF = "upstream/dev"
FORK_POINT = "b4d1293"
FORK_POINT_DATE = "2026-08-20"
FORK_POINT_SUBJECT = (
    "fix(agent): drop the empty assistant turn from an approved-action replay (#6124)"
)
MEASURED_ON = "2026-09-11"

PROVENANCE = ("diffed", "measured", "counted", "fixture", "cited")

# How each provenance tag should be read, printed in the ledger itself. A reader
# who cannot tell a diffed number from a fixture number has not been given
# evidence, they have been given a list.
PROVENANCE_MEANS = {
    "diffed": (
        "From a diff against upstream's actual tree at "
        f"`{FORK_POINT}`. The *before* is Odysseus, not a memory of it."
    ),
    "measured": "A command was run against this tree and its output recorded here.",
    "counted": "From counting this tree — files, call sites, declarations.",
    "fixture": (
        "Measured, but on a corpus that declares itself a harness. **The number "
        "describes the scorer, not real-world use.** Read the caveat beside it."
    ),
    "cited": "A file, a line and a test. No number is claimed.",
}


class Claim(NamedTuple):
    """One improvement, and what makes it checkable.

    `before`/`after` are strings rather than floats on purpose: `0.40` and
    `recall@5 0.40` and `9` are all legitimate, and a float column would force
    every row into one shape and lose the unit. The checker enforces that they
    are both present or both absent, which is the mistake worth catching — a
    lone *after* is an assertion wearing a measurement's clothes.
    """

    id: str
    area: str
    headline: str
    stock: str          # what the tree we forked from does
    pantheon: str       # what this tree does
    before: str
    after: str
    provenance: str
    repro: str          # a command a stranger can run
    evidence: Tuple[str, ...]   # paths that must still exist
    rows: Tuple[str, ...]       # roadmap rows / decisions that argued it
    how: str            # how we got there — the method, and the interesting part


# ---------------------------------------------------------------------------
# Areas, in the order they appear in the ledger. The order is an argument: the
# size of the fork first (because a reader's first question is "how much of this
# is actually different"), then the thing the owner cares most about, then the
# rest by how hard each is to claim without evidence.
# ---------------------------------------------------------------------------

AREAS = (
    ("Scale of the fork", "How much of this tree is not upstream's, measured rather than asserted."),
    ("Memory and retrieval", "The Brain. The one place a number was already being quoted, and the one that needed correcting first."),
    ("Verification apparatus", "The part that makes every other row here checkable. Upstream has none of it."),
    ("Reaching the host", "What a container cannot do, and the one honest way to do it anyway."),
    ("Self-hosted by default", "Law 16: nothing routes to an external service unless a person linked it."),
    ("Outbound politeness", "What this software does to somebody else's server when nobody is watching."),
    ("Trust and approvals", "What the agent may do, who is asked, and what can never be switched off."),
    ("Licence and provenance", "AGPL-3.0 compliance, which upstream ships and does not fully honour."),
    ("Dead code and wiring", "Code that shipped, ran, and reached nothing."),
    ("Themes and contrast", "Sixteen palettes, and the arithmetic that keeps text readable on all of them."),
)


CLAIMS: Tuple[Claim, ...] = (

    # -- Scale of the fork ---------------------------------------------------

    Claim(
        id="fork-size",
        area="Scale of the fork",
        headline="156 commits and 175,966 inserted lines past the fork point.",
        stock="Odysseus at `b4d1293`, 2026-08-20.",
        pantheon="This tree.",
        before="0 commits",
        after="156 commits, 1,964 files changed, 175,966 insertions, 6,625 deletions",
        provenance="diffed",
        repro=f"git diff --shortstat {FORK_POINT}..HEAD && git rev-list --count {FORK_POINT}..HEAD",
        evidence=(".pantheon/ROADMAP.md",),
        rows=(),
        how=(
            "Measured on the deployment box, which is the only machine carrying the "
            "`upstream` remote. The cloud mirror's history begins at an import commit, "
            "so this number cannot be produced there — which is itself worth knowing "
            "about any fork claiming a diff it cannot run."
        ),
    ),

    Claim(
        id="add-never-subtract",
        area="Scale of the fork",
        headline="537 files added. Five removed, and all five are argued.",
        stock="Upstream's file set at the fork point.",
        pantheon=(
            "Everything upstream shipped is still here, minus five files, each deleted "
            "with a recorded argument: `ACKNOWLEDGMENTS.md` (superseded by `CREDITS.md`, "
            "105 -> 483 lines), `scripts/_completion/odysseus.zsh` (a rename), "
            "`docs/pantheon-wordmark.png` (upstream's mark, **renamed and never "
            "repainted** — the filename said Pantheon and the pixels said Odysseus; "
            "`P0-13` says in as many words not to reuse it), "
            "`static/fonts/custom/GohuFont.ttf` (verified first: 1,468 bytes, 13 sfnt "
            "tables, **3 glyphs**, metadata reading *Untitled1 / Copyright (c) 2025, "
            "Unknown*), and `static/js/calendar/reminders.js` (a dead poller)."
        ),
        before="—",
        after="537 added · 1,387 modified · 5 removed",
        provenance="diffed",
        repro=f"git diff --name-status {FORK_POINT}..HEAD | grep '^D'",
        evidence=("CREDITS.md", ".pantheon/DECISIONS.md"),
        rows=("P0-19", "P0-23", "P3-10", "P0-13", "B71", "D-2026-08-27-01"),
        how=(
            "This is the fork's first law as a measurement — *an elevation, not a rip "
            "and re-write; we add, never subtract*. A ratio of 537 to 4 is only "
            "evidence if the four are named, so they are. The font is the one worth "
            "reading: it was checked before deletion rather than taken on trust, and "
            "it turned out to be three glyphs under a copyright notice crediting nobody. "
            "**The fifth was found by a failing test nobody had looked at**: the "
            "orphan-image guard had been red for the whole fork, saying a doc image "
            "was referenced by nothing — and the reason nothing referenced it was "
            "that it was upstream's logo wearing our filename."
        ),
    ),

    Claim(
        id="behind-upstream",
        area="Scale of the fork",
        headline="Twelve upstream commits are not merged, and five of them are real fixes.",
        stock=f"`{UPSTREAM_REF}` has moved 12 commits past the fork point.",
        pantheon="None are merged yet. `P19-06` does the merge.",
        before="0 behind",
        after="7 with no patch-equivalent here (5 docs/deps, 2 advisory merges landed by hand)",
        provenance="measured",
        repro=f"git cherry main {UPSTREAM_REF} | grep -c '^+'",
        evidence=(".pantheon/ROADMAP.md",),
        rows=("P19-05", "P19-06"),
        how=(
            "**This row exists because a ledger with no limitations section reads as "
            "marketing** — and it earned its place twice over. Measuring the gap "
            "found that **two of the twelve are a security fix**, shipped through a "
            "private advisory fork: a bearer API token inherited its minting admin's "
            "tool authority, and a chat-session approval grant was readable back out of "
            "caller-writable message metadata. Neither is in this tree. `B70` backports "
            "them ahead of the rest, because the full merge carries 18 conflicts over "
            "branding and the README and a security fix must not wait on those. The "
            "other five that matter are ordinary: `#6158` docker cache ownership, "
            "`#6228` caching an empty Tailscale lookup, `#6174` task singleflight "
            "cleanup, `#5937` psycopg2-binary, `#6168` version alignment. **A fork that "
            "stops taking upstream's fixes does not merely go stale.** "
            "Counted with `git cherry` rather than `git rev-list`, and that "
            "distinction was found by this ledger's own check failing: a "
            "cherry-pick is a new commit with a new sha, so `rev-list` still "
            "reported twelve behind after five had landed. `git cherry` compares "
            "patch ids. Two of the seven remaining are the advisory merge commits "
            "themselves — their **content** is in this tree as `B70`, ported by "
            "hand, so no patch id matches and the count says seven where the "
            "substance is five."
        ),
    ),

    # -- Memory and retrieval ------------------------------------------------

    Claim(
        id="retrieval-recall",
        area="Memory and retrieval",
        headline="recall@5 on one corpus: 0.40 lexical, 0.77 hybrid, 1.00 semantic.",
        stock=(
            "A lexical scorer — BM25 with corpus IDF — reached through two duplicate "
            "implementations serving five surfaces differently."
        ),
        pantheon=(
            "One retrieval path, with a local ONNX embedding model that needs no "
            "service and no network. The degraded path — no vector service running — "
            "is the one scored, because it is the one a person actually meets."
        ),
        before="recall@5 0.40",
        after="recall@5 1.00",
        provenance="fixture",
        repro="python3 .pantheon/retrieval_eval.py",
        evidence=(".pantheon/retrieval_eval.py", ".pantheon/fixtures/retrieval_probe.json"),
        rows=("P13-11", "P13-13", "P13-14", "P13-21", "D-2026-09-08-07"),
        how=(
            "**Read the provenance tag before quoting this.** The corpus is a harness "
            "fixture and says so in its own file: *\"pairs written from imagination "
            "test the imagination.\"* What these numbers prove is that the scorer "
            "works, that both engines run over one corpus, and that named collisions "
            "are caught rather than argued about. They are **not** a measurement of "
            "how well Pantheon remembers in real use; only an operator's own memories "
            "with probes they wrote can support that, and `retrieval_eval.py "
            "--generate` exists to build one. The eval prints this caveat above the "
            "numbers every run, so the number cannot travel without it."
        ),
    ),

    Claim(
        id="retrieval-mrr",
        area="Memory and retrieval",
        headline="MRR 0.319 -> 0.931. Rank matters because memory is injected under a slot limit.",
        stock="Lexical only: MRR 0.319.",
        pantheon="Semantic: MRR 0.931. The hybrid path in between reads 0.767.",
        before="MRR 0.319",
        after="MRR 0.931",
        provenance="fixture",
        repro="python3 .pantheon/retrieval_eval.py",
        evidence=(".pantheon/retrieval_eval.py",),
        rows=("P13-13", "P13-21"),
        how=(
            "**recall@5 and MRR disagree on purpose, and the disagreement is the "
            "point.** An engine that is always right at rank 5 scores 1.00 recall and "
            "0.20 MRR — and memories are injected under a slot limit, so rank is not "
            "cosmetic. Reporting recall alone would have hidden exactly the failure "
            "this metric exists to catch. **This is also the pair the phase was opened "
            "to correct**: `0.319` is an MRR and `0.77` is a recall, and quoting one "
            "against the other as a single improvement is the first thing a sceptic "
            "breaks."
        ),
    ),

    Claim(
        id="retrieval-defects",
        area="Memory and retrieval",
        headline="The first scored run found three defects, which is what it was built for.",
        stock="Nothing measured retrieval quality, so every change to it shipped on taste.",
        pantheon="A golden set that runs in CI as a report — deliberately never a gate.",
        before="0 measured",
        after="3 defects on the first run",
        provenance="measured",
        repro="python3 .pantheon/retrieval_eval.py",
        evidence=(".pantheon/retrieval_eval.py",),
        rows=("P13-13", "B62"),
        how=(
            "Neither engine stems, so *what do I **drive*** misses *User **drives** a "
            "diesel van*; *who am i* — the canonical memory question — reduces to "
            "**zero content tokens**, so no lexical engine can answer it at all; and a "
            "corpus every engine passes measures nothing, so a test now fails if either "
            "engine ever scores perfectly. A report and not a gate, because a ratchet "
            "on a number nobody has calibrated is how a checker starts lying."
        ),
    ),

    Claim(
        id="retrieval-no-service",
        area="Memory and retrieval",
        headline="Ten thousand memories, under a millisecond a query, no service running.",
        stock="Vector search meant a separate ChromaDB process behind a 2-second port probe.",
        pantheon="Brute-force cosine over 384-dimension vectors with numpy, in-process.",
        before="a service, or nothing",
        after="0.82ms at 10,000 memories (15MB of index)",
        provenance="measured",
        repro="python3 .pantheon/retrieval_eval.py --engine semantic",
        evidence=(".pantheon/retrieval_eval.py",),
        rows=("P13-21",),
        how=(
            "Measured across the range: 0.13ms at 100 memories, 0.18ms at 1,000, 0.82ms "
            "at 10,000, 12ms at 100,000, 135ms at a million. **A personal Brain of ten "
            "thousand memories is years of daily use.** The row exists because the "
            "honest question was not *is a vector database faster* but *does a person's "
            "own memory set ever get big enough for one to be worth running*, and the "
            "measurement says no."
        ),
    ),

    # -- Verification apparatus ----------------------------------------------

    Claim(
        id="checkers",
        area="Verification apparatus",
        headline="Fifteen checkers in CI, each one built from a defect that actually shipped.",
        stock="No repository-level checkers.",
        pantheon=(
            "`.pantheon/release-gate.py` runs all fifteen, reading the list from "
            "`ci.yml` rather than keeping a second copy of it."
        ),
        before="0",
        after="15",
        provenance="counted",
        repro="python3 .pantheon/release-gate.py --fast",
        evidence=(".pantheon/release-gate.py", ".github/workflows/ci.yml"),
        rows=("P3-13", "P3-14", "P3-17", "P3-23", "D-2026-09-10-03"),
        how=(
            "**Not one of these was designed in advance.** Each replaced a paragraph "
            "that had already failed to prevent the same defect twice or more — a tool "
            "name missing from one of nine registries, a silent `except: pass`, an "
            "undeclared environment variable, a module imported under three specifiers. "
            "The rule that gets written down is the rule that gets forgotten; the rule "
            "that runs in CI is the rule. The gate reads its own checker list out of "
            "`ci.yml` so the two cannot disagree."
        ),
    ),

    Claim(
        id="tests",
        area="Verification apparatus",
        headline="Test files 792 -> 930, and a suite of 8,862 passing with nothing red.",
        stock="792 test files.",
        pantheon="930 test files, 8,862 tests passing, 0 failing.",
        before="792 test files",
        after="930 test files · 8,862",
        provenance="diffed",
        repro=f"git ls-tree -r --name-only {FORK_POINT} | grep -c '^tests/test_.*\\.py$' && python3 -m pytest -q",
        evidence=("tests",),
        rows=(),
        how=(
            "Every row in this fork's tracker lands with tests **and** mutations: the "
            "change is made, then the code is deliberately broken in a dozen ways to "
            "check the new tests actually notice. Mutation runs have repeatedly found "
            "that a passing test was proving nothing — a window that matched the next "
            "block's code, a scan satisfied by a name inside `if False:`. "
            "**Proximity is not reachability**, and only a mutation run says so. "
            "**The suite carried 14 standing failures for the fork's whole life and "
            "now carries none** — and the accounting is worth more than the number: "
            "eight were this container missing dependencies the project already "
            "declares, so they were never defects; three were test stubs left behind "
            "by a `headers=` argument, each raising `TypeError` into a broad "
            "`except` so the probe returned `None` and the assertion read as a "
            "logic bug; one was a rule written as an allowlist of one name instead "
            "of the property it meant; and two were pinning upstream's README and "
            "wordmark against a decision this fork had already recorded."
        ),
    ),

    Claim(
        id="tracker",
        area="Verification apparatus",
        headline="One tracker, checked by a script, after it was silently wrong by nineteen.",
        stock="No task tracker in-repo.",
        pantheon=(
            "`.pantheon/ROADMAP.md` is the single tracker, and "
            "`.pantheon/check-tracker.py` validates every phase row against its own "
            "ticks and the newest progress entry against the totals."
        ),
        before="untracked",
        after="370 rows, every one recounted against its section",
        provenance="measured",
        repro="python3 .pantheon/check-tracker.py",
        evidence=(".pantheon/ROADMAP.md", ".pantheon/check-tracker.py"),
        rows=("B44",),
        how=(
            "The checker exists because the summary line — the one line in the file "
            "whose whole job is to summarise the rest — read `135 done` against a table "
            "saying `116`, **wrong by nineteen and carried forward unread from entry to "
            "entry** because each author copied the line above. Older entries keep the "
            "figure they were written with: a record of what was claimed at the time is "
            "worth more than a quietly corrected one."
        ),
    ),

    # -- Reaching the host ---------------------------------------------------

    Claim(
        id="host-guard",
        area="Reaching the host",
        headline="Agents can run commands on the host. 52 rules they cannot reach say what never runs.",
        stock="The shell runs in the container and cannot reach the host. There is no host agent.",
        pantheon=(
            "A small standard-library process on the host answers a narrow protocol. "
            "Pantheon gains **the ability to ask**, not the ability to widen what may "
            "be asked."
        ),
        before="no host reach",
        after="52 compiled-in rules · 0 bypasses",
        provenance="counted",
        repro="python3 -c \"from netagent import guard; print(len(guard.rules()))\"",
        evidence=("netagent/guard.py", "netagent/execute.py", "src/host_exec_policy.py"),
        rows=("P17-01", "P17-11", "D-2026-09-11-01"),
        how=(
            "There are four ways past a container: the Docker socket, `--privileged`, "
            "host SSH credentials, or a process on the host. The first three hand over "
            "the host and then try to claw capability back with rules **inside** the "
            "thing being constrained. Only the fourth puts the rules on the far side of "
            "a boundary the constrained party cannot cross — so the denylist lives in a "
            "different process, started by the operator, with no route that writes it, "
            "and there is **no bypass at all** rather than an admin-gated one, because "
            "a bypass exists to be left on."
        ),
    ),

    Claim(
        id="guard-opaque",
        area="Reaching the host",
        headline="Five of the 52 rules aren't about danger. They keep the other 47 enforceable.",
        stock="—",
        pantheon=(
            "`base64 -d | sh`, `powershell -EncodedCommand`, `curl | sh`, `eval` of a "
            "variable and `xxd -r` are refused as a category."
        ),
        before="—",
        after="5 opaque · 47 nuclear",
        provenance="counted",
        repro="python3 -c \"from netagent import guard; print(len(guard._OPAQUE), len(guard._NUCLEAR))\"",
        evidence=("netagent/guard.py",),
        rows=("P17-11", "D-2026-09-11-01"),
        how=(
            "None of the five is dangerous by itself. Each one makes string inspection "
            "meaningless, and **a denylist that can be handed an opaque payload is a "
            "denylist with one rule.** This is the part of a blocklist that is usually "
            "missing, and it is missing because it does not look like a security rule."
        ),
    ),

    Claim(
        id="guard-rules-fire",
        area="Reaching the host",
        headline="Four of the 52 rules were dead on arrival. A test now proves all 52 fire.",
        stock="—",
        pantheon="Every rule carries a real example and a test walks all 52.",
        before="4 rules matched nothing",
        after="52 of 52 proven to fire",
        provenance="measured",
        repro="python3 -m pytest tests/test_the_host_can_be_reached_but_not_widened.py -q",
        evidence=("netagent/guard.py", "tests/test_the_host_can_be_reached_but_not_widened.py"),
        rows=("P17-11",),
        how=(
            "`\\b` asserts a word boundary, and neither `-` nor `/` is a word character "
            "— so `\\bformat\\b` after a space never matched `format C: /fs:ntfs`. Four "
            "rules that read correctly fired on nothing. **A rule that cannot fire is "
            "worse than an absent one, because it is counted.** The fix was structural "
            "rather than a patch: every rule became a 4-tuple carrying an example, and "
            "`test_every_rule_can_actually_fire` asserts each example trips its own rule."
        ),
    ),

    # -- Self-hosted by default ----------------------------------------------

    Claim(
        id="no-phone-home",
        area="Self-hosted by default",
        headline="No shipped default addresses an external service. A checker keeps it that way.",
        stock=(
            "Defaults reached outward — an `npx -y @playwright/mcp@latest` fetch ran "
            "roughly three seconds after every boot."
        ),
        pantheon="Zero absolute URLs in shipped defaults; all 32 shipped URLs elsewhere are loopback, RFC1918 or tailnet.",
        before="external by default",
        after="0 external destinations in defaults",
        provenance="measured",
        repro="python3 .pantheon/check-destinations.py",
        evidence=(".pantheon/check-destinations.py",),
        rows=("P16-01", "P16-13", "D-2026-09-01-03"),
        how=(
            "The fork's sixteenth law, in the owner's words: *\"we drop external "
            "dependence. i dont want things that'll may route to external services "
            "unless the user (or sysadmin) explicitly links it\"* — later amended to "
            "allow telemetry while still forbidding a phone-home. The baseline was "
            "measured **before** the ratchet went in, because a ratchet set at an "
            "unmeasured number is a ratchet that permits whatever was already there."
        ),
    ),

    Claim(
        id="vendored",
        area="Self-hosted by default",
        headline="The front end fetches nothing at runtime. Fonts, emoji, Pyodide, skills — all local.",
        stock="Runtime fetches for assets and a skills library pulled on demand.",
        pantheon=(
            "13.8 MB of Pyodide, ~4 MB of OpenMoji as one 5 MB JSON rather than 4,147 "
            "files, and 286 skills vendored from ECC pinned to upstream 2.2.0 @ 005eff4."
        ),
        before="fetched at runtime",
        after="vendored, 286 skills, all parsing",
        provenance="counted",
        repro="python3 .pantheon/check-licences.py && ls library/ecc | wc -l",
        evidence=("static/lib/pyodide", "library/ecc"),
        rows=("P16-03", "P16-06", "P16-07"),
        how=(
            "The emoji set is the instructive one: **the same bytes cost 18 MB on disk "
            "as individual files and 5 MB as one JSON**, because a file system charges "
            "by the block. Repointing only the Pyodide script tag would have left three "
            "of five files still remote — a half-vendoring that looks complete from the "
            "network tab until the one machine without internet tries it."
        ),
    ),

    # -- Outbound politeness -------------------------------------------------

    Claim(
        id="fan-out",
        area="Outbound politeness",
        headline="One click fired up to 260 unauthenticated requests at somebody else's API.",
        stock="13 collection sources x 20 pages, sequential, zero delay, no token.",
        pantheon="A shared request budget across the whole refresh: 40, against a worst case of 260.",
        before="260 requests per click",
        after="40, budgeted and shared",
        provenance="counted",
        repro="python3 .pantheon/check-outbound.py --max 116",
        evidence=(".pantheon/check-outbound.py",),
        rows=("P15-05", "P15-06"),
        how=(
            "Unauthenticated GitHub allows **60 requests an hour**. One click of a "
            "discovery refresh spent more than four hours of that budget, and the "
            "user's own network wore the rate limit. An audit across 50 outbound "
            "modules found a second shape worth naming: a failing batch of 8 embeddings "
            "was retried as 8 single requests — **a fan-out amplifier that turns one "
            "request into nine at exactly the moment the far end is struggling.**"
        ),
    ),

    Claim(
        id="retry-forever",
        area="Outbound politeness",
        headline="A failed follow-up retried every 5 seconds forever — 720 attempts an hour.",
        stock="`src/bg_monitor.py` retried on a flat 5-second loop with no ceiling and no give-up.",
        pantheon="30 seconds doubling to 30 minutes with jitter, and it gives up after 12.",
        before="720 attempts/hour, forever",
        after="exponential with jitter, cap 12",
        provenance="cited",
        repro="python3 .pantheon/check-jitter.py",
        evidence=("src/bg_monitor.py", ".pantheon/check-jitter.py"),
        rows=("P15-04", "P15-10"),
        how=(
            "Each of those 720 attempts could run up to 12 model rounds. The "
            "companion checker is the durable half: it found **twelve sites a hand "
            "audit had missed, and two were real** — which is the argument for a "
            "checker over a sweep in one sentence. Recurring work is also held off "
            "exact clock boundaries, scaled to the task's own period, so a fleet of "
            "these does not synchronise into a thundering herd at `:00`."
        ),
    ),

    # -- Trust and approvals -------------------------------------------------

    Claim(
        id="trust-rungs",
        area="Trust and approvals",
        headline="Three trust rungs, a 13-value capability taxonomy, and 21,360 cases pinning it.",
        stock="A capability taxonomy that was written and used to rank nothing.",
        pantheon="`ask_every_time` / `allow_listed` / `gate_on_untrusted`, with capabilities ranked and shown on the approval card.",
        before="taxonomy unused",
        after="21,360 cases, 0 diverged",
        provenance="measured",
        repro="python3 -m pytest tests/ -k trust -q",
        evidence=("src/tool_capabilities.py",),
        rows=("P7-03", "P7-06", "D-2026-08-29-01", "D-2026-08-29-02"),
        how=(
            "The refactor was pinned by sweeping **every known tool x 20 hostile "
            "contents x taint x bypass x three lookup shapes** against an oracle "
            "transcribed from the previous commit — verdict *and* reason string, 0 "
            "diverged. Ranks are spaced by ten so a value can be inserted later without "
            "renumbering, which is the kind of decision that costs nothing now and a "
            "migration later."
        ),
    ),

    Claim(
        id="approval-honesty",
        area="Trust and approvals",
        headline="Four event types carried an approval flag no line of the frontend ever read.",
        stock="Every result card said `approved: true` whether or not anyone had approved it.",
        pantheon="The flag is read, and a card that was not approved does not say it was.",
        before="4 events lying",
        after="0",
        provenance="cited",
        repro="python3 -m pytest tests/ -k approval -q",
        evidence=("src/tool_execution.py",),
        rows=("P4-12", "P4-21"),
        how=(
            "The flag had been emitted on four events since exact approvals shipped, "
            "and nothing consumed it. **A permission UI that always says yes is worse "
            "than none**, because it trains the person to stop reading. The same row "
            "found `consume` returning a bare `None` four different ways — lapsed, "
            "unknown, somebody else's, and a decision the card does not offer — all "
            "four indistinguishable to the caller."
        ),
    ),

    # -- Licence and provenance ----------------------------------------------

    Claim(
        id="spdx",
        area="Licence and provenance",
        headline="1,541 files of program text now declare their licence. None did.",
        stock="No SPDX identifiers.",
        pantheon="Every shipped file of program text carries `AGPL-3.0-or-later`, and no vendored file does.",
        before="0 files",
        after="1,541 files",
        provenance="measured",
        repro="python3 .pantheon/check-spdx.py",
        evidence=(".pantheon/check-spdx.py",),
        rows=("P0-18",),
        how=(
            "The checker enforces **both directions**, and the second is the one that "
            "matters: a vendored third-party file must *not* claim this project's "
            "licence. A sweep that only adds headers relicenses other people's code by "
            "accident."
        ),
    ),

    Claim(
        id="credits",
        area="Licence and provenance",
        headline="CREDITS.md 105 -> 483 lines, and thirteen licence texts that were never shipped.",
        stock=(
            "Bundled third-party code without its licence text; the desktop builds "
            "redistributed a dozen libraries with attribution stripped."
        ),
        pantheon="Every shipped third-party file attributed, with the licence body at the version actually vendored.",
        before="105 lines",
        after="483 lines · 13 licence texts",
        provenance="counted",
        repro="python3 .pantheon/check-licences.py",
        evidence=("CREDITS.md", "licenses", ".pantheon/check-licences.py"),
        rows=("P0-19", "P0-20", "P0-21", "P0-21b", "P0-30", "D-2026-09-07-01"),
        how=(
            "Each licence was **fetched from upstream at the version actually vendored "
            "here**, not reconstructed from memory; nine had their text fetched at two "
            "versions spanning the plausible range and compared byte for byte. The "
            "count itself was wrong twice — a `/*!`-only scan said five where a sweep "
            "across all comment forms found 23 copyright-bearing blocks in 955, and "
            "webpack had left **1,736 `node_modules/<package>/` paths inside a shipped "
            "blob**. AGPL compliance is not a paragraph; it is a file list."
        ),
    ),

    # -- Dead code and wiring ------------------------------------------------

    Claim(
        id="wiring",
        area="Dead code and wiring",
        headline="Unreachable UI 78 -> 2, and 1,524 lines deleted against 340 added.",
        stock="78 wiring defects: markup, handlers and ids that nothing could reach.",
        pantheon="A ratchet in CI that cannot go up.",
        before="78",
        after="2",
        provenance="measured",
        repro="python3 .pantheon/check-wiring.py --max 124",
        evidence=(".pantheon/check-wiring.py",),
        rows=("P3-13", "P3-14", "P3-15"),
        how=(
            "The fix was **overwhelmingly deletion** — 1,524 lines removed against 340 "
            "added — which is what a wiring defect usually is: code that was written, "
            "shipped, and never reached. The companion route checker had a worse "
            "version of the same disease: it recursed, found nothing, and reported "
            "**23 routes when the real number was 443**, looking entirely correct while "
            "doing so."
        ),
    ),

    Claim(
        id="specifiers",
        area="Dead code and wiring",
        headline="A 3,126-line module was parsed three times per page load.",
        stock="167 modules imported under 178 distinct specifiers — 11 forked.",
        pantheon="173 modules, 173 specifiers, 0 forked, enforced at `--max 0`.",
        before="11 forked",
        after="0",
        provenance="measured",
        repro="python3 .pantheon/check-specifiers.py --max 0",
        evidence=(".pantheon/check-specifiers.py",),
        rows=("P3-11",),
        how=(
            "The same file reached under `./x.js`, `/static/js/x.js` and `x.js` is "
            "three modules to a browser, with three copies of its module state. 42 "
            "specifier rewrites across 27 files, plus **eight service-worker precache "
            "entries that had never matched a request URL** — cached on every install "
            "and never once served."
        ),
    ),

    Claim(
        id="silent-failures",
        area="Dead code and wiring",
        headline="440 silent exception handlers, 12 of them explained. The mutating ones are now zero.",
        stock="440 `except: pass` handlers across the tree; 12 carried any explanation.",
        pantheon="Every silent handler that mutates state is closed or explained, held at zero in CI.",
        before="26 mutating-and-silent",
        after="0",
        provenance="measured",
        repro="python3 .pantheon/check-silent-failures.py --max 402",
        evidence=(".pantheon/check-silent-failures.py",),
        rows=("P3-17",),
        how=(
            "Counted by AST, not grep — an earlier estimate said 199 and was wrong "
            "twice before the parser settled it at 440. The split is the useful part: "
            "**11 were genuinely hiding a failure** and now log, **15 were correct to "
            "swallow** and now say why. The remaining 402 are a ratchet that can only "
            "come down, because closing all of them at once would have been a very "
            "large change made on very little evidence."
        ),
    ),

    # -- Themes and contrast -------------------------------------------------

    Claim(
        id="contrast",
        area="Themes and contrast",
        headline="White-on-accent fails WCAG AA on 15 of 16 themes. The fix was not a new token.",
        stock="`color:#fff` hard-coded on the send button and 33 rules painting text on an undiluted accent.",
        pantheon="No global accent token, and every option the theme picker offers clears 4.5:1 on all sixteen themes by construction.",
        before="15 of 16 themes failing",
        after="0 by construction",
        provenance="measured",
        repro="python3 -m pytest tests/ -k contrast -q",
        evidence=("static/style.css",),
        rows=("P1-02", "P1-03", "D-2026-08-26-03", "D-2026-09-08-01"),
        how=(
            "**The obvious fix was measured and rejected.** Defining `--accent` "
            "globally would have flipped 553 sites carrying `var(--accent, var(--red))` "
            "to one colour and **collapsed all sixteen themes into one**. The count was "
            "re-measured four times across the phase — 508, 521, 535, then 816 sites at "
            "implementation — and each correction changed the answer. Two palettes "
            "(`cute`, `retrowave`) cannot reach 4.5:1 by any foreground choice, which "
            "is recorded as a known ceiling rather than quietly rounded away."
        ),
    ),
)
