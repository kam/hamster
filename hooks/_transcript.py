"""Transcript (JSONL) parsing shared by handoff-precompact.py and session-recap.py.

Pure helpers: no git, no writes. Bad lines and missing files yield nothing.
"""

import json
import os

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
WRAPPERS = (
    "<command-name>",
    "<command-message>",
    "<local-command",
    "<system-reminder>",
    "<user-prompt-submit-hook>",
    "<task-notification",
)


def text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(
        b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"
    )


def is_tool_result(content):
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def edited_paths(content):
    """File paths touched by Edit/Write tool_use blocks in an assistant turn."""
    for block in content if isinstance(content, list) else []:
        if not (isinstance(block, dict) and block.get("type") == "tool_use"):
            continue
        if block.get("name") not in EDIT_TOOLS:
            continue
        inp = block.get("input") or {}
        fp = inp.get("file_path") or inp.get("notebook_path")
        if fp:
            yield fp


def records(transcript):
    """Parsed JSONL records from the transcript; bad lines and missing files yield nothing."""
    if not transcript or not os.path.exists(transcript):
        return
    with open(transcript, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if isinstance(rec, dict):
                yield rec


def user_prompt(rec, content):
    """The prompt text of a real user turn, else None (meta, tool_result, wrappers)."""
    if rec.get("isMeta") or is_tool_result(content):
        return None
    t = text_of(content).strip()
    return t if t and not t.startswith(WRAPPERS) else None


def scan(transcript):
    """(prompts, edited files, (last assistant text, prompt count at that point))."""
    prompts, files, last_assistant, turn = [], [], ("", 0), 0
    for rec in records(transcript):
        content = (rec.get("message") or {}).get("content")
        if rec.get("type") == "user":
            t = user_prompt(rec, content)
            if t:
                turn += 1
                prompts.append(t)
        elif rec.get("type") == "assistant":
            t = text_of(content).strip()
            if t:
                last_assistant = (t, turn)
            for fp in edited_paths(content):
                if fp not in files:
                    files.append(fp)
    return prompts, files, last_assistant

