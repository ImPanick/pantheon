# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where a document's text came from, recorded when it is made (`B1325`).

`B1300` gave the person's own saved material its own envelope
(`prompt_security.own_context_message`: no accusing header, and the tool gate
not armed — `D-2026-10-09-01` §1) and could move only memory onto it, because a
document reaches the library by several paths that are indistinguishable
afterwards: typed in the editor, imported from a file, or made by the agent or
by *Save to Docs* from a chat that already held web results. So the document
open in the editor stayed on the untrusted envelope — right for an imported
PDF, wrong for a note the person wrote.

**The adversary** (`Law 17`) is a document's text written by somebody other
than the person — an imported file, a page the agent fetched, a reply that
quotes an email — steering the agent into a tool call. Only a document the
person wrote here is their own material; everything else keeps the armed gate.
So the vocabulary is three words and the safe side is the default:

* `authored_here` — typed in this editor (a blank document, a new email). The
  one provenance that reaches `own_context_message`.
* `imported` — a file's text: the Library's and the chat's imports, a mail
  attachment, an Office or PDF file opened as a document.
* `derived` — made from other material: by the agent, by *Save to Docs* from a
  chat, a reply quoting an email, a copy of a document whose source is not known.

A document from before the column existed reads NULL, which is treated as
`imported` — nobody can say now how it was made (`Law 10`: an unknown is not a
yes). An agent's write into an `authored_here` document makes it `derived`:
from then on the text holds something the person did not write. A person's own
edit changes nothing — an imported text they corrected is still mostly the
import.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

AUTHORED_HERE = "authored_here"
IMPORTED = "imported"
DERIVED = "derived"
PROVENANCES = (AUTHORED_HERE, IMPORTED, DERIVED)


def resolve_created(requested: Optional[str], *, source_name: Optional[str] = None) -> str:
    """The provenance a document made through `POST /api/document` gets.

    A file's name (`source_name`) makes it `imported` whatever was asked; an
    asked-for word from the vocabulary is kept; anything else is `derived` —
    a caller that does not say how the text was made does not get the trusted
    envelope by default.
    """
    if source_name:
        return IMPORTED
    word = str(requested or "").strip().lower()
    return word if word in PROVENANCES else DERIVED


def is_own(doc: Any) -> bool:
    """Whether *doc* is the person's own material for the prompt envelope."""
    return getattr(doc, "provenance", None) == AUTHORED_HERE


def after_agent_edit(doc: Any) -> None:
    """The agent wrote into *doc*: its text is no longer only the person's."""
    if getattr(doc, "provenance", None) == AUTHORED_HERE:
        doc.provenance = DERIVED


def document_context_message(label: str, content: Any, doc: Any) -> Dict[str, Any]:
    """The message that puts an open document in front of the model, in the
    envelope its provenance earns: `own_context_message` for a document the
    person wrote here, `untrusted_context_message` (tool gate armed) for every
    other one, including one whose provenance is not known."""
    from src.prompt_security import own_context_message, untrusted_context_message

    if is_own(doc):
        return own_context_message(label, content, provenance_origin=AUTHORED_HERE)
    return untrusted_context_message(
        label, content, provenance_origin=getattr(doc, "provenance", None) or IMPORTED)
