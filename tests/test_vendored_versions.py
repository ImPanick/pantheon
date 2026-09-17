# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B330` — the recorded version and the shipped bytes cannot disagree.

Before 2026-09-16 a vendored library's version lived in `CREDITS.md` prose and
nowhere a machine looked. `.pantheon/check-licences.py` checks attribution and
is deliberately silent about versions, because attribution does not change when
a library is upgraded. So the versions drifted for weeks and the only reason
anyone found out was that a person ran a research pass by hand — which found
`mammoth.js` eighteen releases behind, an `html2pdf.js` bundle carrying a jsPDF
with twelve open advisories, and a `node-qrcode` file that matched no published
artifact at any version and had no version recorded anywhere.

`.pantheon/check-vendored-versions.py` is the mechanism. These tests are what
keep it able to fail, because a checker that cannot fail is the same as no
checker — the lesson `tests/test_licence_alignment.py` was written for, applied
to the rule next door.

Each mutation below breaks exactly one thing in a temporary copy of the tree and
asserts the checker notices and says which file. Two of them (`NO VERSION`,
`UNPINNED`) are the ones that matter most: they are what makes it impossible to
add a file to `static/lib/` — or to swap one — without recording what it is.

**Evidence this fails on the tree as it stood before the change** (`Law 9`):
the checker did not exist, and the three things it now pins were all wrong.
`CREDITS.md` said highlight.js v11.9.0, mammoth.js v1.8.0 and html2pdf.js
v0.10.2; the node-qrcode row carried no version at all — the only row in the
table missing one. `test_every_vendored_file_has_a_recorded_version` fails
against that tree on the node-qrcode entry alone, and the three version strings
fail `test_credits_carries_every_recorded_version` as soon as the bytes move.
"""
import datetime
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / ".pantheon" / "check-vendored-versions.py"


def load(path=CHECKER):
    spec = importlib.util.spec_from_file_location(f"_cvv_{id(path)}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(repo=ROOT, *args):
    return subprocess.run(
        [sys.executable, str(repo / ".pantheon" / "check-vendored-versions.py"),
         "--quiet", *args],
        cwd=repo, capture_output=True, text=True,
    )


@pytest.fixture
def repo(tmp_path):
    """A copy of what the checker reads, as a git repo so `git ls-files` works.

    The real bytes, not stand-ins: this checker's whole subject is hashes, and a
    fixture of empty files would make every assertion below vacuous. That is the
    trap `tests/test_licence_alignment.py` documents in its own fixture, where
    empty stand-ins are correct because that checker only ever stats paths.
    """
    dst = tmp_path / "repo"
    dst.mkdir()
    for rel in ("CREDITS.md", "NOTICE", "README.md"):
        if (ROOT / rel).is_file():
            shutil.copy2(ROOT / rel, dst / rel)
    for rel in ("licenses", ".pantheon", "static/lib", "static/fonts",
                "static/icons"):
        src = ROOT / rel
        if src.is_dir():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst / rel)
    # `library/` is 286 directories of prose that check-licences.py only stats,
    # and this checker never looks at it at all.
    (dst / "library").mkdir(exist_ok=True)
    (dst / "library" / "README.md").write_text("stand-in\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=dst, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dst, check=True)
    return dst


# The fixture is per-test rather than shared. A shared copy would have to be
# restored after each mutation, and a restore that misses one file turns the
# next test's result into a report about the previous test — which is the
# failure this suite exists to prevent, one level up. Copying `static/lib/`
# costs about ten milliseconds.
clean = repo


def patch_file(repo, rel, old, new):
    """Rewrite one string inside a file in the fixture repo."""
    p = repo / rel
    text = p.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"anchor {old!r} appears {text.count(old)} times"
    p.write_text(text.replace(old, new), encoding="utf-8")


def patch_checker(repo, old, new):
    patch_file(repo, ".pantheon/check-vendored-versions.py", old, new)


# ── the baseline ───────────────────────────────────────────────────────────

def test_the_real_repo_passes():
    """Not the fixture — the actual tree, as CI sees it."""
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr


def test_clean_fixture_passes(clean):
    """Every mutation below is measured against this passing."""
    r = run(clean)
    assert r.returncode == 0, r.stdout + r.stderr


# ── rule 1: nothing under static/lib/ without a version ────────────────────

def test_a_vendored_file_with_no_version_record_fails(clean):
    """The rule that makes this persistent rather than a one-off.

    A new library arrives the way every vendored asset in this repository has
    arrived: as a byte-for-byte copy dropped into `static/` to remove a network
    call. `check-licences.py` rule 1 makes somebody write its licence down. This
    makes them write down *which release it is* and what it hashes to, and
    there is no way to add the file and skip that.
    """
    (clean / "static" / "lib" / "newthing.min.js").write_text(
        "// a library somebody vendored\n", encoding="utf-8")
    # The file has to be declared in the licence inventory, which is the list
    # both checkers share — that is the point of the join. Declaring it there
    # is all it takes for this checker to demand a version for it.
    patch_file(
        clean, ".pantheon/check-licences.py", "INVENTORY = [",
        'INVENTORY = [\n    Entry("newthing", ["static/lib/newthing.min.js"], '
        '"MIT",\n          None, None),')
    subprocess.run(["git", "add", "-A"], cwd=clean, check=True)
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "NO VERSION" in r.stdout and "newthing" in r.stdout, r.stdout


def test_a_record_naming_no_inventory_entry_fails(clean):
    """The other half of the join. Renaming an entry in `check-licences.py`
    without renaming it here leaves two lists that each look complete."""
    patch_checker(clean, '        "Mermaid", "mermaid", "11.17.2"',
                  '        "Mermaidd", "mermaid", "11.17.2"')
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "NO ENTRY" in r.stdout and "Mermaidd" in r.stdout, r.stdout


# ── rule 2: the bytes ──────────────────────────────────────────────────────

def test_a_replaced_file_fails(clean):
    """The claim in one line: swap a byte and this goes red.

    This is what a silent refresh looks like. `B45` is the precedent — the
    html2pdf bundle differed from upstream by one string for as long as the
    repository existed, and nothing could see it because nothing compared the
    file to anything.
    """
    target = clean / "static" / "lib" / "highlight.min.js"
    target.write_bytes(target.read_bytes() + b"\n// one more byte\n")
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "HASH" in r.stdout, r.stdout
    assert "static/lib/highlight.min.js" in r.stdout, r.stdout


def test_an_unpinned_file_inside_a_declared_entry_fails(clean):
    """A glob entry that grows a file nobody hashed. `static/lib/katex/fonts/`
    is twenty files behind one pattern; a twenty-first would otherwise ship
    with its bytes checked by nothing."""
    extra = clean / "static" / "lib" / "katex" / "fonts" / "KaTeX_Extra-Regular.woff2"
    extra.write_bytes(b"wOF2 not really a font")
    subprocess.run(["git", "add", "-A"], cwd=clean, check=True)
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "UNPINNED" in r.stdout and "KaTeX_Extra-Regular" in r.stdout, r.stdout


def test_a_hash_for_a_file_that_is_not_there_fails(clean):
    """The mirror image: a record that outlives its file. Without this, deleting
    a vendored file leaves a hash that passes forever because nothing checks it
    against anything."""
    patch_checker(
        clean,
        '        files={"static/lib/mermaid.min.js":',
        '        files={"static/lib/mermaid-gone.min.js":',
    )
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "GHOST" in r.stdout and "mermaid-gone" in r.stdout, r.stdout


# ── rule 3: the two entries that delegate ──────────────────────────────────

def test_a_manifest_that_disagrees_about_the_version_fails(clean):
    """Pyodide and Swagger UI keep their hashes in the `MANIFEST.json` their own
    fetch scripts write, and this checker reads those rather than copying them
    (`Law 14`). That only works if the two records cannot drift apart, so the
    manifest's own `version` has to match."""
    man = clean / "static" / "lib" / "swagger-ui" / "MANIFEST.json"
    data = json.loads(man.read_text(encoding="utf-8"))
    data["version"] = "5.99.0"
    man.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "VERSION SPLIT" in r.stdout and "Swagger UI" in r.stdout, r.stdout


