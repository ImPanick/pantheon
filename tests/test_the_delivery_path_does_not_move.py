# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1409` — the way to get a change onto the server is findable twice.

For several waves the apply script was delivered *into* the clone as a loose
file, at a path that changed each time. So the next session's instructions
pointed at the previous session's path, and the owner got:

    /usr/bin/bash: .pantheon-transfer/apply-release.sh: No such file or directory

Nothing was broken; the instruction was. That is `Law 15` — *findable without a
tutorial* — failing on the one procedure that stands between a green suite and
a running server, and it had failed quietly for weeks because each session
re-sent the file and nobody noticed the path was new every time.

So the script is **committed**, at a path that does not move, and the procedure
is written down in `docs/delivery.md` rather than in a chat message. These
cases exist to keep the two from drifting apart and to keep the script honest
about what it refuses.

**The doc leads with the two-command form on purpose**, and that is the part
worth defending: `git fetch <bundle> main:refs/remotes/bundle/main` followed by
`git merge --ff-only` depends on nothing but git. The committed script cannot
help with the delivery that installs it — a clone on an older commit does not
have it yet — so a procedure that *only* existed as a script would have exactly
the hole it was written to close.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".pantheon" / "apply-release.sh"
DOC = ROOT / "docs" / "delivery.md"


def _flat(path: Path) -> str:
    """Prose with its line breaks flattened.

    A phrase in Markdown is wrapped wherever the line ran out, so a substring
    check against the raw file fails on a sentence that reads perfectly — which
    is how the first draft of this file reported a doc missing a paragraph it
    actually had. The README tests in this repository normalise the same way.
    """
    return " ".join(path.read_text(encoding="utf-8").split())


def test_the_script_is_committed_at_the_documented_path():
    """The whole point. A script delivered into the clone each time is a script
    at a new path each time."""
    assert SCRIPT.exists(), f"{SCRIPT.relative_to(ROOT)} is gone"
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch",
                              str(SCRIPT.relative_to(ROOT))],
                             capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    assert tracked.returncode == 0, (
        "the apply script is not tracked by git, so it is not in a clone that "
        "fetches — which is the whole defect this row is about")


def test_the_doc_names_the_path_the_script_actually_lives_at():
    """The two cannot drift: an instruction pointing at a path that does not
    exist is exactly the failure being fixed."""
    doc = _flat(DOC)
    assert ".pantheon/apply-release.sh" in doc
    assert "push-tip" not in doc, "the doc still mentions the old bundle ref"
    # `.pantheon-transfer/` IS in the doc, once, inside the quoted failure it
    # was written against — which is the point of quoting it. What must not
    # happen is it appearing as something to run. The first draft of this case
    # forbade the string outright and failed on the doc's own evidence.
    raw = DOC.read_text(encoding="utf-8")
    assert raw.count(".pantheon-transfer/") == 2, (
        "the stale path appears somewhere other than the quoted error")
    quoted = raw[raw.index("```\nPS C:"):raw.index("```", raw.index("```\nPS C:") + 3)]
    assert quoted.count(".pantheon-transfer/") == 2, (
        "the stale path has escaped the quoted error and reads as an instruction")


def test_the_doc_leads_with_a_form_that_needs_no_script():
    """The committed script cannot help with the delivery that installs it, so
    a procedure that only existed as a script would keep the hole."""
    doc = _flat(DOC)
    two_commands = doc.index("git fetch")
    script_form = doc.index("apply-release.sh ~/Downloads")
    assert two_commands < script_form, (
        "the doc reaches for the script before giving the form that always "
        "works")
    assert "--ff-only" in doc, "the doc never says what makes it safe"
    assert "cannot help with the delivery that installs it" in doc, (
        "the doc does not explain why the script is not the primary answer")


def test_the_script_parses_and_refuses_the_three_things_it_must():
    source = SCRIPT.read_text(encoding="utf-8")
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True,
                          timeout=60).returncode == 0, "the script does not parse"
    assert "set -euo pipefail" in source, "the script continues past its own errors"
    # A fast-forward or nothing: never a rewrite of the owner's history.
    assert "--ff-only" in source
    assert "git reset --hard" not in source and "push --force" not in source, (
        "the script can destroy local work")
    # Tracked changes only. Three earlier versions blocked on their own bundle,
    # on themselves, and on a leftover transfer folder — none of it at risk.
    assert "--untracked-files=no" in source, (
        "the dirty guard counts untracked files again, so the script refuses "
        "to run because of the bundle sitting beside it")
    # The bundle's own ref is checked by running the script, not by looking
    # for `list-heads` in the source — see the case below. A mutation that
    # hard-coded `refs/heads/main` left the string in place (it is used twice)
    # and walked straight past the grep.


