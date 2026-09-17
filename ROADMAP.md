# Roadmap

**Pantheon's roadmap lives at [`.pantheon/ROADMAP.md`](.pantheon/ROADMAP.md).**

That file is the single tracker for this project: every task, its status, what verifies it,
and one progress area recording what has landed. Start there.

---

### What used to be here

This file was Odysseus's roadmap. The fork's rename sweep put Pantheon's name on it, so it
opened with upstream's words and upstream's self-deprecation attributed to a project that had
not written either. That was wrong of us, and it is the reason this file was replaced rather
than left to be read as ours.

The original is not lost — it is in this repository's git history, and it is live upstream at
[pewdiepie-archdaemon/odysseus](https://github.com/pewdiepie-archdaemon/odysseus). If you came
here looking for Odysseus's plans, that is where they are, and they are worth reading.

Replaced 2026-08-27 (`P0-28`, D-2026-08-26-06).

**Why this path is kept.** `.pantheon/ROADMAP.md` is 1.4 MB. GitHub declines to render a
Markdown file that size, `grep` on a clone is the only sensible way to read it, and no `#anchor`
into it survives an edit — so a repository whose tracker is its main artefact needs an address
that renders. That is this page: the entry point to a tracker too large for the web view to
serve, plus the record of what stood here before. Neither reason depends on who links here.

It is also an address people and tools try by convention, and this one served upstream's roadmap
under our name for three days. A 404 would leave that with no explanation at the address where
it happened.

Two links have pointed at the tracker over this file's life —
`.github/ISSUE_TEMPLATE/feature_request.yml` was repointed at `.pantheon/ROADMAP.md` and back
again — and for a while this page justified its own existence by naming one of them. That
sentence was true when written, stopped being true when the template moved, and became true
again by coincidence. **A page whose reason to exist is a link somebody else controls has no
reason to exist.** The reason above is a property of the tracker, which is why it is stated
that way. `tests/test_the_root_roadmap_explains_itself.py` holds it there.
