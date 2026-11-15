# SPDX-License-Identifier: AGPL-3.0-or-later
"""Attachment reference helpers for chat storage and tool manifests.

Live model calls may need provider-specific data URLs for the current turn.
Persisted history and search indexes should keep stable upload references and
human-readable text instead of duplicating raw media bytes.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from src.file_names import upload_display_name


DATA_URL_RE = re.compile(
    r"data:[^;,\s\"']+;base64,[A-Za-z0-9+/=]+",
    re.IGNORECASE,
)

MEDIA_BLOCK_TYPES = {
    "image",
    "image_url",
    "input_image",
    "audio",
    "input_audio",
    "file",
}


def strip_inline_data_urls(text: str) -> str:
    """Replace inline data URLs with a compact marker."""
    if not isinstance(text, str) or ";base64," not in text:
        return text
    return DATA_URL_RE.sub("[inline media omitted from persisted history]", text)


def attachment_ref(info: dict[str, Any]) -> dict[str, Any]:
    """Return the stable attachment reference shape used outside raw uploads."""
    upload_id = str(info.get("id") or info.get("attachment_id") or "").strip()
    try:
        size = int(info.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    ref = {
        "type": "attachment_ref",
        "attachment_id": upload_id,
        # `P21-03`: the person's name for the file (`display_name`, or recovered
        # from `original_name` for an upload from before it), which is what the
        # agent's manifest and the `[Attachment: …]` line now carry.
        "name": upload_display_name(info) or upload_id,
        "mime": info.get("mime") or "application/octet-stream",
        "size": size,
    }
    checksum = info.get("checksum_sha256") or info.get("sha256") or info.get("hash")
    if checksum:
        ref["checksum_sha256"] = checksum
    created_at = info.get("created_at") or info.get("uploaded_at")
    if created_at:
        ref["created_at"] = created_at
    for key in ("width", "height", "vision", "vision_model", "gallery_id"):
        value = info.get(key)
        if value is not None:
            ref[key] = value
    return ref


def attachment_refs_from_metadata(metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract attachment refs from message metadata."""
    attachments = (metadata or {}).get("attachments") or []
    if not isinstance(attachments, list):
        return []
    refs: list[dict[str, Any]] = []
    for item in attachments:
        if isinstance(item, dict):
            ref = attachment_ref(item)
            if ref.get("attachment_id"):
                refs.append(ref)
    return refs


def _ref_line(ref: dict[str, Any]) -> str:
    parts = [f"Attachment: {ref.get('name') or ref.get('attachment_id') or 'upload'}"]
    if ref.get("attachment_id"):
        parts.append(f"id={ref['attachment_id']}")
    if ref.get("mime"):
        parts.append(f"mime={ref['mime']}")
    if ref.get("size"):
        parts.append(f"size={ref['size']} bytes")
    if ref.get("checksum_sha256"):
        parts.append(f"sha256={ref['checksum_sha256']}")
    line = "[" + " | ".join(parts) + "]"
    if ref.get("vision"):
        line += f"\n[Attachment description: {str(ref['vision']).strip()}]"
    return line


def _text_from_blocks(blocks: Iterable[Any]) -> str:
    lines: list[str] = []
    omitted_media = 0
    for block in blocks:
        if isinstance(block, str):
            lines.append(strip_inline_data_urls(block))
            continue
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                lines.append(strip_inline_data_urls(text))
        elif block_type == "attachment_ref":
            lines.append(_ref_line(block))
        elif block_type in MEDIA_BLOCK_TYPES:
            omitted_media += 1
        else:
            try:
                encoded = json.dumps(block, ensure_ascii=True, sort_keys=True)
            except TypeError:
                encoded = str(block)
            lines.append(strip_inline_data_urls(encoded))
    if omitted_media:
        plural = "s" if omitted_media != 1 else ""
        lines.append(f"[{omitted_media} inline media payload{plural} omitted]")
    return "\n".join(line for line in lines if line).strip()


