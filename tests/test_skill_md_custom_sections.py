# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1951`. Writing a SKILL.md back lost every section Pantheon does not model.

`parse_body` maps the four known `##` headings (When to Use, Procedure,
Pitfalls, Verification; `## Steps` reads as Procedure) onto fields and keeps
everything else in `body_extra`. It dropped the heading line of any other
section, and took a `##` line inside a fenced code example for a heading too,
so `## Examples` or `## Reference` vanished the first time the file was
written back and their text ran into the paragraph above. `emit_body` then
wrote all of that text after the last list section, where the next read
folded it into the last step, pitfall or check. A SKILL.md is written back on
every save in the Skills editor, every `update_skill` (the model's own
`manage_skills` edits too), a bundle import, a fork, and adding a skill from
the bundled library, where 289 of the 310 shipped files use other headings:
the copy the model was shown had lost them.

Now an unknown heading stays with its text, a `##` line inside a code fence is
example text, and the text before the first heading is written first and the
other sections after the four. A fence that never closes is not counted, so
it cannot hide the headings after it. Files already flattened by the old
writer are not repaired.

Ported from upstream Odysseus de438bfc and 030498bb (PR #6939); the cases down
to `test_fenced_example_survives_manager_update` are upstream's. The shipped
skills, the unclosed fence and the four headings beside a custom one are
Pantheon's cases.
"""

import textwrap
from pathlib import Path

import pytest
from services.memory.skill_format import Skill, emit_body, parse_body
from services.memory.skills import SkillsManager, invalidate_skill_cache


SKILL_MD = textwrap.dedent("""\
    ---
    name: pdf-forms
    description: Fill PDF forms
    ---

    # PDF forms

    Use this when the user hands you a fillable PDF.

    ## Overview

    Forms come in two flavours.

    ## When to use

    User asks to fill a form.

    ## Procedure

    1. Detect fields
    2. Fill them

    ## Examples

    - W-9
    - I-9
    """)


def test_parse_body_keeps_unknown_headings_in_body_extra():
    body = SKILL_MD.split("---\n", 2)[2]
    sections = parse_body(body)

    assert sections["when_to_use"] == "User asks to fill a form."
    assert sections["procedure"] == ["Detect fields", "Fill them"]
    extra = sections["body_extra"]
    assert "## Overview\n\nForms come in two flavours." in extra
    assert "## Examples\n\n- W-9\n- I-9" in extra
    # The free-form sections stay in their original order.
    assert extra.index("# PDF forms") < extra.index("## Overview") < extra.index("## Examples")
    # And the known headings are not copied into it as well.
    assert "## Procedure" not in extra
    assert "## When to use" not in extra


def test_rewritten_markdown_keeps_custom_sections():
    out = Skill.from_markdown(SKILL_MD).to_markdown()

    assert "## Overview\n\nForms come in two flavours." in out
    assert "## Examples\n\n- W-9\n- I-9" in out
    assert "## Procedure\n\n1. Detect fields\n2. Fill them" in out


def test_second_rewrite_does_not_change_the_body():
    once = Skill.from_markdown(SKILL_MD)
    twice = Skill.from_markdown(once.to_markdown())

    assert twice.body_extra == once.body_extra
    assert twice.procedure == once.procedure
    assert twice.when_to_use == once.when_to_use


def test_imported_bundle_keeps_custom_sections(tmp_path):
    mgr = SkillsManager(str(tmp_path))
    result = mgr.import_bundle_from_files({"pdf-forms/SKILL.md": SKILL_MD}, owner="alice")

    with open(result["path"], encoding="utf-8") as f:
        written = f.read()
    assert "## Overview" in written
    assert "## Examples" in written


def test_update_skill_keeps_custom_sections(tmp_path):
    mgr = SkillsManager(str(tmp_path))
    result = mgr.import_bundle_from_files({"pdf-forms/SKILL.md": SKILL_MD}, owner="alice")

    assert mgr.update_skill(result["name"], {"status": "published"}, owner="alice")

    with open(result["path"], encoding="utf-8") as f:
        written = f.read()
    assert "status: published" in written
    assert "## Overview\n\nForms come in two flavours." in written
    assert "## Examples\n\n- W-9\n- I-9" in written


def test_free_text_is_not_folded_into_the_last_list(tmp_path):
    # Plain notes used to be written after the Pitfalls list and read back
    # as part of its last item: "forgetting changelog Always run ...".
    mgr = SkillsManager(str(tmp_path))
    mgr.add_skill(name="release", description="Cut a release", source="user",
                  procedure=["bump version", "tag"], pitfalls=["forgetting changelog"])
    note = "Always run the smoke suite on staging first."

    assert mgr.update_skill("release", {"body_extra": note})
    assert mgr.update_skill("release", {"status": "published"})

    skill = mgr.load()[0]
    assert skill["pitfalls"] == ["forgetting changelog"]
    assert skill["procedure"] == ["bump version", "tag"]
    assert skill["body_extra"] == note


FENCED_MD = textwrap.dedent("""\
    ---
    name: skill-writer
    description: Write SKILL.md files
    ---

    ## When to use

    User asks for a new skill.

    ## Procedure

    1. Draft the file

    ## Examples

    A minimal skill looks like this:

    ```markdown
    ## Procedure

    1. Do the thing
    ```

    ~~~
    ## Pitfalls
    ~~~
    """)


def test_headings_inside_code_fences_are_not_sections():
    sections = parse_body(FENCED_MD.split("---\n", 2)[2])

    assert sections["procedure"] == ["Draft the file"]
    assert sections["pitfalls"] == []
    assert "```markdown\n## Procedure\n\n1. Do the thing\n```" in sections["body_extra"]
    assert "~~~\n## Pitfalls\n~~~" in sections["body_extra"]


def test_fenced_example_survives_a_rewrite():
    once = Skill.from_markdown(FENCED_MD)
    out = once.to_markdown()
    twice = Skill.from_markdown(out)

    assert "## Examples\n\nA minimal skill looks like this:\n\n```markdown\n## Procedure\n\n1. Do the thing\n```" in out
    assert twice.procedure == ["Draft the file"]
    assert twice.body_extra == once.body_extra


def test_fenced_heading_in_leading_text_stays_on_top():
    md = FENCED_MD.replace("## When to use", "```\n## Not a section\n```\n\n## When to use", 1)
    out = Skill.from_markdown(md).to_markdown()
    body = out.split("---\n", 2)[2]

    assert body.index("## Not a section") < body.index("## When to Use")
    assert Skill.from_markdown(out).body_extra == Skill.from_markdown(md).body_extra


@pytest.mark.parametrize("opening,inside,closing", [
    ("````markdown", "```\n## Procedure", "````"),
    ("~~~markdown", "```\n## Procedure\n```", "~~~~"),
    ("   ```markdown", "## Procedure\n```not-a-closing-fence\n## Pitfalls", "   ```  "),
])
def test_fence_marker_and_length_are_respected(opening, inside, closing):
    example = f"## Examples\n\n{opening}\n{inside}\n{closing}"
    body = f"{example}\n\n## Procedure\n\n1. Real step\n"
    once = Skill.from_markdown(body)
    twice = Skill.from_markdown(once.to_markdown())

    assert once.procedure == twice.procedure == ["Real step"]
    assert twice.pitfalls == []
    assert twice.body_extra == example.rstrip()


def test_fenced_example_survives_manager_update(tmp_path):
    manager = SkillsManager(str(tmp_path))
    imported = manager.import_bundle_from_files(
        {"skill-writer/SKILL.md": FENCED_MD}, owner="alice",
    )
    assert manager.update_skill(imported["name"], {"status": "published"}, owner="alice")
    with open(imported["path"], encoding="utf-8") as source:
        saved = Skill.from_markdown(source.read())
    assert saved.procedure == ["Draft the file"]
    assert saved.body_extra == Skill.from_markdown(FENCED_MD).body_extra


# ── Pantheon's cases ──────────────────────────────────────────────────────────

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def shipped(tmp_path):
    """A fresh store over the libraries that ship."""
    invalidate_skill_cache()
    yield SkillsManager(str(tmp_path))
    invalidate_skill_cache()


def _lines(path):
    return Path(path).read_text(encoding="utf-8").splitlines()


def test_a_forked_shipped_skill_keeps_its_examples_through_two_saves(shipped):
    """`chart-the-numbers` shows its charts under `## Examples`, between the
    steps and the pitfalls. A fork lost the heading and wrote the two mermaid
    blocks after the checks, and the next save folded them into the last
    check, so the fork's file had no example left to copy."""
    shipped_md = REPO / "library" / "pantheon" / "skills" / "chart-the-numbers" / "SKILL.md"
    fences = [line for line in _lines(shipped_md) if line.startswith("```")]
    assert "## Examples" in _lines(shipped_md) and fences
    as_shipped = Skill.from_markdown(shipped_md.read_text(encoding="utf-8"))

    fork = shipped.fork_skill("chart-the-numbers", owner="alice")
    assert shipped.update_skill(fork["name"], {"description": "Charts, my way"}, owner="alice")
    assert shipped.update_skill(fork["name"], {"description": "Charts, my own way"}, owner="alice")

    written = _lines(fork["path"])
    assert "## Examples" in written
    assert [line for line in written if line.startswith("```")] == fences
    saved = Skill.from_markdown("\n".join(written))
    assert saved.pitfalls == as_shipped.pitfalls
    assert saved.verification == as_shipped.verification
    assert not any("```" in item for item in saved.pitfalls + saved.verification)
    assert "Forked from `chart-the-numbers`." in saved.body_extra


def test_adding_a_shipped_skill_keeps_its_headings(shipped):
    """Adding a skill from the library is the one way it reaches the model
    (`D-2026-10-26-01` §8), and the copy was written through the parser:
    `api-design`'s eleven `##` headings, none of them one of the four, came
    out as none."""
    shipped_md = REPO / "library" / "ecc" / "skills" / "api-design" / "SKILL.md"
    headings = [line for line in _lines(shipped_md) if line.startswith("## ")]
    four = {"when to use", "procedure", "steps", "pitfalls", "verification"}
    assert headings and not any(line[3:].strip().lower() in four for line in headings)

    added = shipped.adopt_library_skill("api-design", owner="alice")

    assert [line for line in _lines(added["path"]) if line.startswith("## ")] == headings


def test_an_unclosed_fence_does_not_hide_the_headings_after_it():
    """A fence opened and never closed is a typo, and counting it hid every
    heading after it: upstream's patch alone read the skill below with no
    procedure. Without fences counted, the steps stay steps and the custom
    heading stays with its text."""
    assert parse_body("Intro\n```bash\necho hi\n\n## Procedure\n1. a\n")["procedure"] == ["a"]

    md = ("---\nname: t\ndescription: d\n---\n\nIntro\n```bash\necho hi\n\n"
          "## Notes\n\nfoo\n\n## Procedure\n\n1. a\n2. b\n\n## Pitfalls\n\n- p\n")
    once = Skill.from_markdown(md)
    assert once.procedure == ["a", "b"]
    assert once.pitfalls == ["p"]
    assert "## Notes\n\nfoo" in once.body_extra

    out = once.to_markdown()
    twice = Skill.from_markdown(out)
    assert (twice.procedure, twice.pitfalls, twice.body_extra) == (once.procedure, once.pitfalls,
                                                                   once.body_extra)
    assert twice.to_markdown() == out


def test_the_four_headings_and_steps_read_as_before_beside_a_custom_one():
    """`.pantheon/FORBIDDEN.md` Part 1: the four `##` headings are the
    on-disk skill contract and `## Steps` must keep parsing as `procedure`.
    They still do, and a custom section beside them keeps its heading."""
    body = ("## When to Use\n\nwhen\n\n## Steps\n\n1. a\n2. b\n\n## Pitfalls\n\n- p\n\n"
            "## Verification\n\n- v\n\n## Notes\n\nkept\n")
    sections = parse_body(body)
    assert sections == {"when_to_use": "when", "procedure": ["a", "b"], "pitfalls": ["p"],
                        "verification": ["v"], "body_extra": "## Notes\n\nkept"}

    out = emit_body(sections)
    assert out == ("## When to Use\n\nwhen\n\n## Procedure\n\n1. a\n2. b\n\n## Pitfalls\n\n- p\n\n"
                   "## Verification\n\n- v\n\n## Notes\n\nkept\n")
    assert parse_body(out) == sections