def test_the_script_says_what_to_do_when_there_is_no_bundle():
    """The commonest case is that no bundle is needed at all, because a session
    with a live bridge fast-forwards the clone itself. A script that answered
    only "file not found" would send a reader looking for a file that was never
    meant to exist."""
    source = SCRIPT.read_text(encoding="utf-8")
    missing = source[source.index('if [ ! -f "$BUNDLE" ]'):]
    # A line that IS `fi`, not the first two letters of "first argument" —
    # which is where the first draft of this case cut the message in half and
    # then reported it incomplete.
    missing = missing[:missing.index("\nfi")]
    assert "git push origin main" in missing, (
        "the no-bundle message does not mention the step that is usually all "
        "that is left")
    assert "git log --oneline -1" in missing, (
        "the no-bundle message does not say how to check whether the work is "
        "already here")


def test_the_pull_policy_trap_is_written_down_in_both_places():
    """`pull_policy: always` fires only at container CREATION, so `up -d` on a
    running container does not re-pull. That is how a server sat on a two-week
    old build with every link above it green, and it is the one step of the
    chain that looks done when it is not."""
    for path in (SCRIPT, DOC):
        text = _flat(path)
        assert "docker compose pull" in text, f"{path.name} omits the pull"
        # `CREAT` covers both: the doc reads "when a container is CREATED" and
        # the script prints "at container CREATION". Matching the substance
        # rather than one spelling, because the alternative is a test that
        # dictates prose to keep its own regex happy.
        assert re.search(r"container is CREAT|at container CREAT", text), (
            f"{path.name} does not say why the explicit pull is needed")


def test_the_doc_records_why_the_session_cannot_push():
    """Measured, not asserted: the git proxy refuses every repository, public
    ones included, so it is a session with no GitHub source attached rather
    than a missing whitelist entry — and the reflog shows no push has ever
    succeeded."""
    doc = DOC.read_text(encoding="utf-8")
    assert "403" in doc
    assert "every" in doc and "public" in doc, (
        "the doc reads as though one repository needs whitelisting")
    assert re.search(r"zero push entries|no push", doc), (
        "the doc does not record that pushing has never worked from a session")