def test_an_emptied_manifest_fails_rather_than_checking_nothing(clean):
    """A delegated record whose manifest lists no files would check zero hashes
    and report success. A silently empty expectation is how a licence check
    once went green over nothing (`P0-21b`); the same trap is one level up
    here."""
    man = clean / "static" / "lib" / "pyodide" / "MANIFEST.json"
    data = json.loads(man.read_text(encoding="utf-8"))
    data["files"] = {}
    man.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "EMPTY MANIFEST" in r.stdout, r.stdout


# ── rule 4: the prose is driven off the record ─────────────────────────────

def test_credits_that_does_not_carry_the_recorded_version_fails(clean):
    """The original defect, stated as a rule. `CREDITS.md` is where a reader
    looks up what version is shipped; a version there that nothing checks is
    the version that drifts, and it drifted for weeks."""
    credits = clean / "CREDITS.md"
    credits.write_text(
        credits.read_text(encoding="utf-8").replace("mammoth.js) v1.12.3",
                                                    "mammoth.js) v1.8.0"),
        encoding="utf-8")
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "UNVERSIONED" in r.stdout and "mammoth.js" in r.stdout, r.stdout


def test_every_vendored_file_has_a_recorded_version():
    """Against the real tree, not the fixture: every file git tracks under
    `static/lib/` is covered by a record with a version and a hash.

    This is the assertion that fails on the tree as it stood before 2026-09-16.
    `node-qrcode` was the only row in the CREDITS.md table with no version, and
    it had none because the file could not be identified — it matched no
    published artifact at any version from 0.0.1 to 1.5.4. It has one now
    because the build that produces it was found and recorded (`B337`).
    """
    mod = load()
    lic = mod._load_licences()
    by_name = {e.name: e for e in lic.INVENTORY}
    records = {r.entry: r for r in mod.VENDORED}
    uncovered = []
    for path in mod.tracked_lib_files():
        owners = [e.name for e in lic.INVENTORY if e.matches(path)]
        assert owners, f"{path} is declared by no INVENTORY entry"
        if not any(name in records for name in owners):
            uncovered.append(path)
    assert not uncovered, uncovered
    for name, rec in records.items():
        assert name in by_name, name
        assert rec.version and rec.version[0].isdigit(), (name, rec.version)
        assert rec.source.startswith("https://"), (name, rec.source)
        assert rec.files or rec.manifest, name


