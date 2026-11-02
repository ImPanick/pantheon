#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Screen grounding, measured: five scripted desktop and browser tasks, run on
one model with numbered marks off and then on, and each pass's success rate.
`D-2026-11-01-04`, Phase 1's acceptance check.

The plan's bar: *the same five scripted desktop+browser tasks run on the
owner's Gemma 12B before and after, with both success rates reported.* This
is that run. It drives the shipped `computer` and `agent_browser` tools
(`src/agent_tools/`) on a real workstation, as a real Pantheon account, and
talks to the model over the OpenAI-compatible chat API every local server
speaks (LM Studio, Ollama, llama.cpp, vLLM) — so the only thing that differs
between the two passes is `src.screen_marks.ENABLED`.

Run it inside Pantheon's container, where its settings and the workstation's
address and token are:

    docker compose exec pantheon python scripts/grounding_eval.py \\
        --endpoint http://host.docker.internal:1234/v1 \\
        --model google/gemma-3-12b --owner <your Pantheon user name> --runs 3

What each task is, how it is set up and how it is judged is in `TASKS`
below; the judge reads the workstation (a file, a folder, a request the
task's page made), never the model's own claim. Between attempts the
windows a task opened are closed and its files put back. A summary table is
printed and the whole run is written as JSON (`--out`).

The model needs vision for the screenshots (LM Studio: the model's mmproj
loaded). A model without it still gets the marks' list in words — which is
part of what this measures.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PORT = 8765
SITE = f"http://127.0.0.1:{PORT}"

FORM_HTML = """<!doctype html><meta charset="utf-8"><title>Sign up</title>
<style>body{font:16px sans-serif;margin:40px}label{display:block;margin:14px 0 4px}
input,select{font-size:16px;padding:6px}button{margin-top:18px;font-size:16px;padding:8px 18px}</style>
<h1>Sign up</h1>
<form id="f"><label for="name">Full name</label><input id="name" name="name">
<label for="plan">Plan</label><select id="plan" name="plan"><option value="free">Free</option>
<option value="pro">Pro</option><option value="team">Team</option></select>
<label><input type="checkbox" id="agree" name="agree"> I agree to the terms</label>
<button type="submit">Create account</button></form><p id="out"></p>
<script>document.getElementById('f').onsubmit=(e)=>{e.preventDefault();
const q=new URLSearchParams(new FormData(e.target));fetch('/done?'+q).finally(()=>{
document.getElementById('out').textContent='Thanks!';document.title='DONE';});};</script>"""

ITEMS_HTML = """<!doctype html><meta charset="utf-8"><title>Items</title>
<style>body{font:15px sans-serif;margin:30px}.g{display:grid;grid-template-columns:repeat(4,120px);gap:10px}
button{padding:18px 0;font-size:15px}#c{display:none;margin-top:24px;padding:10px 30px}</style>
<h1>Pick an item</h1><div class="g" id="g"></div><button id="c">Confirm</button>
<script>let picked=0;const g=document.getElementById('g');for(let i=1;i<=12;i++){const b=document.createElement('button');
b.textContent='Item '+i;b.onclick=()=>{picked=i;document.getElementById('c').style.display='inline-block';};g.appendChild(b);}
document.getElementById('c').onclick=()=>{fetch('/done?item='+picked).finally(()=>{document.title='DONE';});};</script>"""


@dataclass
class Task:
    key: str
    tool: str              # the one tool offered: "computer" or "agent_browser"
    prompt: str
    files: Dict[str, str]  # path under ~/eval -> text, written before each attempt
    judge: Callable[["Ctx"], "asyncio.Future"]


class Ctx:
    def __init__(self, client, account: str, home: str):
        self.client, self.account, self.home = client, account, home

    async def sh(self, command: str, timeout_s: float = 60.0) -> Dict[str, Any]:
        return await self.client.exec(self.account, command, timeout_s=timeout_s)

    async def text(self, rel: str) -> Optional[str]:
        try:
            got = await self.client.read(self.account, f"{self.home}/eval/{rel}")
        except Exception:  # noqa: BLE001 — a missing file is a failed task
            return None
        return got["data"].decode("utf-8", "replace")

    async def names(self, rel: str = "") -> List[str]:
        try:
            got = await self.client.list(self.account, f"{self.home}/eval/{rel}".rstrip("/"))
        except Exception:  # noqa: BLE001
            return []
        return [e["path"] for e in got.get("entries") or []]

    async def requests(self) -> str:
        return (await self.text("server.log")) or ""


async def _t1(ctx: Ctx) -> bool:
    return ((await ctx.text("t1.txt")) or "").strip() == "grounded"


async def _t2(ctx: Ctx) -> bool:
    return "t2-folder" in await ctx.names()


async def _t3(ctx: Ctx) -> bool:
    names = await ctx.names()
    return "t3-new.txt" in names and "t3-old.txt" not in names


async def _t4(ctx: Ctx) -> bool:
    log = await ctx.requests()
    return "/done?name=Ada+Lovelace&plan=pro&agree=on" in log


async def _t5(ctx: Ctx) -> bool:
    return "/done?item=7 " in await ctx.requests()


TASKS = [
    Task("desktop-terminal", "computer",
         "On the workstation's desktop, open a terminal from the panel and run this command in it: "
         "echo grounded > ~/eval/t1.txt", {}, _t1),
    Task("desktop-new-folder", "computer",
         "On the workstation's desktop, use the File Manager to make a new folder named t2-folder "
         "inside the folder called eval in your home folder.", {}, _t2),
    Task("desktop-rename", "computer",
         "On the workstation's desktop, use the File Manager to rename the file t3-old.txt, in the "
         "eval folder in your home folder, to t3-new.txt.", {"t3-old.txt": "rename me\n"}, _t3),
    Task("desktop-firefox-form", "computer",
         f"On the workstation's desktop, open Firefox, go to {SITE}/form.html and sign up with the "
         "full name Ada Lovelace, the Pro plan, and the terms box ticked, then create the account.",
         {}, _t4),
    Task("browser-pick-item", "agent_browser",
         f"In the browser, open {SITE}/items.html, pick Item 7 and confirm it.", {}, _t5),
]


# ── the model ────────────────────────────────────────────────────────────────

def _schemas(tool: str) -> List[Dict[str, Any]]:
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    return [s for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == tool]


def _system(tool: str) -> str:
    from src import screen_marks
    from src.agent_loop import COMPUTER_USE_MARKS_RULE, COMPUTER_USE_RULES
    text = "You operate a computer for the person with the tool you are given. " + COMPUTER_USE_RULES
    if tool == "computer" and screen_marks.ENABLED:
        text += COMPUTER_USE_MARKS_RULE
    if tool == "agent_browser":
        text += ("\nIn the browser, look with screenshot or read, then click or type by ref. "
                 "Say DONE when the page shows the task finished.")
    return text


async def _chat(http, args, messages, tools) -> Dict[str, Any]:
    body = {"model": args.model, "messages": messages, "tools": tools, "temperature": args.temperature,
            "max_tokens": args.max_tokens}
    headers = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}
    r = await http.post(args.endpoint.rstrip("/") + "/chat/completions", json=body, headers=headers)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def _calls(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Native tool calls, or the ones a model wrote as text in its own family's
    markup (`src/tool_parsing.py` reads every family Pantheon knows)."""
    out = []
    for c in message.get("tool_calls") or []:
        fn = c.get("function") or {}
        out.append({"id": c.get("id") or f"call_{len(out)}", "name": fn.get("name"),
                    "arguments": fn.get("arguments") or "{}"})
    if out:
        return out
    from src.tool_parsing import parse_tool_blocks
    for n, block in enumerate(parse_tool_blocks(message.get("content") or "")):
        out.append({"id": f"text_{n}", "name": block.tool, "arguments": block.content, "text": True})
    return out


async def attempt(ctx: Ctx, task: Task, args, http, owner: str) -> Dict[str, Any]:
    from src.agent_tools.browser_tools import BrowserTool
    from src.agent_tools.computer_tools import ComputerTool
    tool = ComputerTool() if task.tool == "computer" else BrowserTool()
    messages: List[Dict[str, Any]] = [{"role": "system", "content": _system(task.tool)},
                                      {"role": "user", "content": task.prompt}]
    tools = _schemas(task.tool)
    steps, errors, used_marks = 0, 0, 0
    started = time.monotonic()
    while steps < args.max_steps:
        try:
            msg = await _chat(http, args, messages, tools)
        except Exception as e:  # noqa: BLE001 — a model that fails ends the attempt, said
            return {"ok": False, "steps": steps, "why": f"model call failed: {e}"}
        calls = _calls(msg)
        assistant = {"role": "assistant", "content": msg.get("content") or ""}
        native = [c for c in calls if not c.get("text")]
        if native:
            assistant["tool_calls"] = [{"id": c["id"], "type": "function",
                                        "function": {"name": c["name"], "arguments": c["arguments"]}}
                                       for c in native]
        messages.append(assistant)
        if not calls:
            break
        for c in calls[:1]:   # one action, then look
            steps += 1
            if "mark" in str(c["arguments"]) or "ref" in str(c["arguments"]):
                used_marks += 1
            if c["name"] != task.tool:
                result = {"error": f"Only `{task.tool}` is available.", "exit_code": 1}
            else:
                result = await tool.execute(c["arguments"], {"owner": owner})
            if result.get("exit_code"):
                errors += 1
            text = result.get("output") or result.get("error") or ""
            if c.get("text"):
                messages.append({"role": "user", "content": f"Tool result:\n{text}"})
            else:
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": text})
                for extra in native[1:]:
                    messages.append({"role": "tool", "tool_call_id": extra["id"],
                                     "content": "Not run: one action at a time. Look first."})
            images = result.get("images") or []
            if images and not args.no_images:
                # Only the newest picture is kept: small models have small windows.
                for m in messages:
                    if isinstance(m.get("content"), list):
                        m["content"] = "[an earlier screenshot]"
                messages.append({"role": "user", "content": [
                    {"type": "text", "text": "The screenshot:"},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{images[0].get('mimeType') or 'image/png'};base64,{images[0]['data']}"}}]})
    ok = await task.judge(ctx)
    return {"ok": ok, "steps": steps, "errors": errors, "pointed_by_number": used_marks,
            "seconds": round(time.monotonic() - started, 1)}


# ── set-up and tidy-up on the workstation ────────────────────────────────────

CLOSE_WINDOWS = ("thunar -q 2>/dev/null; pkill -x xfce4-terminal 2>/dev/null; "
                 "pgrep -a firefox | grep -v '.pantheon/browser' | awk '{print $1}' | xargs -r kill "
                 "2>/dev/null; sleep 1; true")


async def prepare(ctx: Ctx, task: Task) -> None:
    await ctx.sh(CLOSE_WINDOWS)
    await ctx.sh("rm -rf ~/eval/t1.txt ~/eval/t2-folder ~/eval/t3-old.txt ~/eval/t3-new.txt; "
                 "mkdir -p ~/eval; : > ~/eval/server.log")
    for rel, text in task.files.items():
        await ctx.client.write(ctx.account, f"{ctx.home}/eval/{rel}", text)


async def serve_pages(ctx: Ctx) -> None:
    await ctx.client.write(ctx.account, f"{ctx.home}/eval/site/form.html", FORM_HTML)
    await ctx.client.write(ctx.account, f"{ctx.home}/eval/site/items.html", ITEMS_HTML)
    await ctx.sh(f"pkill -f 'http.server {PORT}' 2>/dev/null; cd ~/eval/site && "
                 f"setsid nohup python3 -u -m http.server {PORT} --bind 127.0.0.1 "
                 f">> ~/eval/server.log 2>&1 < /dev/null & sleep 1; true")


async def main_async(args) -> int:
    import httpx
    from src import screen_marks
    from src.workstation_access import ensure_ready

    ready = await ensure_ready(args.owner)
    home = (await ready.client.exec(ready.account, "printf %s \"$HOME\""))["stdout"].strip()
    ctx = Ctx(ready.client, ready.account, home)
    await ctx.sh("mkdir -p ~/eval")
    await serve_pages(ctx)
    picked = [t for t in TASKS if not args.tasks or t.key in args.tasks]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    results: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    async with httpx.AsyncClient(timeout=args.model_timeout) as http:
        for mode in modes:
            screen_marks.ENABLED = mode == "on"
            for task in picked:
                for n in range(args.runs):
                    await prepare(ctx, task)
                    out = await attempt(ctx, task, args, http, args.owner)
                    results.setdefault(mode, {}).setdefault(task.key, []).append(out)
                    print(f"[marks {mode}] {task.key} run {n + 1}: {'PASS' if out['ok'] else 'fail'} "
                          f"({out.get('steps')} steps)", flush=True)
    await ctx.sh(CLOSE_WINDOWS + f"; pkill -f 'http.server {PORT}'; true")
    screen_marks.ENABLED = True

    print("\nTask".ljust(26) + "".join(f"marks {m}".rjust(14) for m in modes))
    totals = {m: [0, 0] for m in modes}
    for task in picked:
        row = task.key.ljust(25)
        for m in modes:
            runs = results.get(m, {}).get(task.key, [])
            won = sum(1 for r in runs if r["ok"])
            totals[m][0] += won
            totals[m][1] += len(runs)
            row += f"{won}/{len(runs)}".rjust(14)
        print(row)
    print("Success rate".ljust(25) + "".join(
        f"{(100 * w / t if t else 0):.0f}% ({w}/{t})".rjust(14) for w, t in totals.values()))
    report = {"model": args.model, "endpoint": args.endpoint, "runs": args.runs, "modes": modes,
              "at": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results,
              "success_rate": {m: (w / t if t else 0) for m, (w, t) in totals.items()}}
    Path(args.out).write_text(json.dumps(report, indent=2))
    print(f"\nWritten to {args.out}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--endpoint", default=os.environ.get("EVAL_ENDPOINT", "http://host.docker.internal:1234/v1"),
                   help="OpenAI-compatible base URL (LM Studio's is http://<host>:1234/v1)")
    p.add_argument("--model", required=True, help="the model's name as the server lists it")
    p.add_argument("--owner", required=True, help="the Pantheon user whose workstation is used")
    p.add_argument("--api-key", default=os.environ.get("EVAL_API_KEY", ""))
    p.add_argument("--runs", type=int, default=3, help="attempts per task per mode")
    p.add_argument("--modes", default="off,on", help="off,on (the default), or one of them")
    p.add_argument("--tasks", nargs="*", help="only these task keys")
    p.add_argument("--max-steps", type=int, default=25)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--max-tokens", type=int, default=1024)
    p.add_argument("--model-timeout", type=float, default=300.0)
    p.add_argument("--no-images", action="store_true", help="send the words only (a model without vision)")
    p.add_argument("--out", default="grounding-eval.json")
    return asyncio.run(main_async(p.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
