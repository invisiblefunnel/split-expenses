"""Replay the example conversation against a real Claude chat.

chat.html's assistant turns are written by hand. This sends the same user
messages — including the receipt as an actual image — to Claude Opus 5 with
SKILL.md as the system prompt and a bash tool pointed at a copy of the skill,
so the model records the expenses and runs scripts/settle.py itself. The
result lands in transcript.json, which is what the hand-written turns should
be checked against.

Usage:
    python3 docs/examples/replay.py --dry-run   # assemble and print, send nothing
    python3 docs/examples/replay.py             # run it, write transcript.json

Needs an Anthropic credential (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or an
`ant auth login` profile) and playwright, to photograph the receipt.
"""

import base64
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SOURCE = HERE / "chat.html"
SKILL = ROOT / "skills" / "split-expenses" / "SKILL.md"
SOLVER = ROOT / "skills" / "split-expenses" / "scripts" / "settle.py"
TRANSCRIPT = HERE / "transcript.json"

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
BASH_TIMEOUT = 30


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]
    if unknown := set(sys.argv[1:]) - {"--dry-run"}:
        raise SystemExit(f"unknown option(s): {' '.join(sorted(unknown))}")

    prompts = user_messages(SOURCE.read_text(encoding="utf-8"))
    photos = sum(p["photo"] for p in prompts)
    print(f"{len(prompts)} user messages, {photos} with a photo")

    photo = receipt_png()
    print(f"receipt photographed: {len(photo) / 1024:.0f} KB")

    system = SKILL.read_text(encoding="utf-8")
    if dry_run:
        preview(system, prompts)
        return

    transcript = converse(system, prompts, photo)
    TRANSCRIPT.write_text(json.dumps(transcript, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {TRANSCRIPT.relative_to(ROOT)}")


def user_messages(markup: str) -> list[dict]:
    """The user's side of chat.html, in order."""
    prompts = []
    for block in re.findall(r'<div class="from-user">(.*?)\n    </div>', markup, re.S):
        bubble = re.search(r'<div class="bubble">(.*?)</div>', block, re.S)
        if not bubble:
            raise SystemExit("a .from-user block has no .bubble")
        text = html.unescape(re.sub(r"\s+", " ", bubble.group(1))).strip()
        prompts.append({"text": text, "photo": 'class="photo"' in block})
    if not prompts:
        raise SystemExit("found no user messages in chat.html")
    return prompts


def receipt_png() -> bytes:
    """Photograph the receipt exactly as the reader sees it in the example."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(
            viewport={"width": 900, "height": 1400}, device_scale_factor=2
        )
        page.goto(SOURCE.as_uri())
        page.wait_for_timeout(300)
        shot = page.locator(".photo").first.screenshot()
        browser.close()
    return shot


def workspace() -> Path:
    """A scratch copy of the skill, so `python3 scripts/settle.py` resolves."""
    root = Path(tempfile.mkdtemp(prefix="split-expenses-replay-"))
    (root / "scripts").mkdir()
    shutil.copy(SOLVER, root / "scripts" / "settle.py")
    return root


def converse(system: str, prompts: list[dict], photo: bytes) -> list[dict]:
    """Send each message in turn, letting Claude run the solver as it goes."""
    import anthropic

    client = anthropic.Anthropic()
    cwd = workspace()
    print(f"bash tool rooted at {cwd}")

    tools = [{"type": "bash_20250124", "name": "bash"}]
    messages: list[dict] = []
    transcript: list[dict] = []

    for turn, prompt in enumerate(prompts, start=1):
        content: list[dict] = []
        if prompt["photo"]:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.standard_b64encode(photo).decode(),
                    },
                }
            )
        content.append({"type": "text", "text": prompt["text"]})
        messages.append({"role": "user", "content": content})

        reply, commands = exchange(client, system, tools, messages, cwd)
        transcript.append(
            {
                "turn": turn,
                "user": prompt["text"],
                "photo": prompt["photo"],
                "assistant": reply,
                "bash": commands,
            }
        )
        print(f"  turn {turn}: {len(reply)} chars, {len(commands)} command(s)")

    return transcript


def exchange(client, system, tools, messages, cwd) -> tuple[str, list[dict]]:
    """One user turn, looping until Claude stops asking to run things."""
    commands: list[dict] = []
    while True:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=tools,
            messages=messages,
            # Recommended default for Opus 5: on a policy decline the API
            # re-runs the request on a fallback model within the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise SystemExit(f"refused: {response.stop_details}")

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            text = "\n\n".join(
                b.text for b in response.content if b.type == "text"
            ).strip()
            return text, commands

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            ran = bash(block.input, cwd)
            commands.append(ran)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": ran["output"],
                    "is_error": ran["code"] != 0,
                }
            )
        messages.append({"role": "user", "content": results})


def bash(payload: dict, cwd: Path) -> dict:
    """Run one command from the model inside the scratch workspace."""
    command = payload.get("command", "")
    done = subprocess.run(
        ["bash", "-c", command],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=BASH_TIMEOUT,
    )
    return {
        "command": command,
        "code": done.returncode,
        "output": (done.stdout + done.stderr).strip(),
    }


def preview(system: str, prompts: list[dict]) -> None:
    """Show exactly what would be sent, without sending it."""
    print(f"\nmodel: {MODEL}   system: SKILL.md ({len(system)} chars)")
    print("tools: bash_20250124\n")
    for i, prompt in enumerate(prompts, start=1):
        mark = "[photo] " if prompt["photo"] else ""
        print(f"  {i}. {mark}{prompt['text']}")
    print("\n--dry-run: nothing sent.")


if __name__ == "__main__":
    main()