def test_credits_carries_every_recorded_version():
    """Against the real tree. Stated separately from the fixture mutation so
    that the claim about *this* repository is a test somebody can point at."""
    mod = load()
    assert mod.check() == []


# ── rule 5: the bookkeeping ────────────────────────────────────────────────

def test_a_checked_date_that_is_not_a_date_fails(clean):
    patch_checker(clean, '"11.12.0", "2026-09-16"', '"11.12.0", "last tuesday"')
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "BAD DATE" in r.stdout, r.stdout


def test_a_checked_date_in_the_future_fails(clean):
    soon = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    patch_checker(clean, '"11.12.0", "2026-09-16"', f'"11.12.0", "{soon}"')
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "FUTURE" in r.stdout, r.stdout


def test_staleness_is_opt_in_and_works_when_asked(clean):
    """`checked` is not a ratchet by default: failing the offline gate because a
    calendar day passed reddens CI on a repository nobody changed, and a gate
    that is always red is a gate nobody reads (`P3-20`). `--max-age-days` is
    there for whoever wants the ratchet, and the freshness workflow is what
    actually goes red when a newer release exists."""
    patch_checker(clean, '"11.12.0", "2026-09-16"', '"11.12.0", "2024-01-02"')
    assert run(clean).returncode == 0, "a stale date is not a gate by default"
    assert run(clean, "--max-age-days", "36500").returncode == 0
    r = run(clean, "--max-age-days", "30")
    assert r.returncode == 1, r.stdout
    assert "STALE" in r.stdout and "highlight.js" in r.stdout, r.stdout


# ── the record is usable by the thing that needs the network ───────────────

