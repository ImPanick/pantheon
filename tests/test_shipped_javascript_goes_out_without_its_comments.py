# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1591` — Pantheon's own JavaScript goes out of the image without its comments.

The owner's call (`D-2026-10-29-02` §6): strip them at build time with a real
parser, keep every comment in the repository (`Law 1`), serve the stripped copy
from the image. Measured on this tree before it: 244 modules under `static/`
that are not `static/lib/`, 8,992 KB, of which 29,635 comments were 2,268 KB;
2,648 KB gzipped. After it, 6,660 KB and 1,674 KB gzipped, every module still
there (the module count stands, `D-2026-09-14-01`); in Chromium, a cold load's
own JavaScript on the wire went from 2,245 KB to 1,410 KB across the same 163
requests, and the whole load from 3,101 KB to 2,266 KB.

Now the `Dockerfile`'s `js-without-comments` stage runs
`scripts/strip-js-comments.mjs` (acorn 8.19.0, from `package-lock.json`) over
the build context and the app's stage copies what it wrote over `COPY . .`'s
modules, with a record of which git blob each was made from for
`scripts/pantheon-deploy`'s byte check.

There is no Docker daemon here, so the stage is driven **outside Docker**: its
instructions are read out of the `Dockerfile` and done in a temporary
directory — its `COPY`s placed, its last `RUN` executed as written with only
its two absolute paths moved into that directory. Its `apt-get` (node is on
PATH here) and its `npm ci` (the suite does not leave the machine, `B1520`)
are the two it does not run; this checks instead that the acorn on disk is the
one the lock names. Then, all driven: the stage's output is held token for
token to the source by acorn on its own (not the stripper's check), every
output passes `node --check`, the hard cases a pattern gets wrong are run in
`vm` before and after, the one module that ships a function's source text
builds a worker that still runs, the two server-side readers of shipped
modules read the stripped copy the same, the deploy's byte check passes the
image tree and still fails drift, and the real app serves the image tree with
the ETag of the file it serves.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_the_deploy_script_fails_when_the_deploy_failed import pd  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
ACORN = ROOT / "node_modules" / "acorn"
STRIPPER = ROOT / "scripts" / "strip-js-comments.mjs"
STAGE = "js-without-comments"

_SKIP = (None if NODE and (ACORN / "package.json").is_file() else
         "acorn is not installed here — `npm ci --omit=dev --ignore-scripts` installs it "
         "from package-lock.json, as the image's stage and CI's suite job do")
needs_acorn = pytest.mark.skipif(_SKIP is not None, reason=_SKIP or "")


# ── The Dockerfile, read as the builder reads it ────────────────────────────

def _instructions(text: str) -> list[str]:
    """Each instruction with its continuation lines joined; comments dropped
    (a `#` line inside a continuation is a comment too, as Docker reads it)."""
    out, buf = [], ""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.endswith("\\"):
            buf += s[:-1].strip() + " "
            continue
        out.append((buf + s).strip())
        buf = ""
    return out


def _stages() -> list[dict]:
    stages = []
    for ins in _instructions((ROOT / "Dockerfile").read_text(encoding="utf-8")):
        m = re.match(r"FROM\s+(\S+)(?:\s+AS\s+(\S+))?$", ins, re.I)
        if m:
            stages.append({"from": m.group(1), "name": m.group(2), "lines": []})
        else:
            stages[-1]["lines"].append(ins)
    return stages


def _stage(name):
    return next(s for s in _stages() if s["name"] == name)


def _lock() -> dict:
    return json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))


