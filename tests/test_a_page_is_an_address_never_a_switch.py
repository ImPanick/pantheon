# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1636` — a page a hire names reaches the browser as an address, never as
one of its switches.

Measured before the fix: Screenshot Reporter and Visual Regression handed each
page to Chromium as its last word, `chromium --headless … "$u"`, and
Accessibility Auditor handed it to `axe` and `pa11y` the same way. Chromium
reads any word that starts with `--` as a switch wherever it stands, and
`--renderer-cmd-prefix=<program>` runs that program for every page it draws —
so a page listed as `--renderer-cmd-prefix=…` ran a program on the workstation.
Quoting the page (`B1631`) keeps it one word; it does not stop that word being
a switch. Web Performance handed Lighthouse its page first and in double
quotes, so a `$(…)` in it ran as well.

Now `--` comes before every page: Chromium stops reading switches at `--`
(`base::CommandLine`'s switch terminator), and `axe`, `pa11y` and Lighthouse
read what follows `--` as an address, as their argument parsers (commander,
yargs) do. Visual Regression names its file with `printf %s`, which, unlike
`echo`, has no switches of its own to mistake a page for.

Driven (`Law 20`): with the real Chromium where this machine has one (the
browser the in-browser tests drive), each runbook's own command, filled as it
says, runs on a page named `--renderer-cmd-prefix=<a program that leaves a
mark>` and on a real page: the program never runs, the real page is captured.
The control — the page as the last word, as before — runs the program. `axe`,
`pa11y` and Lighthouse are not installed here, so each is a stand-in that
writes down what it was handed: `--`, then the page, whole.

The adversary (`Law 17`): low — only the person's own list reaches these
commands, and the person already runs commands on the workstation. The fix is
for a mistake, and for a list pasted from somewhere else.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from src.agents.catalogue import get_agent
from test_a_name_runs_nothing_on_the_far_side import _q, _runs_under_its_own_hire, _steps


def _real_chromium():
    for name in ("chromium", "chromium-browser", "google-chrome"):
        if shutil.which(name):
            return shutil.which(name)
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "", "/opt/pw-browsers",
             os.path.expanduser("~/.cache/ms-playwright")]
    for root in filter(None, roots):
        found = sorted(glob.glob(os.path.join(root, "chromium-*", "chrome-linux*", "chrome")))
        if found:
            return found[-1]
    return None


CHROMIUM = _real_chromium()


def _span(agent: str, needle: str) -> str:
    spans = [s for s in re.findall(r"`([^`]+)`", _steps(get_agent(None, agent).runbook)) if needle in s]
    assert len(spans) == 1, (agent, spans)
    return spans[0]


def _executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


#: Writes down each word it was handed, one a line.
RECORDER = '#!/bin/sh\nfor a in "$@"; do printf "%%s\\n" "$a"; done >> %s\n'