def test_the_script_reads_the_bundle_s_own_ref_rather_than_assuming_one(tmp_path):
    """Driven, because this exact bug shipped once and a grep cannot see it.

    An earlier version hard-coded the bundle ref as `push-tip` while the
    bundles being produced carried `refs/heads/main`, so it would have reported
    *"adds nothing new"* over sixteen real commits — a silent no-op on a
    delivery, which is the worst available failure for a script whose whole job
    is to move a clone forward.

    So a bundle is built here under a ref name that is **not** `main`, and the
    script has to apply it anyway. A source-text assertion could not catch
    this: the mutation that reintroduced the bug left `git bundle list-heads`
    in the file, because the script calls it twice.
    """
    def git(*args, cwd, **kw):
        run = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                             text=True, timeout=60, **kw)
        assert run.returncode == 0, run.stdout + run.stderr
        return run.stdout.strip()

    # A two-commit repository with no history in common with this one, so the
    # case is about the script and nothing else.
    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-q", "-b", "main", cwd=origin)
    git("config", "user.email", "t@example.invalid", cwd=origin)
    git("config", "user.name", "t", cwd=origin)
    (origin / "a.txt").write_text("one\n", encoding="utf-8")
    git("add", "a.txt", cwd=origin)
    git("commit", "-qm", "one", cwd=origin)
    first = git("rev-parse", "HEAD", cwd=origin)
    (origin / "a.txt").write_text("two\n", encoding="utf-8")
    git("commit", "-qam", "two", cwd=origin)
    second = git("rev-parse", "HEAD", cwd=origin)

    # The bundle carries `refs/heads/delivery`, deliberately not `main`.
    bundle = tmp_path / "odd.bundle"
    git("branch", "delivery", cwd=origin)
    git("bundle", "create", str(bundle), f"{first}..delivery", cwd=origin)
    assert "refs/heads/delivery" in git("bundle", "list-heads", str(bundle), cwd=origin)

    clone = tmp_path / "clone"
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    git("reset", "-q", "--hard", first, cwd=clone)
    (clone / ".pantheon").mkdir(exist_ok=True)
    (clone / ".pantheon" / "apply-release.sh").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")

    run = subprocess.run(["bash", ".pantheon/apply-release.sh", str(bundle)],
                         cwd=str(clone), capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert git("rev-parse", "HEAD", cwd=clone) == second, (
        "the script did not fast-forward a bundle whose ref is not `main` — "
        "it is assuming the ref name again:\n" + run.stdout)
    # And it tidied up after itself, so a later run cannot apply a stale bundle.
    assert not bundle.exists(), "the spent bundle was left behind"


def test_the_doc_does_not_recommend_typing_into_a_terminal():
    """A correction, and the reason it is a case rather than an edit.

    This page's first answer was *"turn computer use on so the session runs
    `git push` in your own PowerShell"*. It is wrong, and wrong in a way no
    amount of re-reading would have caught — computer use grants terminals and
    IDEs in **click-only** mode by design (*"you can see and left-click, but
    cannot type, press keys, or paste"*), and PowerShell is masked out of
    screenshots besides. The advice was written into the repository before
    anybody had tried it.

    What works is a GUI client's Push **button**, because a click is allowed:
    measured on 2026-10-21, 26 commits through GitHub Desktop. So the case
    guards the shape of the mistake — a recommendation to type into a shell —
    rather than the sentence that happened to carry it.
    """
    doc = _flat(DOC)
    lowered = doc.lower()
    assert "click-only" in lowered, (
        "the doc does not record that terminals cannot be typed into")
    for wrong in ("runs `git push` in your own powershell",
                  "run `git push` in your own powershell",
                  "types `git push`"):
        assert wrong not in lowered, (
            f"the doc recommends {wrong!r}, which computer use refuses")
    assert "github desktop" in lowered, (
        "the doc does not name the route that actually works")
    # Measured, with the commits it moved, so it reads as a thing that was done
    # rather than a thing that should work.
    assert "208f60d6" in doc, (
        "the doc claims the route works without saying when it was measured")


def _delivery(tmp_path):
    """An origin two commits ahead of a clone, the second commit adding a
    file, and the bundle that carries it. Returns `(git, clone, bundle, tip)`."""
    def git(*args, cwd):
        run = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                             text=True, timeout=60)
        assert run.returncode == 0, run.stdout + run.stderr
        return run.stdout.strip()

    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-q", "-b", "main", cwd=origin)
    git("config", "user.email", "t@example.invalid", cwd=origin)
    git("config", "user.name", "t", cwd=origin)
    (origin / "a.txt").write_text("one\n", encoding="utf-8")
    git("add", "a.txt", cwd=origin)
    git("commit", "-qm", "one", cwd=origin)
    first = git("rev-parse", "HEAD", cwd=origin)
    (origin / "tests").mkdir()
    (origin / "tests" / "test_new.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "tests/test_new.py", cwd=origin)
    git("commit", "-qm", "two", cwd=origin)
    tip = git("rev-parse", "HEAD", cwd=origin)
    bundle = tmp_path / "pantheon.bundle"
    git("bundle", "create", str(bundle), f"{first}..main", cwd=origin)

    clone = tmp_path / "clone"
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    git("config", "user.email", "t@example.invalid", cwd=clone)
    git("config", "user.name", "t", cwd=clone)
    git("reset", "-q", "--hard", first, cwd=clone)
    (clone / ".pantheon").mkdir(exist_ok=True)
    (clone / ".pantheon" / "apply-release.sh").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    return git, clone, bundle, tip


def _apply(clone, bundle):
    return subprocess.run(["bash", ".pantheon/apply-release.sh", str(bundle)],
                          cwd=str(clone), capture_output=True, text=True, timeout=120)


def test_a_real_divergence_is_named_with_the_commits_that_are_yours(tmp_path):
    """`B1411`, the first shape: the clone has a commit the bundle does not.
    The refusal says so and lists that commit — the one case where the old
    message was the truth."""
    git, clone, bundle, tip = _delivery(tmp_path)
    (clone / "mine.txt").write_text("local\n", encoding="utf-8")
    git("add", "mine.txt", cwd=clone)
    git("commit", "-qm", "a commit only this clone has", cwd=clone)
    run = _apply(clone, bundle)
    assert run.returncode == 1, run.stdout + run.stderr
    assert "not a fast-forward: your main has commits the bundle does not." in run.stderr
    assert "a commit only this clone has" in run.stderr, run.stderr
    assert "not a divergence" not in run.stderr
    assert git("rev-parse", "HEAD", cwd=clone) != tip
    assert bundle.exists(), "a refused bundle was deleted"


def test_an_untracked_file_in_the_bundles_path_is_named_and_is_not_a_divergence(tmp_path):
    """`B1411`, the shape that was hit on a real delivery: a previous run that
    died part-way left one of the bundle's new files behind, untracked. git
    refuses the fast-forward because it would overwrite it — and the script
    used to say *"your main has commits the bundle does not"* over an empty
    list. It now says it was not a divergence and names the path."""
    git, clone, bundle, tip = _delivery(tmp_path)
    (clone / "tests").mkdir()
    (clone / "tests" / "test_new.py").write_text("left by a dead run\n", encoding="utf-8")
    run = _apply(clone, bundle)
    assert run.returncode == 1, run.stdout + run.stderr
    assert "commits the bundle does not" not in run.stderr, run.stderr
    assert "These are yours alone" not in run.stderr, run.stderr
    assert "not applied, and not a divergence: your main has no commits the bundle lacks." in run.stderr
    assert "\n  tests/test_new.py\n" in run.stderr, run.stderr
    assert git("rev-parse", "HEAD", cwd=clone) != tip
    assert (clone / "tests" / "test_new.py").read_text(encoding="utf-8") == "left by a dead run\n"
    # With the path cleared, the same bundle applies.
    (clone / "tests" / "test_new.py").unlink()
    run = _apply(clone, bundle)
    assert run.returncode == 0, run.stdout + run.stderr
    assert git("rev-parse", "HEAD", cwd=clone) == tip