def _own_modules() -> list[str]:
    """What the release gate calls ours (`release-gate.py` `_js_files`, the one
    list `B436` left), under `static/`: what the browser is sent."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("b1591_gate", ROOT / ".pantheon" / "release-gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return sorted(f for f in gate._js_files() if f.startswith("static/"))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """The stage, done outside Docker, and the image's tree after it."""
    if _SKIP:
        pytest.skip(_SKIP)
    tmp = tmp_path_factory.mktemp("b1591")
    build, image = tmp / "build", tmp / "image"
    stage = _stage(STAGE)
    workdir, runs, skipped = None, [], []
    for ins in stage["lines"]:
        word, _, rest = ins.partition(" ")
        if word == "WORKDIR":
            workdir = rest.strip()
            build.mkdir()
        elif word == "COPY":
            *sources, dest = rest.split()
            for src in sources:
                source = ROOT / src.rstrip("/")
                if source.is_dir():          # `COPY dir/ dest/`: its contents, at dest
                    target = build / dest.rstrip("/")
                elif dest.endswith("/") or len(sources) > 1:
                    target = build / dest / source.name
                else:
                    target = build / dest
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():          # read, never written: the tree itself
                    target.symlink_to(source, target_is_directory=True)
                else:
                    shutil.copy2(source, target)
        elif word == "RUN":
            runs.append(rest)
    for cmd in runs:
        argv = shlex.split(cmd)
        if argv[:2] == ["apt-get", "update"]:
            skipped.append("apt")
        elif argv[:2] == ["npm", "ci"]:
            # What `npm ci` would put there: the acorn the lock names.
            (build / "node_modules").symlink_to(ROOT / "node_modules", target_is_directory=True)
            skipped.append("npm ci")
        else:
            moved = [str(build) if a == workdir else str(tmp / a.lstrip("/")) if a.startswith("/") else a
                     for a in argv]
            proc = subprocess.run(moved, cwd=build, capture_output=True, text=True, timeout=600)
            assert proc.returncode == 0, proc.stderr[-4000:]
            summary = proc.stdout
    out = tmp / "out"
    # The app's stage: `COPY . .` (the static tree is what matters here), then
    # the stage's output over it.
    (image / "static").mkdir(parents=True)
    for entry in (ROOT / "static").iterdir():
        dst = image / "static" / entry.name
        if entry.name in ("lib", "fonts", "icons"):
            dst.symlink_to(entry, target_is_directory=True)
        elif entry.is_dir():
            shutil.copytree(entry, dst)
        else:
            shutil.copy2(entry, dst)
    copy_from = [l for l in _stage(None)["lines"] if l.startswith(f"COPY --from={STAGE} ")]
    assert copy_from == [f"COPY --from={STAGE} /out/ ./"], copy_from
    shutil.copytree(out, image, dirs_exist_ok=True)
    record = json.loads((out / "js-without-comments.json").read_text(encoding="utf-8"))
    return {"tmp": tmp, "out": out, "image": image, "runs": runs, "skipped": skipped,
            "summary": summary, "record": record}


# ── The stage ───────────────────────────────────────────────────────────────

def test_the_stage_brings_no_new_image_and_installs_acorn_from_the_lock():
    stages = _stages()
    final = stages[-1]
    stage = _stage(STAGE)
    assert stages.index(stage) < len(stages) - 1, "the stage must come before the app's"
    assert stage["from"] == final["from"], (
        f"the stage runs on {stage['from']} and the app on {final['from']} — one more image "
        f"to trust and keep current")
    runs = [shlex.split(l[4:]) for l in stage["lines"] if l.startswith("RUN ")]
    npm = [r for r in runs if r[:2] == ["npm", "ci"]]
    assert len(npm) == 1 and "--omit=dev" in npm[0] and "--ignore-scripts" in npm[0], runs
    assert not any(r[:2] == ["npm", "install"] for r in runs), "npm install ignores the lock"
    assert runs[-1][:2] == ["node", "scripts/strip-js-comments.mjs"], runs[-1]
    # In the app's stage, after `COPY . .`, so it lands on the files it replaces.
    lines = final["lines"]
    assert lines.index("COPY . .") < lines.index(f"COPY --from={STAGE} /out/ ./")


def test_acorn_is_pinned_exactly_with_its_integrity():
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"] == {"acorn": "8.19.0"}, package.get("dependencies")
    entry = _lock()["packages"]["node_modules/acorn"]
    assert entry["version"] == "8.19.0" and not entry.get("dev")
    assert entry["resolved"] == "https://registry.npmjs.org/acorn/-/acorn-8.19.0.tgz"
    assert re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", entry["integrity"]), entry["integrity"]
    assert _lock()["packages"][""]["dependencies"] == package["dependencies"]