def test_the_json_the_freshness_workflow_reads_is_complete():
    """`.github/workflows/vendored-freshness.yml` asks npm and OSV about every
    record. It reads `--json`, so a field that stopped being emitted would make
    the workflow quietly ask about fewer libraries — and a freshness check that
    silently narrows is worse than none, because the green tick still appears.
    """
    out = subprocess.run(
        [sys.executable, str(CHECKER), "--json"],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout
    records = json.loads(out)
    mod = load()
    assert len(records) == len(mod.VENDORED)
    for rec in records:
        for field in ("entry", "package", "registry", "version", "checked",
                      "source", "behind_ok", "osv_known"):
            assert field in rec, (rec.get("entry"), field)
        assert rec["registry"] in {"npm", "sheetjs"}, rec

    workflow = (ROOT / ".github" / "workflows" / "vendored-freshness.yml").read_text(
        encoding="utf-8")
    # The workflow must not be the thing that decides a library is exempt; the
    # record is, next to the version it excuses.
    assert 'rec["behind_ok"]' in workflow
    assert 'rec["osv_known"]' in workflow


def test_the_offline_checker_never_reaches_the_network():
    """`Law 16` as a test rather than a promise. Developers run
    `release-gate.py --fast` offline and constantly; a checker that resolved a
    registry would make the local gate depend on somebody else's uptime, and it
    would do it intermittently, which is the worst way to find out."""
    # Comments and strings are dropped with the stdlib tokenizer rather than by
    # grepping raw source: this file *talks* about npm, OSV and URLs at length,
    # and reading an explanation as the thing it explains is a defect this
    # repository has now shipped three times (`B87`, `B58`, `B290`). What is
    # left is code — names and keywords — which is where an import lives.
    import io
    import tokenize

    with open(CHECKER, "rb") as fh:
        tokens = list(tokenize.tokenize(fh.readline))
    code = " ".join(
        tok.string for tok in tokens
        if tok.type not in (tokenize.COMMENT, tokenize.STRING, tokenize.NL,
                            tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)
    )
    assert "hashlib" in code, "the tokenizer returned nothing usable"
    for forbidden in ("urllib", "requests", "httpx", "socket", "urlopen",
                      "http", "ssl"):
        assert forbidden not in code.split(), (
            f"{forbidden!r} is a name in the offline checker's code — the "
            "network half belongs in "
            ".github/workflows/vendored-freshness.yml"
        )

    # And the shipped application never learns about any of this: nothing under
    # src/, routes/ or services/ imports the checker or reads its record.
    hits = subprocess.run(
        ["git", "grep", "-l", "check-vendored-versions", "--",
         "src/", "routes/", "services/", "static/", "app.py"],
        cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert not hits, hits


# ── rule 6: what a bundle carries INSIDE it (B336) ─────────────────────────
#
# A vendored bundle is one npm coordinate to a scanner and a dozen to an
# attacker. `html2pdf.js` 0.14.0 has zero advisories of its own and ships jsPDF
# 4.0.0 with nine — one CRITICAL — and DOMPurify 3.3.1 with eighteen. Until
# 2026-09-17 that lived in a roadmap row and in `CREDITS.md` prose, and nothing
# compared either to the file. `B336`'s decision is to stay on the published
# artifact, which is only defensible if the waiting is checked rather than
# remembered.

def test_the_recorded_inner_versions_are_in_the_shipped_bytes():
    """The real tree. `M.version="4.0.0"` is jsPDF's own version literal in the
    blob and `@license DOMPurify 3.3.1` is in the extracted sidecar, so both
    numbers are read out of the artifact rather than asserted about it."""
    mod = load()
    recorded = {r.entry: r for r in mod.VENDORED}
    html2pdf = recorded["html2pdf.js"]
    inner = {i.package: i for i in html2pdf.contains}
    assert set(inner) == {"jspdf", "dompurify", "html2canvas"}, sorted(inner)
    assert inner["jspdf"].version == "4.0.0"
    assert inner["dompurify"].version == "3.3.1"
    bundle = (ROOT / "static" / "lib" / "html2pdf.bundle.min.js").read_bytes()
    assert inner["jspdf"].witness.encode() in bundle, inner["jspdf"].witness
    sidecar = (ROOT / "licenses"
               / "html2pdf.bundle.min.js.LICENSE.txt").read_bytes()
    assert inner["dompurify"].witness.encode() in sidecar


def test_every_inner_advisory_has_a_reason_written_beside_its_version():
    """The excuses are per advisory id and live beside the version they excuse,
    so a bump orphans them and somebody has to look again — `B333`'s pattern,
    applied to the twenty-seven advisories inside this bundle."""
    mod = load()
    inner = {i.package: i
             for r in mod.VENDORED for i in r.contains}
    assert len(inner["jspdf"].osv_known) == 9, sorted(inner["jspdf"].osv_known)
    assert len(inner["dompurify"].osv_known) == 18, len(inner["dompurify"].osv_known)
    # The CRITICAL one is named, not lumped in.
    assert "GHSA-wfv2-pwc8-crg5" in inner["jspdf"].osv_known
    for why in inner["jspdf"].osv_known.values():
        assert len(why) > 40, why
    assert not inner["html2canvas"].osv_known, (
        "html2canvas is current and has nothing to excuse")


def test_a_bundle_carrying_a_different_inner_version_fails(clean):
    """The claim in one line. Swap the bundle for one carrying a different jsPDF
    and this goes red — which matters because the record does not merely say
    `4.0.0`, it carries nine advisory excuses written *for* 4.0.0, and an excuse
    written for one version is not an excuse for another."""
    target = clean / "static" / "lib" / "html2pdf.bundle.min.js"
    blob = target.read_bytes()
    target.write_bytes(blob.replace(b'M.version="4.0.0"', b'M.version="4.2.1"'))
    r = run(clean)
    assert r.returncode == 1, r.stdout
    # The hash moves too; the point is that the inner version is named.
    assert "INNER" in r.stdout, r.stdout
    assert "jspdf" in r.stdout and "4.0.0" in r.stdout, r.stdout


def test_an_inner_witness_whose_file_is_gone_fails(clean):
    """A witness that names a file nobody ships would check nothing. An empty
    expectation going green is the trap `EMPTY MANIFEST` exists for, one level
    in."""
    patch_checker(
        clean,
        '"dompurify", "3.3.1", "@license DOMPurify 3.3.1",\n'
        '                where="licenses/html2pdf.bundle.min.js.LICENSE.txt",',
        '"dompurify", "3.3.1", "@license DOMPurify 3.3.1",\n'
        '                where="licenses/not-a-file.txt",')
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "NO WITNESS" in r.stdout, r.stdout


def test_the_freshness_workflow_is_handed_the_inner_packages():
    """`Law 16` splits the question: this checker reads the tree, the workflow
    asks upstream. The workflow can only ask about what `--json` hands it, so a
    `contains` that stopped being exported would silently stop twenty-seven
    advisories being counted every week."""
    r = subprocess.run(
        [sys.executable, str(CHECKER), "--json"],
        cwd=ROOT, capture_output=True, text=True, check=True)
    records = {rec["entry"]: rec for rec in json.loads(r.stdout)}
    inner = {i["package"]: i for i in records["html2pdf.js"]["contains"]}
    assert set(inner) == {"jspdf", "dompurify", "html2canvas"}, sorted(inner)
    assert inner["jspdf"]["version"] == "4.0.0"
    assert inner["jspdf"]["behind_ok"], "being behind here needs a row that owns it"
    assert len(inner["dompurify"]["osv_known"]) == 18

    workflow = (ROOT / ".github" / "workflows"
                / "vendored-freshness.yml").read_text(encoding="utf-8")
    assert 'rec.get("contains"' in workflow, (
        "the workflow no longer asks OSV about the packages inside a bundle")


def test_a_version_line_names_which_dist_tag_to_compare_against():
    """`B335`'s Pyodide judgement, made machine-readable.

    npm's `pyodide` `dist-tags.latest` is 314.0.7 — a CPython-aligned line that
    0.27.x does not belong to — so comparing against `latest` reports a
    maintained runtime as permanently behind, for ever. A light that is always
    on is a light nobody reads, which is the whole design principle of the
    `behind_ok` field next door.
    """
    mod = load()
    records = {r.entry: r for r in mod.VENDORED}
    assert records["Pyodide"].dist_tag == "stable-0.27", records["Pyodide"].dist_tag
    assert records["Mermaid"].dist_tag == "latest"
    workflow = (ROOT / ".github" / "workflows"
                / "vendored-freshness.yml").read_text(encoding="utf-8")
    assert 'rec.get("dist_tag")' in workflow, (
        "the workflow still asks npm for `latest` whatever the record says")


# ── rule 7: a self-built artifact states its own inputs (B339) ─────────────

def test_a_build_command_with_no_input_record_fails(clean):
    """`B337` recorded *how* `qrcode.min.js` was built and `B339` is that the
    command alone is not provenance: `dijkstrajs` came in through that build and
    nothing in the repository said so. The two halves are now required
    together."""
    patch_checker(
        clean, '        "v11.17.2",',
        '        "v11.17.2",\n        build="esbuild mermaid --bundle",')
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "NO INPUTS" in r.stdout, r.stdout
    assert "mermaid.min.js" in r.stdout, r.stdout


def test_a_build_record_for_a_file_nobody_builds_fails(clean):
    """The other direction. A record left behind after a file went back to
    being fetched would otherwise declare packages for bytes that no longer
    contain them."""
    d = clean / ".pantheon" / "vendored-builds"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mermaid.json").write_text(json.dumps({
        "file": "static/lib/mermaid.min.js",
        "command": "esbuild mermaid --bundle",
        "packages": ["mermaid"],
    }), encoding="utf-8")
    r = run(clean)
    assert r.returncode == 1, r.stdout
    assert "ORPHAN BUILD" in r.stdout, r.stdout


