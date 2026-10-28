# SPDX-License-Identifier: AGPL-3.0-or-later
"""
image_gen_server.py

MCP server exposing image generation via OpenAI-compatible APIs.
"""

import asyncio
import base64
import sys
import uuid
from pathlib import Path

from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp_tool_server import serve_stdio, tool_server  # noqa: E402

from src.constants import GENERATED_IMAGES_DIR
# `B1357` / `D-2026-10-14-01` §1: one register, and this server derives
# from it like the email server does.
from src.tool_schemas import mcp_tool_schema
from src.paced_http import guard_environment_reader

# `B1013`: this server is its own process, and its client reads the environment
# Pantheon started it with — an IPv6 range in NO_PROXY would stop it being built.
guard_environment_reader()


async def list_tools() -> list[Tool]:
    return [
        Tool(**mcp_tool_schema("generate_image"))
    ]


async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "generate_image":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    prompt = arguments.get("prompt", "")
    model_spec = arguments.get("model", "")
    size = arguments.get("size", "1024x1024")
    quality = arguments.get("quality", "medium")

    if not prompt:
        return [TextContent(type="text", text="Error: Image prompt is required")]

    try:
        import httpx
        from src.settings import load_settings, get_setting
        from src.ai_interaction import _resolve_model

        if not get_setting("image_gen_enabled", True):
            return [TextContent(type="text", text="Error: Image generation is disabled by the administrator.")]

        _settings = load_settings()

        if not model_spec:
            model_spec = _settings.get("image_model", "")
        if quality == "medium" and _settings.get("image_quality"):
            quality = _settings["image_quality"]

        # Auto-detect best available image model
        if not model_spec:
            for candidate in ("gpt-image-1.5", "gpt-image-1", "dall-e-3"):
                try:
                    await asyncio.to_thread(_resolve_model, candidate)
                    model_spec = candidate
                    break
                except ValueError:
                    continue
            if not model_spec:
                return [TextContent(type="text", text="Error: No image model found. Configure one in Admin.")]

        try:
            url, model_id, headers = await asyncio.to_thread(_resolve_model, model_spec, model_type="image")
        except ValueError:
            _lower_model_spec = model_spec.lower()
            if not any(_name in _lower_model_spec for _name in ("gpt-image", "dall-e")):
                raise
            url, model_id, headers = await asyncio.to_thread(_resolve_model, model_spec)

        is_gpt_image = "gpt-image" in model_id.lower()
        base_url = url.replace("/chat/completions", "").replace("/v1/messages", "").rstrip("/")
        images_url = base_url + "/images/generations"

        valid_gpt_sizes = {"1024x1024", "1024x1536", "1536x1024", "auto"}
        valid_dalle3_sizes = {"1024x1024", "1024x1792", "1792x1024"}
        if is_gpt_image and size not in valid_gpt_sizes:
            size = "1024x1024"
        elif not is_gpt_image and size not in valid_dalle3_sizes:
            size = "1024x1024"

        payload = {"model": model_id, "prompt": prompt, "n": 1, "size": size}
        if is_gpt_image:
            payload["quality"] = quality if quality in ("low", "medium", "high", "auto") else "medium"

        from src import paced_http   # `B1014`
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0),
                                     mounts=paced_http.direct_mounts(images_url)) as client:
            resp = await client.post(images_url, json=payload, headers=headers)

            if resp.status_code != 200:
                error_text = resp.text[:500]
                try:
                    err_json = resp.json()
                    error_text = err_json.get("error", {}).get("message", error_text) if isinstance(err_json.get("error"), dict) else str(err_json.get("error", error_text))
                except Exception:
                    pass
                return [TextContent(type="text", text=f"Error: Image generation failed ({resp.status_code}): {error_text}")]

            data = resp.json()
            images = data.get("data", [])
            if not images:
                return [TextContent(type="text", text="Error: No images returned from API")]

            img = images[0]
            image_url = None
            # Prefix the instance's public base URL (existing app_public_url setting) so the
            # link is fully-qualified and clickable when the model echoes it. Empty = relative
            # same-origin path (unchanged default).
            _pub_base = (get_setting("app_public_url", "") or "").rstrip("/")

            if img.get("b64_json"):
                img_dir = Path(GENERATED_IMAGES_DIR)
                img_dir.mkdir(parents=True, exist_ok=True)
                filename = f"{uuid.uuid4().hex[:12]}.png"
                img_path = img_dir / filename
                img_path.write_bytes(base64.b64decode(img["b64_json"]))
                image_url = f"{_pub_base}/api/generated-image/{filename}"

                # Save to gallery
                try:
                    from src.database import SessionLocal, GalleryImage
                    db = SessionLocal()
                    db.add(GalleryImage(
                        id=str(uuid.uuid4()),
                        filename=filename,
                        prompt=prompt,
                        model=model_id,
                        size=size,
                        quality=payload.get("quality", "medium"),
                    ))
                    db.commit()
                    db.close()
                except Exception:
                    pass

            elif img.get("url"):
                image_url = img["url"]
            else:
                return [TextContent(type="text", text="Error: Unexpected image API response format")]

            # "Direct link:" rather than an "image_url:" label — small models copied the
            # label token ("image_url") into the link href, producing a broken link.
            result = (
                f"Generated image for: {prompt[:100]}\n"
                f"Direct link: {image_url}\n"
                f"model: {model_id}\nsize: {size}"
            )
            return [TextContent(type="text", text=result)]

    except httpx.TimeoutException:
        return [TextContent(type="text", text="Error: Image generation timed out (300s)")]
    except ValueError as e:
        return [TextContent(type="text", text=f"Error: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


# `B621`: mcp 2.x has no `@server.list_tools()` / `@server.call_tool()`; the
# two functions above are handed to the SDK in `src/mcp_tool_server.py`.
server = tool_server("image_gen", list_tools, call_tool)


async def run():
    await serve_stdio(server)


if __name__ == "__main__":
    asyncio.run(run())
