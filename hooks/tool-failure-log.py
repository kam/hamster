#!/usr/bin/env python3
"""PostToolUseFailure hook: append one JSONL line per failed tool call.

Writes ~/.claude/hamster/session-errors/<session_id>.jsonl with {ts, tool, error, cwd}
so error-retro.py (Stop hook) can count and fingerprint failures from a small
file instead of re-parsing the whole transcript. Never blocks: prints nothing,
exits 0 on any error.

Payload (Claude Code >= 2.1): session_id, cwd, tool_name, tool_input, error,
optional is_interrupt, duration_ms.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import state_dir  # noqa: E402

LOG_DIR = state_dir("session-errors")
SNIPPET_LEN = 400


def main():
    data = json.load(sys.stdin)
    sid = data.get("session_id") or "unknown"
    if data.get("is_interrupt"):
        return  # user cancellations are not errors to learn from
    error = data.get("error")
    if not isinstance(error, str):
        error = json.dumps(error) if error is not None else ""
    error = re.sub(r"\s+", " ", error).strip()[:SNIPPET_LEN]
    if not error:
        return
    tool_input = data.get("tool_input") or {}
    cmd = ""
    if isinstance(tool_input, dict):
        cmd = str(tool_input.get("command") or tool_input.get("file_path") or "")[:200]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": data.get("tool_name", ""),
        "input": cmd,
        "error": error,
        "cwd": data.get("cwd", ""),
    }
    with open(LOG_DIR / f"{sid}.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
