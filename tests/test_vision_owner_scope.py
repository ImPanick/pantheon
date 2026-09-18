# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

from src import ai_interaction
from src import document_processor as dp


ROOT = Path(__file__).resolve().parents[1]


def test_configured_vision_model_resolution_passes_owner(monkeypatch):
    seen = []

    def fake_resolve_model(spec, owner=None):
        seen.append((spec, owner))
        return ("http://example.test/chat/completions", spec, {"Authorization": "Bearer token"})

    monkeypatch.setattr(ai_interaction, "_resolve_model", fake_resolve_model)

    assert dp._resolve_vl_model("gpt-4o", owner="alice") == (
        "http://example.test/chat/completions",
        "gpt-4o",
        {"Authorization": "Bearer token"},
    )
    assert seen == [("gpt-4o", "alice")]


def test_auto_detected_vision_model_resolution_passes_owner(monkeypatch):
    seen = []

    def fake_resolve_model(spec, owner=None):
        seen.append((spec, owner))
        if spec == "llava":
            return ("http://example.test/chat/completions", spec, {})
        raise ValueError("not available")

    monkeypatch.setattr(ai_interaction, "_resolve_model", fake_resolve_model)

    assert dp._resolve_vl_model("", owner="alice") == (
        "http://example.test/chat/completions",
        "llava",
        {},
    )
    assert seen
    assert all(owner == "alice" for _spec, owner in seen)


def test_vision_analysis_uses_owner_scoped_primary_and_fallback(monkeypatch, tmp_path):
    seen = {}

    def fake_resolve_vl_model(configured, owner=None):
        seen["primary"] = (configured, owner)
        return ("http://primary.test/chat/completions", "vision-primary", {"X-Test": "1"})

    def fake_fallbacks(owner=None):
        seen["fallback_owner"] = owner
        return []

    def fake_llm_call(url, model, messages, headers=None, timeout=None):
        seen["llm"] = (url, model, headers, timeout, messages)
        return "description"

    monkeypatch.setattr(dp, "_load_vl_settings", lambda: {"vision_enabled": True, "vision_model": "gpt-4o"})
    monkeypatch.setattr(dp, "_resolve_vl_model", fake_resolve_vl_model)
    monkeypatch.setattr(dp, "llm_call", fake_llm_call)

    from src import endpoint_resolver

    monkeypatch.setattr(endpoint_resolver, "resolve_vision_fallback_candidates", fake_fallbacks)

    image = tmp_path / "image.png"
    image.write_bytes(b"not-a-real-png-but-base64-is-enough")

    assert dp.analyze_image_with_vl_result(str(image), owner="alice") == {
        "text": "description",
        "model": "vision-primary",
    }
    assert seen["primary"] == ("gpt-4o", "alice")
    assert seen["fallback_owner"] == "alice"
    assert seen["llm"][:4] == (
        "http://primary.test/chat/completions",
        "vision-primary",
        {"X-Test": "1"},
        120,
    )


# `B763`. This used to assert seven one-line spellings — `"_process_pdf(path,
# owner=owner)" in processor_source` and six like it. `P12-04` threaded a
# `ceiling=` argument through `_process_pdf` and black-wrapped both call sites
# across two lines, and the test went red for a change that kept every `owner=`
# exactly where it was. The property it defends is real and load-bearing: a
# vision call without an owner resolves somebody else's model. The property is
# *"every call site passes `owner=`"*, and a source substring is only one
# spelling of it (`Law 20`).
#
# Parsed, so a reformat, a line wrap or a new keyword argument cannot break it,
# and so a call site added tomorrow is covered without anybody remembering to
# add a line here — which the substring version could never do.

_OWNER_SCOPED = (
    "analyze_image_with_vl_result",
    "analyze_image_with_vl",
    "_process_pdf",
    "_resolve_vl_model",
)

_OWNER_SCOPED_FILES = (
    "src/chat_handler.py",
    "src/document_processor.py",
    "routes/upload_routes.py",
    "routes/document/document_routes.py",
    "routes/gallery/gallery_routes.py",
    "routes/memory/memory_routes.py",
)


def test_request_vision_call_sites_pass_owner():
    import ast

    missing = []
    found = 0
    for rel in _OWNER_SCOPED_FILES:
        path = ROOT / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in _OWNER_SCOPED:
                continue
            found += 1
            if not any(kw.arg == "owner" for kw in node.keywords):
                missing.append(f"{rel}:{node.lineno} {name}")

    assert found >= 7, (
        f"only {found} owner-scoped vision calls found across {len(_OWNER_SCOPED_FILES)} "
        "files — the population shrank, which is either a deletion or a rename")
    assert not missing, (
        "a vision call resolves the model without an owner, so it answers with "
        "somebody else's: " + ", ".join(missing))
