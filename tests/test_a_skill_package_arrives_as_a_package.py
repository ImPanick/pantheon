# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-49` … `P8-52`, `B928`. A package of skills arrives as a package.

The owner, 2026-09-30: *"adding a multi-layer skill package also does not build
its segmented 'category' and group skills together... Which it should.
Honestly we need to revamp the 'Skills' entirely... These should be groupable -
either assembled as a preset package ... - or custom grouped as well. Groups
that have skills that may overlap, should these be duplicated? Or
cross-referenced?"* He chose (`D-2026-09-30-01`): a skill is stored once and
groups reference it, with Fork for a deliberate copy; importing a repository
imports the whole package, even when `--skill` names one; a group organises,
filters, and switches its skills on and off as a set.

The line he pasted was
`npx skills add https://github.com/Leonxlnx/taste-skill --skill "design-taste-frontend"`,
and that skill lives in `skills/taste-skill/` — the name `--skill` takes is the
one SKILL.md gives itself, not its folder's. That is `B928`.

Everything here drives the real importer against a fake GitHub that serves
repository archives built in the test, the real `SkillsManager` on a temporary
store, the real routes through an ASGI client, and the real agent loop's
message array.
"""

import asyncio
import io
import json
import tarfile
import time

import httpx
import pytest
from fastapi import FastAPI

import services.memory.skill_importer as si
from services.memory.skill_collections import SkillCollections
from services.memory.skill_importer import SkillImportError
from services.memory.skills import SkillsManager


def _md(name, desc=None, status=None):
    fm = ["---", f"name: {name}", f"description: {desc or 'Does ' + name + ' things.'}"]
    if status:
        fm.append(f"status: {status}")
    return "\n".join(fm + ["---", "", f"# {name}", "", "See notes.md.", ""])


def _tarball(files, *, root="repo-main", commit="c0ffee", extra=None):
    """A gzip'd tar shaped like GitHub's: one top folder, a pax commit header."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT,
                      pax_headers={"comment": commit}) as tar:
        for path, text in files.items():
            data = text.encode("utf-8") if isinstance(text, str) else text
            info = tarfile.TarInfo(f"{root}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra or ():
            tar.addfile(info, io.BytesIO(b"x" * info.size) if info.isfile() else None)
    return buf.getvalue()


TASTE = {
    ".claude-plugin/marketplace.json": json.dumps({
        "name": "taste-skill", "plugins": [{"name": "taste-skill", "source": "./"}]}),
    ".claude-plugin/plugin.json": json.dumps({
        "name": "taste-skill", "version": "1.0.0", "description": "Frontend design taste skills"}),
    "README.md": "# taste",
    "skills/taste-skill/SKILL.md": _md("design-taste-frontend"),
    "skills/taste-skill-v1/SKILL.md": _md("design-taste-frontend-v1"),
    "skills/brandkit/SKILL.md": _md("brandkit"),
    "skills/stitch-skill/SKILL.md": _md("stitch-design-taste"),
    "skills/stitch-skill/DESIGN.md": "design system notes",
    "skills/stitch-skill/logo.png": "\x89PNG not text we keep",
    "research/laziness/README.md": "not a skill",
}

MARKET = {
    ".claude-plugin/marketplace.json": json.dumps({
        "name": "agent-skills", "metadata": {"description": "Example skills", "version": "2.0.0"},
        "plugins": [
            {"name": "document-skills", "description": "Office files", "source": "./",
             "skills": ["./skills/pdf", "./skills/xlsx"]},
            {"name": "example-skills", "source": "./", "skills": ["./skills/frontend-design"]},
        ]}),
    "skills/pdf/SKILL.md": _md("pdf"),
    "skills/pdf/forms.md": "forms",
    "skills/pdf/scripts/fill.py": "print('fill')",
    "skills/xlsx/SKILL.md": _md("xlsx"),
    "skills/frontend-design/SKILL.md": _md("frontend-design"),
    "template/SKILL.md": _md("template-skill"),
}


class _Resp:
    def __init__(self, url, status=200, body=b""):
        self.url = url
        self.status_code = status
        self.content = body
        self.headers = {}
        self.text = ""

    def json(self):
        return json.loads(self.content or b"null")


class _FakeCodeload:
    """Answers `_get_checked` with archives by `owner/repo/ref`; records calls."""

    def __init__(self, archives, raw=None, api=None):
        self.archives = dict(archives)
        self.raw = dict(raw or {})
        self.api = dict(api or {})
        self.asked = []
        self.max_bytes = []

    def __call__(self, url, *, headers=None, timeout=30.0, max_bytes=None):
        self.asked.append(url)
        self.max_bytes.append(max_bytes)
        pre = "https://codeload.github.com/"
        if url.startswith(pre):
            owner, repo, _tgz, ref = url[len(pre):].split("/", 3)
            key = f"{owner}/{repo}/{ref}"
            if key in self.archives:
                return _Resp(url, body=self.archives[key])
            return _Resp(url, status=404, body=b"404: Not Found")
        if url.startswith("https://raw.githubusercontent.com/"):
            key = url[len("https://raw.githubusercontent.com/"):]
            if key in self.raw:
                return _Resp(url, body=self.raw[key].encode())
            return _Resp(url, status=404, body=b"404: Not Found")
        if url in self.api:
            return _Resp(url, body=json.dumps(self.api[url]).encode())
        return _Resp(url, status=404, body=b'{"message": "Not Found"}')


@pytest.fixture
def github(monkeypatch):
    def install(archives=None, **kw):
        fake = _FakeCodeload(archives or {}, **kw)
        monkeypatch.setattr(si, "_get_checked", fake)
        return fake
    return install


@pytest.fixture
def store(tmp_path):
    return SkillsManager(str(tmp_path), library_root="")


TASTE_LINE = 'npx skills add https://github.com/Leonxlnx/taste-skill --skill "design-taste-frontend"'


# ── the package, as fetched ─────────────────────────────────────────────────

def test_the_owners_line_brings_the_whole_package_and_finds_the_named_skill(github):
    fake = github({"Leonxlnx/taste-skill/main": _tarball(TASTE, root="taste-skill-main")})
    pkg = si.fetch_skill_package(TASTE_LINE)
    names = sorted(s.name for s in pkg.skills)
    assert names == ["brandkit", "design-taste-frontend", "design-taste-frontend-v1",
                     "stitch-design-taste"]
    # `B928`: the named skill is found by the name its SKILL.md gives itself.
    assert pkg.named == "skills/taste-skill"
    assert pkg.id == "leonxlnx--taste-skill" and pkg.title == "taste-skill"
    assert pkg.version == "1.0.0" and pkg.commit == "c0ffee"
    stitch = next(s for s in pkg.skills if s.name == "stitch-design-taste")
    assert sorted(stitch.files) == ["DESIGN.md", "SKILL.md"], "an image is not a skill file"
    # One request for the whole package, with the archive cap on it.
    assert fake.asked == ["https://codeload.github.com/Leonxlnx/taste-skill/tar.gz/main"]
    assert fake.max_bytes == [si.MAX_ARCHIVE_BYTES]


def test_a_marketplace_declares_the_sections_and_a_template_is_not_a_skill(github):
    github({"acme/agent-skills/main": _tarball(MARKET)})
    pkg = si.fetch_skill_package("https://github.com/acme/agent-skills")
    assert [(s.id, [f.rsplit("/", 1)[-1] for f in s.folders]) for s in pkg.sections] == [
        ("document-skills", ["pdf", "xlsx"]), ("example-skills", ["frontend-design"])]
    assert "template-skill" not in {s.name for s in pkg.skills}
    pdf = next(s for s in pkg.skills if s.name == "pdf")
    assert sorted(pdf.files) == ["SKILL.md", "forms.md", "scripts/fill.py"]
    assert pdf.section == "document-skills"
    assert pkg.description == "Example skills" and pkg.version == "2.0.0"


def test_a_repository_of_loose_top_level_skills_and_a_one_skill_repository(github):
    github({"a/loose/main": _tarball({"one/SKILL.md": _md("one"), "two/SKILL.md": _md("two"),
                                      "docs/deep/x/SKILL.md": _md("buried")}),
            "a/single/main": _tarball({"SKILL.md": _md("single"), "ref.md": "r"})})
    loose = si.fetch_skill_package("https://github.com/a/loose")
    assert sorted(s.name for s in loose.skills) == ["one", "two"]
    single = si.fetch_skill_package("https://github.com/a/single")
    assert [(s.folder, s.name, sorted(s.files)) for s in single.skills] == [
        ("", "single", ["SKILL.md", "ref.md"])]


def test_a_named_skill_that_is_not_there_is_said_and_the_package_still_comes(github):
    github({"Leonxlnx/taste-skill/main": _tarball(TASTE)})
    pkg = si.fetch_skill_package("npx skills add Leonxlnx/taste-skill --skill no-such-thing")
    assert len(pkg.skills) == 4 and pkg.named == ""
    assert any("no skill called “no-such-thing”" in n for n in pkg.notes)


def test_master_is_tried_when_there_is_no_main_and_a_missing_repo_says_so(github):
    fake = github({"old/repo/master": _tarball({"skills/a/SKILL.md": _md("a")})})
    pkg = si.fetch_skill_package("https://github.com/old/repo")
    assert pkg.src.ref == "master" and [s.name for s in pkg.skills] == ["a"]
    assert fake.asked[-2:] == ["https://codeload.github.com/old/repo/tar.gz/main",
                               "https://codeload.github.com/old/repo/tar.gz/master"]
    with pytest.raises(SkillImportError, match="private repository"):
        si.fetch_skill_package("https://github.com/nobody/nothing")


def test_the_archive_cannot_write_outside_or_carry_links(github):
    evil = []
    for name, kind in (("repo-main/skills/a/link.md", tarfile.SYMTYPE),
                       ("repo-main/skills/a/hard.md", tarfile.LNKTYPE)):
        info = tarfile.TarInfo(name)
        info.type = kind
        info.linkname = "/etc/passwd"
        evil.append(info)
    for name in ("repo-main/../escape.md", "other-root/skills/b/SKILL.md"):
        info = tarfile.TarInfo(name)
        info.size = 4
        evil.append(info)
    github({"x/y/main": _tarball({"skills/a/SKILL.md": _md("a")}, extra=evil)})
    pkg = si.fetch_skill_package("https://github.com/x/y")
    assert [(s.name, sorted(s.files)) for s in pkg.skills] == [("a", ["SKILL.md"])]


def test_the_caps_hold_and_say_what_they_left_out(github, monkeypatch):
    monkeypatch.setattr(si, "MAX_FILE_BYTES", 70)
    assert len(_md("a")) < 70
    files = {"skills/a/SKILL.md": _md("a"), "skills/a/big.md": "x" * 90,
             "skills/a/package-lock.json": "{}"}
    github({"x/y/main": _tarball(files)})
    pkg = si.fetch_skill_package("https://github.com/x/y")
    assert sorted(pkg.skills[0].files) == ["SKILL.md"]
    assert any("big.md" in n and "limit for one file" in n for n in pkg.notes)
    assert any("package-lock.json" in n and "lockfile" in n for n in pkg.notes)

    monkeypatch.setattr(si, "MAX_PACKAGE_SKILLS", 2)
    github({"x/y/main": _tarball(files),
            "x/many/main": _tarball({f"skills/s{i}/SKILL.md": _md(f"s{i}") for i in range(5)})})
    pkg = si.fetch_skill_package("https://github.com/x/many")
    assert len(pkg.skills) == 2 and any("holds 5 skills" in n for n in pkg.notes)

    monkeypatch.setattr(si, "MAX_ARCHIVE_UNPACKED", 10)
    with pytest.raises(SkillImportError, match="unpacks to more than"):
        si.fetch_skill_package("https://github.com/x/y")


def test_the_download_cap_is_enforced_while_the_body_streams():
    transport = si._PinnedTransport([__import__("ipaddress").ip_address("140.82.112.9")],
                                    max_bytes=10)

    class _Core:
        status = 200
        headers = []
        extensions = {}
        stream = [b"x" * 6, b"y" * 6]

        def close(self):
            pass

    transport._pool.handle_request = lambda req: _Core()
    with pytest.raises(SkillImportError, match="larger than 10 bytes"):
        transport.handle_request(httpx.Request("GET", "https://codeload.github.com/a/b/tar.gz/main"))


def test_codeload_is_a_github_host_and_is_paced_like_one():
    from src.rate_limiter import _HOST_POLICIES

    assert "codeload.github.com" in si._GITHUB_HOSTS
    assert _HOST_POLICIES["codeload.github.com"].min_interval >= 1.0


@pytest.mark.parametrize("text,package", [
    (TASTE_LINE, True),
    ("npx skills add anthropics/skills@pdf", True),
    ("https://skills.sh/anthropics/skills/pdf", True),
    ("https://github.com/anthropics/skills", True),
    ("github.com/anthropics/skills", True),
    ("https://github.com/anthropics/skills/tree/main", True),
    ("https://github.com/anthropics/skills/tree/main/skills/pdf", False),
    ("https://github.com/anthropics/skills/blob/main/skills/pdf/SKILL.md", False),
    ("https://raw.githubusercontent.com/anthropics/skills/main/skills/pdf/SKILL.md", False),
    ("https://skills.sh/abc123", False),
    ("https://example.com/x/y", False),
])
def test_which_links_import_a_whole_package(text, package):
    assert si.is_package_link(text) is package


def test_b928_the_folder_link_path_also_finds_a_skill_by_its_own_name(github):
    """`_locate_named_skill` is still what `fetch_skill_bundle_report` uses."""
    tree = {"tree": [{"path": "skills/taste-skill/SKILL.md", "type": "blob"},
                     {"path": "skills/brandkit/SKILL.md", "type": "blob"}]}
    api = {"https://api.github.com/repos/Leonxlnx/taste-skill/git/trees/main?recursive=1": tree}
    raw = {"Leonxlnx/taste-skill/main/skills/taste-skill/SKILL.md": _md("design-taste-frontend"),
           "Leonxlnx/taste-skill/main/skills/brandkit/SKILL.md": _md("brandkit")}
    github(raw=raw, api=api)
    src = si.ResolvedSource(owner="Leonxlnx", repo="taste-skill", ref="main", path="",
                            skill="design-taste-frontend", ref_known=True)
    si._locate_named_skill(src)
    assert src.path == "skills/taste-skill"


# ── installed ───────────────────────────────────────────────────────────────

def test_installed_under_its_sections_and_recorded_as_one_package(github, store, tmp_path):
    github({"acme/agent-skills/main": _tarball(MARKET)})
    out = store.install_package(si.fetch_skill_package("https://github.com/acme/agent-skills"))
    assert sorted(out["installed"]) == ["frontend-design", "pdf", "xlsx"]
    root = tmp_path / "skills"
    assert (root / "document-skills" / "pdf" / "forms.md").read_text() == "forms"
    assert (root / "document-skills" / "pdf" / "scripts" / "fill.py").exists()
    assert (root / "example-skills" / "frontend-design" / "SKILL.md").exists()
    rec = store.collections.package(None, "acme--agent-skills")
    assert rec["mode"] == "full" and rec["enabled"] is True
    assert [(s["id"], s["skills"]) for s in rec["sections"]] == [
        ("document-skills", ["pdf", "xlsx"]), ("example-skills", ["frontend-design"])]


def test_a_single_section_package_is_filed_under_its_own_name(github, store, tmp_path):
    github({"Leonxlnx/taste-skill/main": _tarball(TASTE)})
    out = store.install_package(si.fetch_skill_package(TASTE_LINE))
    assert out["named"] == "design-taste-frontend"
    assert (tmp_path / "skills" / "taste-skill" / "design-taste-frontend" / "SKILL.md").exists()
    assert {s["category"] for s in store.load()} == {"taste-skill"}


def test_importing_again_refreshes_in_place_and_keeps_what_a_person_decided(github, store):
    fake = github({"Leonxlnx/taste-skill/main": _tarball(TASTE)})
    store.install_package(si.fetch_skill_package(TASTE_LINE))
    assert store.update_skill("brandkit", {"status": "published", "confidence": 0.95})
    changed = dict(TASTE, **{"skills/brandkit/SKILL.md": _md("brandkit", "A sharper brandkit.")})
    fake.archives["Leonxlnx/taste-skill/main"] = _tarball(changed)
    out = store.install_package(si.fetch_skill_package("https://github.com/Leonxlnx/taste-skill"))
    assert out["installed"] == [] and sorted(out["updated"]) == sorted(
        ["brandkit", "design-taste-frontend", "design-taste-frontend-v1", "stitch-design-taste"])
    brandkit = next(s for s in store.load() if s["name"] == "brandkit")
    assert brandkit["description"] == "A sharper brandkit."
    assert brandkit["status"] == "published" and float(brandkit["confidence"]) == 0.95
    assert [v for v in store.list_versions("brandkit")], "the replaced SKILL.md was not kept"
    assert len(store.collections.packages(None)) == 1


def test_a_name_someone_else_has_is_not_overwritten(github, store):
    store.add_skill(name="brandkit", description="mine", procedure=["keep me"])
    github({"Leonxlnx/taste-skill/main": _tarball(TASTE)})
    out = store.install_package(si.fetch_skill_package(TASTE_LINE))
    assert out["renamed"] == {"brandkit": "brandkit-2"}
    mine = next(s for s in store.load() if s["name"] == "brandkit")
    assert mine["description"] == "mine"
    assert "brandkit-2" in store.collections.package(None, "leonxlnx--taste-skill")["sections"][0]["skills"]


def test_one_skill_by_its_folder_then_the_whole_repository_is_one_package(github, store):
    github({"Leonxlnx/taste-skill/main": _tarball(TASTE)})
    files = {"skills/brandkit/SKILL.md": _md("brandkit")}
    src = si.ResolvedSource(owner="Leonxlnx", repo="taste-skill", ref="main", path="skills/brandkit")
    store.install_package(si.single_skill_package(files, src))
    rec = store.collections.package(None, "leonxlnx--taste-skill")
    assert rec["mode"] == "partial" and rec["names"] == {"skills/brandkit": "brandkit"}
    out = store.install_package(si.fetch_skill_package(TASTE_LINE))
    assert out["updated"] == ["brandkit"] and len(out["installed"]) == 3
    rec = store.collections.package(None, "leonxlnx--taste-skill")
    assert rec["mode"] == "full" and len(rec["names"]) == 4


def test_removing_a_package_removes_its_skills_unless_asked_to_keep_them(github, store):
    github({"Leonxlnx/taste-skill/main": _tarball(TASTE)})
    store.install_package(si.fetch_skill_package(TASTE_LINE))
    store.collections.create_group(None, "Design", ["brandkit"])
    out = store.remove_package("leonxlnx--taste-skill")
    assert len(out["removed"]) == 4 and store.load() == []
    assert store.collections.group(None, "design")["skills"] == [], "a group kept a deleted name"
    store.install_package(si.fetch_skill_package(TASTE_LINE))
    store.remove_package("leonxlnx--taste-skill", keep_skills=True)
    assert len(store.load()) == 4 and store.collections.packages(None) == []


# ── groups, switches, and the model ─────────────────────────────────────────

def test_a_group_references_and_a_rename_or_delete_follows_the_skill(store):
    for n in ("a", "b"):
        store.add_skill(name=n, description=n, procedure=["x"])
    col = store.collections
    g1 = col.create_group(None, "Design", ["a", "b"])
    g2 = col.create_group(None, "Design", ["a"])
    assert (g1["id"], g2["id"]) == ("design", "design-2")
    # Stored once, listed twice: nothing on disk was copied.
    assert sorted(s["name"] for s in store.load()) == ["a", "b"]
    assert store.update_skill("a", {"name": "a-renamed"})
    assert col.group(None, "design")["skills"] == ["a-renamed", "b"]
    assert col.group(None, "design-2")["skills"] == ["a-renamed"]
    assert store.delete_skill("b")
    assert col.group(None, "design")["skills"] == ["a-renamed"]
    with pytest.raises(ValueError, match="needs a name"):
        col.create_group(None, "   ")


def test_off_wins_and_says_what_holds_a_skill_off(github, store):
    github({"Leonxlnx/taste-skill/main": _tarball(TASTE)})
    store.install_package(si.fetch_skill_package(TASTE_LINE))
    col = store.collections
    col.create_group(None, "Keep on", ["brandkit"])
    col.create_group(None, "Images", ["brandkit"])
    col.update_group(None, "images", enabled=False)
    assert col.switched_off(None) == {"brandkit": ["Images"]}
    col.set_package_enabled(None, "leonxlnx--taste-skill", False)
    off = col.switched_off(None)
    assert off["brandkit"] == ["taste-skill", "Images"] and len(off) == 4
    assert store.load_active() == [] and len(store.load()) == 4
    col.set_package_enabled(None, "leonxlnx--taste-skill", True)
    assert [s["name"] for s in store.load_active()].count("brandkit") == 0, (
        "switching the package back on re-enabled a skill a group still holds off")


def test_owners_do_not_share_packages_or_switches(github, store):
    github({"Leonxlnx/taste-skill/main": _tarball(TASTE)})
    store.install_package(si.fetch_skill_package(TASTE_LINE), owner="alice")
    col = store.collections
    assert col.packages("bob") == [] and len(col.packages("alice")) == 1
    col.set_package_enabled("bob", "leonxlnx--taste-skill", False)
    assert col.disabled_names("alice") == set()
    col.set_package_enabled("alice", "leonxlnx--taste-skill", False)
    assert col.disabled_names("bob") == set()


def test_a_damaged_collections_file_leaves_every_skill_on(store, tmp_path):
    store.add_skill(name="a", description="a", procedure=["x"])
    (tmp_path / "skills" / "_collections.json").write_text("{not json")
    assert [s["name"] for s in store.load_active()] == ["a"]


def test_fork_is_the_one_copy_and_says_where_it_came_from(tmp_path):
    lib = tmp_path / "lib" / "docs" / "house-style"
    lib.mkdir(parents=True)
    (lib / "SKILL.md").write_text(_md("house-style"))
    (lib / "examples.md").write_text("examples")
    sm = SkillsManager(str(tmp_path / "data"), library_root=str(tmp_path / "lib"))
    fork = sm.fork_skill("house-style")
    assert fork["name"] == "house-style-fork" and fork["forked_from"] == "house-style"
    assert "Forked from `house-style`." in fork["body_extra"]
    assert (tmp_path / "data" / "skills" / fork["category"] / "house-style-fork" / "examples.md").exists()
    assert sm.fork_skill("house-style", "house-style-fork")["name"] == "house-style-fork-2"
    assert sm.fork_skill("nope") is None


def _write_published(root, name, category="ops", description="a test procedure", step="do it"):
    d = root / category / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text("\n".join([
        "---", f"name: {name}", f"description: {description}", "version: 1.0.0",
        f"category: {category}", "tags: []", "status: published", "confidence: 0.9",
        "source: learned", "created: 2026-01-01T00:00:00Z", "---", "",
        "## When to Use", "- a test", "", "## Procedure", f"1. {step}", ""]), encoding="utf-8")


def test_a_switched_off_skill_is_in_no_part_of_what_the_model_is_sent(tmp_path, monkeypatch):
    """The whole message array of one agent request — catalogue and matched
    procedures — with `tidy-logs` in a group that is switched off."""
    import src.agent_loop as agent_loop
    import src.constants as constants
    from test_the_skill_index_is_injected_once import REQUEST, _preface, _request_messages

    # The description is the request itself, so retrieval matches it and the
    # procedure — not only the catalogue line — is injected when it is on.
    _write_published(tmp_path / "skills", "tidy-logs", description=REQUEST.split(",")[0],
                     step="PRUNE-STEP-SENTINEL")
    _write_published(tmp_path / "skills", "rotate-files")
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(agent_loop, "_cached_base_prompt", None, raising=False)
    monkeypatch.setattr(agent_loop, "_cached_base_prompt_key", None, raising=False)
    sm = SkillsManager(str(tmp_path))
    on = json.dumps(_request_messages(monkeypatch, _preface(sm)))
    assert "tidy-logs" in on and "rotate-files" in on
    assert "PRUNE-STEP-SENTINEL" in on, "the matched procedure was not injected to begin with"
    sm.collections.create_group(None, "Ops", ["tidy-logs"])
    sm.collections.update_group(None, "ops", enabled=False)
    monkeypatch.setattr(agent_loop, "_cached_base_prompt", None, raising=False)
    off = json.dumps(_request_messages(monkeypatch, _preface(sm)))
    assert "tidy-logs" not in off, "a switched-off skill still reached the model"
    assert "PRUNE-STEP-SENTINEL" not in off, "its procedure was still injected by retrieval"
    assert "rotate-files" in off


def test_the_model_s_own_list_and_search_leave_it_out_too(tmp_path, monkeypatch):
    import src.constants as constants
    from src.tools import system

    _write_published(tmp_path / "skills", "tidy-logs")
    _write_published(tmp_path / "skills", "rotate-files")
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(system, "DATA_DIR", str(tmp_path), raising=False)
    SkillCollections(str(tmp_path / "skills")).create_group(None, "Ops", ["tidy-logs"])
    SkillCollections(str(tmp_path / "skills")).update_group(None, "ops", enabled=False)
    listed = asyncio.run(system.do_manage_skills(json.dumps({"action": "list"})))["results"]
    assert "rotate-files" in listed and "tidy-logs" not in listed
    viewed = asyncio.run(system.do_manage_skills(json.dumps({"action": "view", "name": "tidy-logs"})))
    assert "do it" in json.dumps(viewed), "a person naming a skill can still open it"


# ── the routes ──────────────────────────────────────────────────────────────

def _app(store, monkeypatch, admin=True):
    import routes.skills_routes as routes
    from fastapi import HTTPException

    def gate(request):
        if not admin:
            raise HTTPException(403, "Admin only")

    monkeypatch.setattr(routes, "require_admin", gate)
    app = FastAPI()
    app.include_router(routes.setup_skills_routes(store))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_the_import_route_answers_with_the_package(github, store, monkeypatch):
    github({"Leonxlnx/taste-skill/main": _tarball(TASTE)})
    async with _app(store, monkeypatch) as client:
        res = await client.post("/api/skills/import-from-url", json={"url": TASTE_LINE})
        body = res.json()
        assert res.status_code == 200, body
        assert body["skill"]["name"] == "design-taste-frontend"
        assert body["package"]["title"] == "taste-skill" and len(body["installed"]) == 4
        assert body["package"]["sections"][0]["skills"][0] == "brandkit"
        col = await client.get("/api/skills/collections")
        assert col.status_code == 200, "GET /collections was read as a skill id"
        assert [p["id"] for p in col.json()["packages"]] == ["leonxlnx--taste-skill"]


@pytest.mark.asyncio
async def test_switching_a_package_off_and_removing_it_over_the_api(github, store, monkeypatch):
    github({"Leonxlnx/taste-skill/main": _tarball(TASTE)})
    store.install_package(si.fetch_skill_package(TASTE_LINE))
    async with _app(store, monkeypatch) as client:
        res = await client.patch("/api/skills/packages/leonxlnx--taste-skill", json={"enabled": False})
        assert res.json()["package"]["enabled"] is False
        off = (await client.get("/api/skills/collections")).json()["off"]
        assert off["brandkit"] == ["taste-skill"]
        assert (await client.patch("/api/skills/packages/nope", json={"enabled": True})).status_code == 404
        res = await client.delete("/api/skills/packages/leonxlnx--taste-skill")
        assert len(res.json()["removed"]) == 4 and store.load() == []


@pytest.mark.asyncio
async def test_refreshing_a_package_is_admin_only_and_refreshes(github, store, monkeypatch):
    fake = github({"Leonxlnx/taste-skill/main": _tarball(TASTE)})
    store.install_package(si.fetch_skill_package(TASTE_LINE))
    async with _app(store, monkeypatch, admin=False) as client:
        res = await client.post("/api/skills/packages/leonxlnx--taste-skill/update")
        assert res.status_code == 403
    fake.asked.clear()
    async with _app(store, monkeypatch) as client:
        res = await client.post("/api/skills/packages/leonxlnx--taste-skill/update")
        assert res.status_code == 200 and len(res.json()["updated"]) == 4
    assert fake.asked == ["https://codeload.github.com/Leonxlnx/taste-skill/tar.gz/main"]


@pytest.mark.asyncio
async def test_groups_over_the_api(store, monkeypatch):
    for n in ("a", "b"):
        store.add_skill(name=n, description=n, procedure=["x"])
    async with _app(store, monkeypatch) as client:
        bad = await client.post("/api/skills/groups", json={"title": "G", "skills": ["zzz"]})
        assert bad.status_code == 400 and "zzz" in bad.json()["detail"]
        made = (await client.post("/api/skills/groups", json={"title": "Design", "skills": ["a"]})).json()
        gid = made["group"]["id"]
        res = await client.patch(f"/api/skills/groups/{gid}", json={"add": ["b"], "remove": ["a"],
                                                                      "enabled": False})
        assert res.json()["group"] == {"id": "design", "title": "Design", "enabled": False,
                                       "skills": ["b"]}
        assert [s["name"] for s in store.load_active()] == ["a"]
        assert (await client.delete(f"/api/skills/groups/{gid}")).status_code == 200
        assert sorted(s["name"] for s in store.load_active()) == ["a", "b"]
        assert (await client.delete(f"/api/skills/groups/{gid}")).status_code == 404


@pytest.mark.asyncio
async def test_fork_over_the_api(store, monkeypatch):
    store.add_skill(name="a", description="a", procedure=["x"])
    async with _app(store, monkeypatch) as client:
        res = await client.post("/api/skills/a/fork", json={"name": "a-acme"})
        assert res.status_code == 200 and res.json()["skill"]["name"] == "a-acme"
        assert (await client.post("/api/skills/missing/fork", json={})).status_code == 404
    assert sorted(s["name"] for s in store.load()) == ["a", "a-acme"]