def persistable_message_content(
    content: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Return content safe for DB persistence and FTS indexing.

    Multimodal provider blocks are collapsed to readable text plus stable
    attachment reference lines from metadata. This avoids storing base64 media
    in ``chat_messages.content`` while preserving enough context for reloads,
    search, and later turns.
    """
    if isinstance(content, list):
        text = _text_from_blocks(content)
        refs = attachment_refs_from_metadata(metadata)
        ref_lines = [_ref_line(ref) for ref in refs]
        if ref_lines:
            text = "\n".join([part for part in (text, "\n".join(ref_lines)) if part]).strip()
        return text
    if isinstance(content, str):
        return strip_inline_data_urls(content)
    try:
        return strip_inline_data_urls(json.dumps(content, ensure_ascii=True, sort_keys=True))
    except TypeError:
        return strip_inline_data_urls(str(content))


def search_index_text(content: Any) -> str:
    """Best-effort searchable text for legacy stored content."""
    if isinstance(content, str):
        raw = content.strip()
        if raw.startswith("[") and '"type"' in raw:
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, list):
                return _text_from_blocks(parsed)
        return strip_inline_data_urls(content)
    if isinstance(content, list):
        return _text_from_blocks(content)
    return persistable_message_content(content)


# ── `B1290`: a recording given as sound, on its own turn only ───────────────

SOUND_PART = "input_audio"


def has_sounds(messages: Iterable[Any]) -> bool:
    """Whether any message carries a recording as sound (`input_audio`)."""
    for message in messages or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list) and any(
                isinstance(p, dict) and p.get("type") == SOUND_PART for p in content):
            return True
    return False


def without_sounds(messages: list, *, keep_last_user: bool = False) -> list:
    """`messages` with every `input_audio` part taken out — but the newest
    user message's when `keep_last_user`. A message left with text alone is
    its text, the shape `build_user_content` gives a message with no media.

    `B1290`. A recording goes to a model as sound on the turn it is attached
    to, because only that turn's model was asked whether it hears
    (`chat_helpers.audio_answer`). Left in the history it would be sent again
    to whatever model the chat is on next — most local servers refuse an audio
    part and fail the whole turn — and the reply to it already says what was
    heard; its text part still names the recording. Copies; never mutates the
    session's own messages."""
    if not has_sounds(messages):
        return messages
    keep = -1
    if keep_last_user:
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], dict) and messages[index].get("role") == "user":
                keep = index
                break
    out = []
    for index, message in enumerate(messages):
        content = message.get("content") if isinstance(message, dict) else None
        if index == keep or not isinstance(content, list) or not any(
                isinstance(p, dict) and p.get("type") == SOUND_PART for p in content):
            out.append(message)
            continue
        parts = [p for p in content if not (isinstance(p, dict) and p.get("type") == SOUND_PART)]
        if all(isinstance(p, dict) and p.get("type") == "text" for p in parts):
            parts = "\n".join(str(p.get("text") or "") for p in parts).strip()
        out.append({**message, "content": parts})
    return out


# ── `B2132`: an earlier turn's files go with that turn, not every turn after ──

#: Metadata key on a saved user message that carried attachments: what the
#: person wrote, without the files' text folded in after it.
SAID_WITH_ATTACHMENTS = "said_with_attachments"

EARLIER_ATTACHMENT_NOTE = (
    "[The attached file's contents went with this message and are not sent "
    "again. If they are needed now, ask the person to attach it again or to "
    "name it.]"
)

_KIND_WORDS = (r"attachments?|files?|pdfs?|docs?|documents?|images?|pictures?|photos?|"
               r"screenshots?|spreadsheets?|sheets?|uploads?|markdown|md|csv|slides?|"
               r"deck|scan|attached")
_REFERS_TO_AN_ATTACHMENT = re.compile(
    r"\b(?:the|that|this|those|these|my|your|same|attached|uploaded)\s+(?:\w+\s+)?(?:"
    + _KIND_WORDS + r")\b"
    r"|\b(?:i|we)\s+(?:just\s+)?(?:sent|attached|uploaded|shared|gave)\b",
    re.IGNORECASE)


def _plain_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text") or "") for p in content
                         if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _named_in(text: str, ref: dict[str, Any]) -> bool:
    name = str(ref.get("name") or "").strip().lower()
    if not name or not text:
        return False
    stem = name.rsplit(".", 1)[0] if "." in name else name
    low = text.lower()
    return name in low or (len(stem) >= 4 and stem in low)


def earlier_attachments_as_references(messages: list) -> list:
    """`messages` with each earlier user turn's attachments sent as their
    reference lines, not their contents; the newest user message whole.

    `B2132`. The owner, 2026-11-15: *"Ensure documents and other storage
    materials aren't constantly passed to the LLM per turn ... unless
    explicitly attached/called upon by the user ... This includes documents,
    markdowns, pdf's, images etc... the whole suite."* Measured before this: a
    PDF's extracted text (24,000 characters by default, up to half the model's
    window) is folded into the message it came with, and that message went in
    every later request of the chat; a picture's base64 too, while the session
    stayed in memory.

    An earlier turn keeps its files when the newest message calls on them: by
    the file's name, or as "the PDF", "that screenshot", "the file I sent"
    (then the newest turn with files). Copies; never mutates the session."""
    last_user = next((i for i in range(len(messages) - 1, -1, -1)
                      if isinstance(messages[i], dict) and messages[i].get("role") == "user"
                      and not (messages[i].get("metadata") or {}).get("source")), -1)
    if last_user < 0:
        return messages
    asked = _plain_text(messages[last_user].get("content"))
    carrying = [i for i in range(last_user)
                if isinstance(messages[i], dict) and messages[i].get("role") == "user"
                and attachment_refs_from_metadata(messages[i].get("metadata"))]
    if not carrying:
        return messages
    keep = {i for i in carrying
            if any(_named_in(asked, r) for r in attachment_refs_from_metadata(messages[i].get("metadata")))}
    if not keep and _REFERS_TO_AN_ATTACHMENT.search(asked or ""):
        keep = {carrying[-1]}
    out = list(messages)
    for i in carrying:
        if i in keep:
            continue
        message = messages[i]
        metadata = message.get("metadata") or {}
        refs = attachment_refs_from_metadata(metadata)
        said = metadata.get(SAID_WITH_ATTACHMENTS)
        content = message.get("content")
        if isinstance(said, str):
            words = said.strip()
        elif isinstance(content, list):
            # Saved before `B2132`, still in memory: the pictures and sounds
            # go; the text, which holds the person's words and the files'
            # folded together, stays as it was.
            words = _plain_text(content).strip()
        else:
            continue
        lines = [words] if words else []
        lines += [_ref_line(r) for r in refs]
        lines.append(EARLIER_ATTACHMENT_NOTE)
        out[i] = {**message, "content": "\n".join(lines)}
    return out