# ── B338: qrcode.min.js is gone, and its paperwork is not ──────────────────

def test_the_unreferenced_qrcode_bundle_is_no_longer_shipped():
    """`B338`. Nothing in `static/` ever loaded this file: no `<script>` in
    `static/index.html`, no module import, not precached by `static/sw.js`. The
    2FA QR code a user sees is rasterised server-side by the Python
    `qrcode[pil]` package, so the `CREDITS.md` purpose column had never been
    true of these bytes.

    **Fails on the tree as it stood**: the file was tracked, and
    `.pantheon/check-vendored-versions.py` carried a `node-qrcode` record for
    it.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "static/lib/"], cwd=ROOT,
        capture_output=True, text=True, check=True).stdout.split()
    assert "static/lib/qrcode.min.js" not in tracked, tracked
    assert not (ROOT / "static" / "lib" / "qrcode.min.js").exists()
    mod = load()
    assert "node-qrcode" not in {r.entry for r in mod.VENDORED}, (
        "a fingerprint record for bytes this repository no longer serves")
    # And nothing in the served frontend went looking for it.
    hits = subprocess.run(
        ["git", "grep", "-l", "qrcode.min.js", "--", "static/", "app.py",
         "routes/", "src/"],
        cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert not hits, hits


def test_the_qrcode_attribution_survives_the_file():
    """`Law 1`, and `B334`'s precedent three entries up in the inventory: those
    bytes ship in every tag of this repository up to 2026-09-17, and deleting
    the notice for bytes somebody can still check out is how attribution rots
    backwards. The *fingerprint* goes because it hashes nothing; the *notice*
    stays because it is about what was distributed."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_cl_qr", ROOT / ".pantheon" / "check-licences.py")
    lic = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lic)
    by_name = {e.name: e for e in lic.INVENTORY}
    for name in ("node-qrcode", "dijkstrajs"):
        assert name in by_name, f"{name}'s attribution was deleted with the file"
        assert by_name[name].patterns == [], (
            f"{name} still claims a file pattern for bytes that are gone")
        assert (ROOT / "licenses" / by_name[name].text).is_file()
    credits = (ROOT / "CREDITS.md").read_text(encoding="utf-8")
    assert "licenses/node-qrcode-MIT-LICENSE.txt" in credits
    assert "licenses/dijkstrajs-MIT-LICENSE.txt" in credits
    assert "through 2026-09-17" in credits, (
        "CREDITS.md does not say which release was the last to carry the file")
