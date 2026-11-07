# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2009`. `pantheon-gallery list --tag` missed AI tags and stacked tags.

The CLI's tag filter was one substring match against the `tags` column. The
Gallery keeps a picture's AI tags in `ai_tags` and its PATCH route moves any
tag that is also an AI tag out of `tags`, so `--tag sunset` missed pictures
the Gallery shows under *sunset*. A comma-separated `--tag sunset,beach` was
one literal substring, which a row stored as `sunset, beach` never contains,
and a `%` or `_` was a wildcard.

Now `--tag` splits on commas, and each tag must match the manual or the AI
tags, as the web library's own tag filter does (`B2004` escapes LIKE's
wildcards there, and here too). `--favorites`, `--album` and `--limit`
narrow the result as before.

Ported from upstream Odysseus fec2bb11 (#6951); the cases are upstream's,
with rows stored as Pantheon's PATCH route stores them (`', '`-joined).
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, GalleryAlbum, GalleryImage
from tests.helpers.cli_loader import load_script

EVERY_ACTIVE_ROW = ["sale", "other", "one", "split", "ai", "manual"]   # newest first
BOTH_TAGS = ["split", "ai", "manual"]


@pytest.fixture
def gallery_cli(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'gallery.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(GalleryAlbum(id="sea", name="Sea"))
        for index, (uid, tags, ai_tags, favorite, album) in enumerate([
            ("manual", "sunset, beach", "", True, "sea"),
            ("ai", "", "Beach, sunset", False, "sea"),
            ("split", "sunset", "beach", True, None),
            ("one", "sunset", "", False, None),
            ("other", "forest", "moss", False, None),
            ("inactive", "sunset, beach", "sunset, beach", True, "sea"),
            ("sale", "sale_2024", "", False, None),
        ]):
            db.add(GalleryImage(id=uid, filename=uid + ".png", tags=tags, ai_tags=ai_tags,
                                favorite=favorite, album_id=album, is_active=uid != "inactive",
                                created_at=datetime(2026, 1, 1) + timedelta(minutes=index)))
        db.commit()
    cli = load_script("pantheon-gallery")
    monkeypatch.setattr(cli, "SessionLocal", sessions)
    output = []
    monkeypatch.setattr(cli, "emit", lambda rows, args: output.extend(rows))

    def run(*argv):
        output.clear()
        args = cli._build_parser().parse_args(["list", *argv])
        args.func(args)
        return [row["id"] for row in output]

    yield run
    engine.dispose()


@pytest.mark.parametrize("tag,expected", [
    ("sunset", ["one", "split", "ai", "manual"]),
    ("sun", ["one", "split", "ai", "manual"]),
    ("moss", ["other"]),
    ("beach,sunset", BOTH_TAGS),
    ("sunset,beach", BOTH_TAGS),
    (", sunset, , BEACH ,", BOTH_TAGS),
    (" , ", EVERY_ACTIVE_ROW),
    ("%", []),
    ("_", ["sale"]),
])
def test_each_tag_matches_the_manual_or_the_ai_tags_and_they_stack(gallery_cli, tag, expected):
    assert gallery_cli("--tag", tag) == expected


@pytest.mark.parametrize("tag,expected", [
    ("forest", ["other"]),
    ("no-match", []),
])
def test_a_manual_tag_finds_what_it_found_before(gallery_cli, tag, expected):
    assert gallery_cli("--tag", tag) == expected


@pytest.mark.parametrize("options,expected", [
    ([], EVERY_ACTIVE_ROW),
    (["--favorites"], ["split", "manual"]),
    (["--album", "Sea"], ["ai", "manual"]),
    (["--limit", "2"], ["sale", "other"]),
    (["--tag", "sunset", "--favorites"], ["split", "manual"]),
])
def test_the_other_list_options_narrow_as_before(gallery_cli, options, expected):
    assert gallery_cli(*options) == expected


@pytest.mark.parametrize("options,expected", [
    (["--tag", "beach,sunset", "--favorites"], ["split", "manual"]),
    (["--tag", "beach,sunset", "--album", "Sea"], ["ai", "manual"]),
    (["--tag", "beach", "--limit", "1"], ["split"]),
])
def test_stacked_tags_narrow_with_the_other_options(gallery_cli, options, expected):
    assert gallery_cli(*options) == expected