@needs_acorn
def test_the_acorn_on_disk_is_the_one_the_lock_names():
    """The stand-in for the stage's `npm ci` is only honest if it is."""
    installed = json.loads((ACORN / "package.json").read_text(encoding="utf-8"))
    assert installed["version"] == _lock()["packages"]["node_modules/acorn"]["version"]
    hidden = ROOT / "node_modules" / ".package-lock.json"
    if hidden.is_file():
        seen = json.loads(hidden.read_text(encoding="utf-8"))["packages"]["node_modules/acorn"]
        assert seen["integrity"] == _lock()["packages"]["node_modules/acorn"]["integrity"]


def test_the_stage_command_rewrites_every_module_that_is_ours_and_nothing_vendored(built):
    assert built["skipped"] == ["apt", "npm ci"], built["runs"]
    written = sorted(str(p.relative_to(built["out"])).replace(os.sep, "/")
                     for p in built["out"].rglob("*") if p.is_file() and p.suffix in (".js", ".mjs"))
    ours = _own_modules()
    assert len(ours) > 200 and written == ours
    assert not [p for p in written if p.startswith("static/lib/")]
    assert "static/sw.js" in written and "static/app.js" in written
    assert f"strip-js-comments: {len(ours)} modules" in built["summary"]


def test_the_record_names_the_blob_each_module_was_made_from_and_the_one_it_is(built, pd):  # noqa: F811
    listing = subprocess.run(["git", "ls-files", "-s", "static"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    git = {line.split("\t")[1]: line.split()[1] for line in listing.splitlines()}
    files = built["record"]["files"]
    assert sorted(files) == _own_modules()
    assert built["record"]["acorn"] == "8.19.0"
    for path, made in files.items():
        assert made["from"] == git[path], path
        assert made["to"] == pd.blob_id((built["out"] / path).read_bytes()), path
    assert sum(made["from"] != made["to"] for made in files.values()) == len(files)


# ── The same program, every module ─────────────────────────────────────────

_TOKENS = r"""
const { parse } = require(process.argv[2]);
const fs = require('fs');
const pairs = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
// What may be left: the SPDX line and the notices (src/static_representations.py's words).
const KEEP = /SPDX-License-Identifier|licen[cs]e|copyright|©|^\/\*!|@license|@preserve|source(?:Mapping)?URL=/i;
const BREAKS = /\r\n|[\n\r\u2028\u2029]/g;
function lex(code) {
  let last;
  for (const sourceType of ['module', 'script']) {
    try {
      const tokens = [], comments = [];
      parse(code, { ecmaVersion: 'latest', sourceType, locations: true, allowHashBang: true,
                    onToken: tokens, onComment: comments });
      return { sourceType, tokens, comments };
    } catch (e) { last = e; }
  }
  throw last;
}
const key = (t) => {
  let v = t.value;
  if (v && typeof v === 'object' && 'pattern' in v) v = '/' + v.pattern + '/' + v.flags;
  if (t.type.label === 'eof') return 'eof|' + t.loc.start.line;   // the end of input: its line
  return [t.type.label, typeof v, String(v), t.loc.start.line, t.loc.start.column,
          t.loc.end.line, t.loc.end.column].join('|');
};
const out = { problems: [], files: 0, before: 0, after: 0, tokens: 0 };
for (const [name, a, b] of pairs) {
  const src = fs.readFileSync(a, 'utf8'), dst = fs.readFileSync(b, 'utf8');
  const x = lex(src), y = lex(dst);
  out.files += 1; out.before += x.comments.length; out.after += y.comments.length;
  out.tokens += x.tokens.length;
  if (x.sourceType !== y.sourceType) out.problems.push(`${name}: goal ${x.sourceType} -> ${y.sourceType}`);
  const kx = x.tokens.map(key), ky = y.tokens.map(key);
  const i = kx.findIndex((k, n) => k !== ky[n]);
  if (kx.length !== ky.length || i >= 0) out.problems.push(`${name}: token ${i}: ${kx[i]} -> ${ky[i]}`);
  for (const c of y.comments) {
    const text = dst.slice(c.start, c.end);
    if (!KEEP.test(text)) out.problems.push(`${name}: a comment is left: ${text.slice(0, 80)}`);
  }
  if ((src.match(BREAKS) || []).length !== (dst.match(BREAKS) || []).length)
    out.problems.push(`${name}: the line count moved`);
}
console.log(JSON.stringify(out));
"""


def _node(script: str, *args, tmp: Path, name: str = "probe.cjs", timeout: int = 600) -> str:
    path = tmp / name
    path.write_text(script, encoding="utf-8")
    proc = subprocess.run([NODE, str(path), *map(str, args)], capture_output=True, text=True,
                          timeout=timeout, cwd=str(tmp))
    assert proc.returncode == 0, proc.stderr[-4000:]
    # `split`, not `splitlines`: JSON leaves U+2028 as it is, and a case holds one.
    return proc.stdout.strip().split("\n")[-1]


def test_every_module_is_the_same_token_stream_on_the_same_lines(built):
    """The row's proof, by acorn on its own and not by the stripper's check:
    every token of every module — type, value, line, column — is where it
    was, under the same goal; no comment is left but a notice; no line moved."""
    pairs = [[rel, str(ROOT / rel), str(built["out"] / rel)] for rel in _own_modules()]
    (built["tmp"] / "pairs.json").write_text(json.dumps(pairs))
    got = json.loads(_node(_TOKENS, ACORN / "dist" / "acorn.js", built["tmp"] / "pairs.json",
                           tmp=built["tmp"], name="tokens.cjs"))
    assert got["problems"] == [], got["problems"][:10]
    assert got["files"] == len(pairs) and got["tokens"] > 1_000_000
    assert got["before"] > 25_000 and got["after"] <= len(pairs) + 10, got


def test_every_module_passes_node_check(built):
    """As a module, the way the release gate checks the source (`B10`: piped,
    `--input-type=module`); and a classic script — the service worker, the
    sandbox's runner, `cookbookSchedule.js` — compiles as a script too."""
    bad = []
    for rel in _own_modules():
        proc = subprocess.run([NODE, "--input-type=module", "--check"],
                              input=(built["out"] / rel).read_text(encoding="utf-8"),
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            bad.append((rel, proc.stderr.strip().splitlines()[-1:]))
    assert bad == []
    script = r"""
const vm = require('vm'), fs = require('fs');
const [root, out, list] = process.argv.slice(2);
const res = { scripts: [], bad: [] };
for (const rel of JSON.parse(fs.readFileSync(list, 'utf8'))) {
  try { new vm.Script(fs.readFileSync(root + '/' + rel, 'utf8')); } catch { continue; }
  res.scripts.push(rel);
  try { new vm.Script(fs.readFileSync(out + '/' + rel, 'utf8')); } catch (e) { res.bad.push(rel + ': ' + e.message); }
}
console.log(JSON.stringify(res));
"""
    (built["tmp"] / "list.json").write_text(json.dumps(_own_modules()))
    got = json.loads(_node(script, ROOT, built["out"], built["tmp"] / "list.json",
                           tmp=built["tmp"], name="scripts.cjs"))
    assert got["bad"] == []
    assert {"static/sw.js", "static/js/pythonSandbox.js", "static/js/cookbookSchedule.js"} <= set(got["scripts"])


# ── The cases a pattern gets wrong ──────────────────────────────────────────

_HARD = r"""
import vm from 'node:vm';
const { stripComments } = await import(process.argv[2]);
const LS = String.fromCharCode(0x2028);
const cases = {
  // A regular expression holding `//` and `/*` — a pattern reads a comment.
  regexSlashes: "var r = /\\/\\/ no/g, c = /[/*]+/; [r.source, c.exec('x/*y')[0]] // done",
  regexClass: "var k = /[//]/.test('/') /* a */ ; k",
  // Division, after a name, a bracket and a number — a pattern reads a regex.
  division: "var a = 10, b = 2, g = 5; var x = a / b / g; // c\nvar y = (a) / 2 /* z */ / 1; [x, y]",
  divideAComment: "var q=1/**/+/**/2, w = 6 /* not /regex/ */ / 3; [q, w]",
  // Template literals holding comment-like text, and a real comment inside `${}`.
  template: "var n = 1; `// not ${ /* real */ n + 1 } /* nor */ ${`//${'/*'}`}`",
  // `</script>` and comment-like text in strings.
  strings: "var s = '</script><!-- x -->' + \"http://h/*p*/\" // c\n; s",
  // A block comment holding a line break is a line terminator: ASI still applies.
  asi: "function f() { return /* the\n value */ 1 }\nf()",
  asiSeparator: "function g() { return /*" + LS + "*/ 2 }\ng()",
  asiLine: "var u = 1\n// c\n-1\nu",
  // Code after a comment on its line keeps its column.
  column: "var w = /* lead */ 5; w",
  // Kept whole.
  kept: "// SPDX-License-Identifier: AGPL-3.0-or-later\n/*! keep */\n/** @license MIT */\n"
      + "// Copyright 2020 Someone\nvar k2 = 3; k2\n//# sourceURL=kept.js",
};
const out = {};
for (const [name, src] of Object.entries(cases)) {
  const { code, removed, kept } = stripComments(src, name);
  out[name] = { code, removed, kept,
                before: String(JSON.stringify(vm.runInNewContext(src))),
                after: String(JSON.stringify(vm.runInNewContext(code))) };
}
const refusals = {};
for (const [name, src] of Object.entries({
  htmlComment: "var h = 1 <!-- x\nh",       // a comment as a script, code as a module
  broken: "let = ;",
})) {
  try { stripComments(src, name); refusals[name] = null; } catch (e) { refusals[name] = e.message; }
}
const hashbang = stripComments("#!/usr/bin/env node\n// gone\nvar z = 1;\n", 'hashbang').code;
console.log(JSON.stringify({ out, refusals, hashbang }));
"""


@needs_acorn
def test_the_cases_a_pattern_gets_wrong(tmp_path):
    from urllib.parse import quote
    got = json.loads(_node(_HARD, "file://" + quote(str(STRIPPER)), tmp=tmp_path, name="hard.mjs"))
    out = got["out"]
    for name, row in out.items():
        assert row["before"] == row["after"], (name, row)
    assert json.loads(out["regexSlashes"]["after"]) == ["\\/\\/ no", "/*"]
    assert out["regexSlashes"]["code"].startswith("var r = /\\/\\/ no/g, c = /[/*]+/;")
    assert "/* a */" not in out["regexClass"]["code"] and "/[//]/" in out["regexClass"]["code"]
    sp = lambda text: " " * len(text)  # noqa: E731 — a comment's share of its line, as spaces
    assert json.loads(out["division"]["after"]) == [1, 5]
    assert out["division"]["code"] == ("var a = 10, b = 2, g = 5; var x = a / b / g;\n"
                                       "var y = (a) / 2 " + sp("/* z */") + " / 1; [x, y]")
    assert json.loads(out["divideAComment"]["after"]) == [3, 2]
    assert out["divideAComment"]["code"] == ("var q=1" + sp("/**/") + "+" + sp("/**/") + "2, w = 6 "
                                             + sp("/* not /regex/ */") + " / 3; [q, w]")
    assert json.loads(out["template"]["after"]) == "// not 2 /* nor */ ///*"
    assert "real" not in out["template"]["code"]
    assert json.loads(out["strings"]["after"]) == "</script><!-- x -->http://h/*p*/"
    assert out["strings"]["code"].endswith("\"http://h/*p*/\"\n; s")
    # `return` then a line break: undefined, before and after.
    assert out["asi"]["before"] == out["asi"]["after"] == "undefined"
    assert out["asi"]["code"] == "function f() { return \n" + sp(" value */") + " 1 }\nf()"
    assert out["asiSeparator"]["before"] == out["asiSeparator"]["after"] == "undefined"
    assert out["asiLine"]["code"] == "var u = 1\n\n-1\nu"
    assert out["column"]["code"] == "var w = " + sp("/* lead */") + " 5; w"
    kept = out["kept"]["code"]
    assert kept.splitlines()[:4] == ["// SPDX-License-Identifier: AGPL-3.0-or-later", "/*! keep */",
                                     "/** @license MIT */", "// Copyright 2020 Someone"]
    assert kept.endswith("//# sourceURL=kept.js") and out["kept"]["removed"] == 0
    assert got["hashbang"] == "#!/usr/bin/env node\n\nvar z = 1;\n"
    # Refused with a sentence that says which file and what to do — never a guess.
    assert "different places" in got["refusals"]["htmlComment"]
    assert got["refusals"]["broken"].startswith("broken: acorn cannot parse it")


@needs_acorn
def test_a_module_it_cannot_prove_stops_the_build_and_says_which(tmp_path):
    app = tmp_path / "app"
    (app / "static" / "js").mkdir(parents=True)
    (app / "static" / "js" / "good.js").write_text("// fine\nexport const a = 1;\n")
    (app / "static" / "js" / "bad.js").write_text("// SPDX-License-Identifier: AGPL-3.0-or-later\nlet = ;\n")
    (app / "static" / "lib").mkdir()
    (app / "static" / "lib" / "vendored.js").write_text("// left alone\n")
    proc = subprocess.run([NODE, str(STRIPPER), str(app), str(tmp_path / "out")],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    assert "static/js/bad.js: acorn cannot parse it" in proc.stderr
    assert "the build stops here" in proc.stderr
    assert not (tmp_path / "out" / "js-without-comments.json").exists()
    # And never over the repository's own files.
    same = subprocess.run([NODE, str(STRIPPER), str(app), str(app)], capture_output=True, text=True, timeout=60)
    assert same.returncode == 2 and "repository's own files" in same.stderr


@needs_acorn
def test_the_notice_words_are_the_stylesheets(tmp_path):
    """One rule for which comment is a notice, in the two places that strip
    comments (`Law 7`): this and `src/static_representations.py`."""
    from urllib.parse import quote
    from src.static_representations import _NOTICE
    script = ("const m = await import(process.argv[2]);"
              "console.log(JSON.stringify([m.NOTICE.source, m.NOTICE.flags]));")
    source, flags = json.loads(_node(script, "file://" + quote(str(STRIPPER)), tmp=tmp_path, name="n.mjs"))
    assert source == _NOTICE.pattern and flags == "i" and _NOTICE.flags & re.I


# ── What reads a module's text ──────────────────────────────────────────────

_SANDBOX = r"""
const vm = require('vm'), fs = require('fs');
function worker(file) {
  let source = null;
  const posted = [];
  const ctx = {
    location: { href: 'http://127.0.0.1/static/python-sandbox.html' }, URL: class extends URL {},
    Blob: function (parts) { source = parts.join(''); },
    Worker: function () { return {}; },
    window: { parent: { postMessage: (m) => posted.push(m) }, addEventListener() {} },
    JSON,
  };
  ctx.URL.createObjectURL = () => 'blob:x';
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), ctx);
  // The worker as the browser would start it: Pyodide is not there.
  const sent = [];
  vm.runInNewContext(source, { self: { postMessage: (m) => sent.push(m) },
                               importScripts() { throw new Error('missing'); } });
  return { source, sent, posted };
}
const [a, b] = process.argv.slice(2);
console.log(JSON.stringify({ repo: worker(a), image: worker(b) }));
"""


def test_the_one_module_that_ships_a_functions_source_still_builds_a_working_worker(built):
    """`static/js/pythonSandbox.js` starts its Worker from
    `workerMain.toString()` — the one place a shipped module sends its own
    source text anywhere (searched with acorn: `.toString()` of a function,
    `String(fn)`, `fn + ''`, `${fn}`, `Function.prototype.toString`, `eval`,
    `new Function`). The stripped function is still a program, and the
    worker it makes says the same sentence when Pyodide is missing."""
    rel = "static/js/pythonSandbox.js"
    got = json.loads(_node(_SANDBOX, ROOT / rel, built["out"] / rel, tmp=built["tmp"], name="sandbox.cjs"))
    repo, image = got["repo"], got["image"]
    assert image["sent"] == repo["sent"] and image["posted"] == repo["posted"] == [{"type": "ready"}]
    assert image["sent"][0]["type"] == "failed"
    assert "Pyodide is not installed" in image["sent"][0]["error"]
    assert "Vendored, so this is a missing file" in repo["source"]
    assert "Vendored, so this is a missing file" not in image["source"]


def test_the_server_reads_the_stripped_tables_as_it_reads_the_source(built, monkeypatch):
    """Two server modules read a shipped module's text at runtime: the theme
    keys out of `theme.js` (`B21`) and the shell's glyphs out of `icons.js`
    (`B398`). In the image they read the stripped copy."""
    from src import shell_glyphs, theme_advanced_keys
    stripped = built["out"] / "static" / "js"
    assert theme_advanced_keys._parse_adv_keys((stripped / "theme.js").read_text(encoding="utf-8")) \
        == theme_advanced_keys._parse_adv_keys((ROOT / "static/js/theme.js").read_text(encoding="utf-8")) \
        == theme_advanced_keys.ADVANCED_KEYS
    assert len(theme_advanced_keys.ADVANCED_KEYS) > 10
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "{{chevron:" in page and "{{glyph:" in page
    drawn = {}
    for name, icons in (("repo", ROOT / "static/js/icons.js"), ("image", stripped / "icons.js")):
        monkeypatch.setattr(shell_glyphs, "ICONS_JS", str(icons))
        shell_glyphs._cache.clear()
        drawn[name] = shell_glyphs.render(page)
    shell_glyphs._cache.clear()
    drawable = re.compile(r"\{\{(?:chevron|glyph):[a-z-]+\}\}")
    assert len(drawable.findall(page)) > 10
    assert drawable.findall(drawn["image"]) == drawable.findall(drawn["repo"]) == []
    assert drawn["image"] == drawn["repo"]


# ── The deploy's byte check ────────────────────────────────────────────────

def test_the_deploys_byte_check_passes_the_image_and_still_catches_drift(built, pd, tmp_path):  # noqa: F811
    """`scripts/pantheon-deploy` holds every shipped file to git's blob
    (`B360`). Over the image's tree — the real index, the real probe — every
    module matches as the stripped copy of git's blob. Without the record, or
    with a module built from bytes that are not git's (`B362`'s CRLF copies),
    or changed after the build, it fails, as it should."""
    manifest = {p: w for p, w in pd.build_manifest().items() if p.startswith("static/")}
    image = built["image"]
    out = pd.compare_bytes(manifest, pd._probe_bytes(image, manifest))
    assert out["mismatched"] == [] and out["missing"] == []
    assert out["stripped"] == _own_modules()
    report = {"routes": [{"path": "/", "expected": [200], "status": 200, "ok": True}],
              "mcp": [{"module": m, "ok": True, "error": ""} for m in "abcd"],
              "tracebacks": [], "log_lines": 1, "bytes_compared": out}
    row = next(r for r in pd.verdict(report)["rows"] if r["name"] == "shipped bytes")
    assert row["ok"] and f"({len(_own_modules())} as served without comments, made from it)" in row["detail"]

    # No record: every rewritten module is drift.
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "static").symlink_to(image / "static", target_is_directory=True)
    assert len(pd.compare_bytes(manifest, pd._probe_bytes(bare, manifest))["mismatched"]) == len(_own_modules())

    # Built from CRLF copies: the record names a `from` git does not have.
    rel = "static/js/a11y.js"
    crlf = tmp_path / "crlf"
    (crlf / "static" / "js").mkdir(parents=True)
    (crlf / rel).write_bytes((ROOT / rel).read_bytes().replace(b"\n", b"\r\n"))
    subprocess.run([NODE, str(STRIPPER), str(crlf), str(crlf / "out")], check=True,
                   capture_output=True, timeout=60)
    (crlf / "out" / rel).replace(crlf / rel)
    (crlf / "out" / "js-without-comments.json").replace(crlf / "js-without-comments.json")
    one = {rel: manifest[rel]}
    assert pd.compare_bytes(one, pd._probe_bytes(crlf, one))["mismatched"]

    # Changed after the build: not the `to` the record says was written.
    tampered = tmp_path / "tampered"
    (tampered / "static" / "js").mkdir(parents=True)
    shutil.copy2(image / "js-without-comments.json", tampered / "js-without-comments.json")
    (tampered / rel).write_bytes((image / rel).read_bytes() + b"\n")
    assert pd.compare_bytes(one, pd._probe_bytes(tampered, one))["mismatched"]


# ── Served ──────────────────────────────────────────────────────────────────

_SERVE = r'''
import hashlib, json, os, sys
image_static, repo_static, modules = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
import src.constants as constants
constants.STATIC_DIR = image_static          # the image's /app/static
import app as app_module
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.routing import Mount
from starlette.responses import FileResponse
from src import static_representations as kept

GZ = {"Accept-Encoding": "gzip, deflate, br"}
clients = {
    "image": (TestClient(app_module.app), image_static),
    # The repository's tree behind the same mount and middleware app.py gives it.
    "repo": (TestClient(Starlette(
        routes=[Mount("/static", app=app_module._RevalidatingStatic(directory=repo_static))],
        middleware=[Middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)])), repo_static),
}
res = {}
for name, (client, root) in clients.items():
    kept.forget()
    cold = {rel: client.get("/static/" + rel, headers=GZ) for rel in modules}   # every one a miss
    kept.settle(300)
    rows = {}
    for rel in modules:
        r = client.get("/static/" + rel, headers=GZ)
        path = os.path.join(root, rel)
        etag = FileResponse(path, stat_result=os.stat(path)).headers["etag"]
        rows[rel] = {"status": r.status_code, "encoding": r.headers.get("content-encoding"),
                     "is_file": r.content == open(path, "rb").read(),
                     "etag": r.headers.get("etag"), "file_etag": etag,
                     "cold_etag": cold[rel].headers.get("etag"),
                     "cold_wire": cold[rel].num_bytes_downloaded, "wire": r.num_bytes_downloaded}
    res[name] = rows
print("RESULT=" + json.dumps(res))
'''


def test_the_app_serves_the_image_tree_under_the_etag_of_the_file_it_serves(built):
    """`B1227`'s drive on the image's tree: every module, cold (each a miss,
    gzipped per request) and then as prepared, is the stripped file's bytes
    under the ETag that file's own stat gives — so a browser's cached copy
    of the commented file is a miss, never a stale hit. `?v=` is written by
    hand in each import (`check-specifiers.py`), not derived from content,
    so it has nothing to read. And the JavaScript on the wire is measured."""
    modules = [rel[len("static/"):] for rel in _own_modules()]
    env = dict(os.environ, PYTHONPATH=str(ROOT), PANTHEON_DISABLE_MCP="1", PYTHON_DOTENV_DISABLED="1",
               CHROMADB_HOST="127.0.0.1", CHROMADB_PORT="9", CHROMADB_CONNECT_TIMEOUT="0.01",
               PANTHEON_DATA_DIR=str(built["tmp"]), DATABASE_URL=f"sqlite:///{built['tmp'] / 'app.db'}")
    proc = subprocess.run([sys.executable, "-c", _SERVE, str(built["image"] / "static"),
                           str(ROOT / "static"), json.dumps(modules)],
                          cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stderr[-4000:]
    res = json.loads(next(l for l in proc.stdout.splitlines() if l.startswith("RESULT="))[7:])
    for name in ("image", "repo"):
        for rel, row in res[name].items():
            assert row["status"] == 200 and row["is_file"], (name, rel, row)
            assert row["etag"] == row["cold_etag"] == row["file_etag"], (name, rel, row)
    for rel in modules:
        assert res["image"][rel]["etag"] != res["repo"][rel]["etag"], rel
    wire = {name: sum(r["wire"] for r in rows.values()) for name, rows in res.items()}
    cold = {name: sum(r["cold_wire"] for r in rows.values()) for name, rows in res.items()}
    print(f"B1591 JavaScript on the wire, {len(modules)} modules: repo {wire['repo']:,} B "
          f"(cold {cold['repo']:,}), image {wire['image']:,} B (cold {cold['image']:,})")
    assert wire["image"] < 0.7 * wire["repo"], wire
    assert cold["image"] < 0.7 * cold["repo"], cold
