# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B622` — the action pins are a supply-chain control, and nothing offline held it.

`.github/dependabot.yml`'s own header states the property this file protects:

> every workflow in this repo pins its GitHub Actions to an exact commit (a
> SHA), which is safe but freezes them in time

A tag is not a commit. `actions/checkout@v7` is whatever the `v7` ref points at
the moment a runner resolves it, and whoever can move that ref runs code in a
job holding this repository's token. A SHA cannot be moved. So the difference
between `@v7.0.1` and `@3d3c42e5…` is the whole control, and a bump that lands
the first while claiming the second is a regression wearing an upgrade's commit
message — the single most likely way this property is lost, because the diff
looks like every other Dependabot diff.

**What was checking it.** `zizmor` in `.github/workflows/workflow-security.yml`,
which flags unpinned actions and is the right tool for the job. `B526` is why
that is not enough: **no job in this repository has started since the account's
billing block, so `workflow-security` has never run**, and a control enforced
only by a workflow that cannot start is a control nobody is applying. These
tests are the offline half, in the suite a contributor actually runs.

Three rules, and the third is the one a partial bump breaks:

  1. every `uses:` names a 40-hex commit;
  2. every one carries a `# vX.Y.Z` comment, because a bare SHA tells a reader
     nothing about what it is or whether it is current;
  3. one action is one SHA and one version label across the whole tree — a bump
     that rewrites ten of eleven `actions/checkout` lines leaves the eleventh
     running a different release than the label beside it in the next file, and
     that reads as a typo rather than as the divergence it is.

**What these do not check.** Whether the pinned commit is the newest release:
that is a fact about the world, it needs the network, and `Law 16` keeps the
suite offline. It is Dependabot's job, and `.pantheon/check-pins.py` has the
same split for Python for the same reason.
"""
import collections
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

# `owner/repo[/sub/path]@<ref>`, with whatever trails it on the line. Deliberately
# permissive about the ref: a rule that only matched a SHA could not report the
# tag it was written to catch.
_USES = re.compile(
    r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+?)\s*(?:#\s*(?P<comment>.*?))?\s*$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_VERSION = re.compile(r"^v\d+(?:\.\d+)*$")


def _pins():
    """`(file, line number, action, ref, comment)` for every `uses:` in a workflow."""
    out = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = _USES.match(raw)
            if not match:
                continue
            ref = match.group("ref")
            action, _, rev = ref.rpartition("@")
            out.append((path.name, number, action or ref, rev if action else "",
                        (match.group("comment") or "").strip()))
    return out


def test_there_are_workflows_to_check():
    """A rule that silently checks nothing passes forever (`Law 10`)."""
    pins = _pins()
    assert len(pins) > 20, f"only {len(pins)} `uses:` found — the parser is wrong"


@pytest.mark.parametrize("pin", _pins(), ids=lambda p: f"{p[0]}:{p[1]}")
def test_every_action_is_pinned_to_a_commit_and_labelled(pin):
    """Rules 1 and 2, per line, so a failure names the line to fix."""
    name, number, action, rev, comment = pin
    if action.startswith("./"):  # a local composite action is this repository
        return
    assert _SHA.match(rev), (
        f"{name}:{number}: `{action}@{rev}` is not a 40-hex commit. A tag or "
        f"branch is resolved by the runner at run time, so whoever can move it "
        f"runs code in a job holding this repository's token")
    assert _VERSION.match(comment), (
        f"{name}:{number}: `{action}` is pinned to {rev[:12]}… with no `# vX.Y.Z` "
        f"beside it — a bare commit tells a reader nothing about which release "
        f"it is or whether it is behind one")


def test_one_action_is_one_commit_and_one_label_across_the_tree():
    """Rule 3. A half-finished bump is the failure mode with no other detector."""
    by_action = collections.defaultdict(set)
    sites = collections.defaultdict(list)
    for name, number, action, rev, comment in _pins():
        if action.startswith("./"):
            continue
        by_action[action].add((rev, comment))
        sites[action].append(f"{name}:{number}")
    split = {a: v for a, v in by_action.items() if len(v) > 1}
    assert not split, "\n".join(
        f"{action} is pinned {len(v)} different ways — "
        + "; ".join(f"{rev[:12]}… ({comment or 'no label'})" for rev, comment in sorted(v))
        + f" — at {', '.join(sites[action])}"
        for action, v in sorted(split.items()))


def test_two_sub_actions_of_one_repository_move_together():
    """`github/codeql-action/init`, `/analyze` and `/upload-sarif` are three
    `uses:` lines from one release of one repository. Bumping one of the three
    is the same divergence as rule 3 and the action names do not match, so rule
    3 cannot see it."""
    by_repo = collections.defaultdict(set)
    for name, number, action, rev, comment in _pins():
        if action.startswith("./") or action.count("/") < 2:
            continue
        by_repo["/".join(action.split("/")[:2])].add((rev, comment))
    split = {r: v for r, v in by_repo.items() if len(v) > 1}
    assert not split, "\n".join(
        f"{repo}'s sub-actions are on {len(v)} different releases: "
        + "; ".join(f"{rev[:12]}… ({comment or 'no label'})" for rev, comment in sorted(v))
        for repo, v in sorted(split.items()))