@pytest.fixture
def station(tmp_path):
    """The workstation's shell: a projects folder, a `bin` first on `PATH`,
    and a program that leaves a mark when something runs it."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    projects = tmp_path / "projects"
    (projects / "shots").mkdir(parents=True)
    mark = tmp_path / "mark.sh"
    _executable(mark, f'#!/bin/sh\ntouch {_q(str(tmp_path / "pwned"))}\nexec "$@"\n')
    env = dict(os.environ, PATH=f"{bin_}:/usr/local/bin:/usr/bin:/bin", PANTHEON_PROJECTS=str(projects),
               HOME=str(tmp_path))

    class S:
        root = tmp_path
        hostile = f"--renderer-cmd-prefix={mark}"

        @staticmethod
        def tool(name: str, text: str) -> None:
            _executable(bin_ / name, text)

        @staticmethod
        def record(name: str) -> None:
            _executable(bin_ / name, RECORDER % _q(str(tmp_path / f"{name}.args")))

        @staticmethod
        def handed(name: str):
            f = tmp_path / f"{name}.args"
            return f.read_text(encoding="utf-8").split("\n")[:-1] if f.exists() else []

        @staticmethod
        def run(command: str) -> str:
            done = subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True, timeout=180,
                                  cwd=str(tmp_path))
            return done.stdout + done.stderr

        @staticmethod
        def ran() -> bool:
            return (tmp_path / "pwned").exists()
    return S


# ── Chromium, for real ──────────────────────────────────────────────────────

needs_chromium = pytest.mark.skipif(CHROMIUM is None, reason="no Chromium on this machine")


def _with_chromium(station):
    """`chromium` on `PATH` is the real one; as root it needs `--no-sandbox`,
    put before everything the command hands it."""
    sandbox = " --no-sandbox" if os.geteuid() == 0 else ""
    station.tool("chromium", f'#!/bin/sh\nexec {_q(CHROMIUM)}{sandbox} "$@"\n')


def _real_page(station) -> str:
    page = station.root / "page.html"
    page.write_text('<html><body style="background:#c00"><h1>Sales</h1></body></html>', encoding="utf-8")
    return page.as_uri()


@needs_chromium
def test_chromium_reads_a_page_written_last_as_a_switch_and_runs_it(station):
    """The control: the page as the last word, as both runbooks had it."""
    _with_chromium(station)
    shot = station.root / "c.png"
    station.run(f"chromium --headless --hide-scrollbars --window-size=320,200 --screenshot={shot} "
                f"{_q(station.hostile)} >/dev/null 2>&1")
    assert station.ran()


@needs_chromium
def test_screenshot_reporter_captures_such_a_page_as_an_address(station):
    _with_chromium(station)
    if not shutil.which("img2pdf"):
        station.record("img2pdf")
    real = _real_page(station)
    span = _span("screenshot-reporter", "img2pdf")
    command = (span.replace("'<folder>'", _q("shots"))
               .replace("<the pages, each in single quotes>", " ".join(map(_q, [station.hostile, real]))))
    command = command.replace("--window-size=1280,2000", "--window-size=320,200")
    out = station.run(command)
    assert not station.ran(), out
    assert f"OK 2 {real}" in out, out
    assert f"OK 1 {station.hostile}" in out or f"FAILED {station.hostile}" in out, out
    assert _runs_under_its_own_hire("screenshot-reporter", command)


@needs_chromium
def test_visual_regression_captures_such_a_page_as_an_address(station):
    _with_chromium(station)
    real = _real_page(station)
    span = _span("visual-regression", "--screenshot=")
    command = (span.replace("'<folder>'", _q("shots")).replace("<last folder>", "2026-10-27")
               .replace("<the pages, each in single quotes>", " ".join(map(_q, [station.hostile, real]))))
    command = command.replace("--window-size=1280,2000", "--window-size=320,200")
    out = station.run(command)
    assert not station.ran(), out
    name = re.sub(r"[^A-Za-z0-9]", "_", real)
    assert f"SHOT {name}" in out, out
    assert list((station.root / "projects" / "shots").glob(f"*/{name}.png")), out
    assert _runs_under_its_own_hire("visual-regression", command)


# ── what each tool is handed ────────────────────────────────────────────────

PAGES = ["--renderer-cmd-prefix=touch pwned", "-x", "https://shop.example/?a=1&b=2"]


def _after_the_end_of_switches(handed, pages):
    """Each page arrives whole, right after a `--` of its own."""
    return all(handed[i] == "--" and handed[i + 1] == p for p in pages for i in [handed.index(p) - 1])


@pytest.mark.parametrize("agent,needle", [("screenshot-reporter", "img2pdf"), ("visual-regression", "--screenshot=")])
def test_each_page_follows_its_own_end_of_switches(station, agent, needle):
    """Without a Chromium here too: what the browser is handed."""
    station.record("chromium")
    station.record("img2pdf")
    command = (_span(agent, needle).replace("'<folder>'", _q("shots")).replace("<last folder>", "2026-10-27")
               .replace("<the pages, each in single quotes>", " ".join(map(_q, PAGES))))
    station.run(command)
    handed = station.handed("chromium")
    assert _after_the_end_of_switches(handed, PAGES), handed
    assert not (station.root / "pwned").exists()


@pytest.mark.parametrize("checker,before", [("axe", ["--exit"]), ("pa11y", [])])
def test_accessibility_auditor_hands_each_checker_the_page_after_its_switches(station, checker, before):
    station.record(checker)
    command = _span("accessibility-auditor", "NO CHECKER").replace(
        "<the pages, each in single quotes>", " ".join(map(_q, PAGES)))
    out = station.run(command)
    handed = station.handed(checker)
    assert handed == [w for p in PAGES for w in (*before, "--", p)], handed
    for p in PAGES:
        assert f"== {p}\n" in out
    assert _runs_under_its_own_hire("accessibility-auditor", command)


def test_web_performance_hands_lighthouse_the_page_after_its_switches(station):
    station.record("lighthouse")
    station.tool("jq", "#!/bin/sh\ncat\n")
    runbook = _steps(get_agent(None, "web-performance").runbook)
    first, each = re.findall(r"`([^`]+)`", runbook)[1:3]
    assert first == "command -v lighthouse jq || exit 3" and each.startswith("lighthouse "), (first, each)
    command = "; ".join([first] + [each.replace("'<page>'", _q(p)) for p in PAGES])
    station.run(command)
    handed = station.handed("lighthouse")
    assert _after_the_end_of_switches(handed, PAGES), handed
    assert handed[-1] == PAGES[-1] and handed.count("--") == len(PAGES)
    assert not (station.root / "pwned").exists()
    assert _runs_under_its_own_hire("web-performance", command)
