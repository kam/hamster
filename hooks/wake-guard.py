#!/usr/bin/env python3
"""PreToolUse hook on SendMessage: price the wake of an idle agent, without blocking.

A sub-agent's prompt cache lives ~5 minutes. A message to one that has sat
longer re-writes its whole context at cache-write price before it reads a
word (measured 2026-09: 73 of 81 sub-agent cold rewrites followed an incoming
message). Until 0.8.4 the hook blocked the first send and let the repeat
through; in practice every blocked send was a round-2 brief to a reviewer or
implementer that only that agent could take (94 blocks in 10 days, 2026-10),
so the block bought a resend, not a saving. Now it exits 0 with a
`systemMessage` the user sees and an `additionalContext` note for the model.
Fails open. HAMSTER_WAKE_GUARD=0 disables; HAMSTER_WAKE_IDLE_S and
HAMSTER_WAKE_MIN_TOKENS tune the thresholds.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cache import cold  # noqa: E402
from _common import env_int  # noqa: E402


def agent_transcript(transcript_path, to):
    """Newest sub-agent transcript in this session whose name or id is `to`."""
    tp = Path(transcript_path)
    sub = tp.parent if tp.parent.name == "subagents" else tp.with_suffix("") / "subagents"
    if not sub.is_dir():
        return None
    hits = []
    for meta in sub.glob("*.meta.json"):
        log = meta.with_name(meta.name[: -len(".meta.json")] + ".jsonl")
        if not log.exists():
            continue
        named = False
        try:
            mj = json.loads(meta.read_text(encoding="utf-8"))
            named = to in (mj.get("name"), mj.get("agentType"))
        except (OSError, ValueError):
            pass
        if named or log.name.startswith((f"agent-{to}", f"agent-a{to}-")):
            hits.append(log)
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def main():
    if os.environ.get("HAMSTER_WAKE_GUARD", "1") == "0":
        return
    data = json.load(sys.stdin)
    if data.get("tool_name") != "SendMessage":
        return
    tool_input = data.get("tool_input") or {}
    to = str(tool_input.get("to") or tool_input.get("recipient") or "")
    if not to or to == "main" or not data.get("transcript_path"):
        return
    log = agent_transcript(data["transcript_path"], to)
    if not log:
        return
    hit = cold(
        log, env_int("HAMSTER_WAKE_IDLE_S", 300), env_int("HAMSTER_WAKE_MIN_TOKENS", 60000)
    )
    if not hit:
        return
    tokens, minutes, dollars = hit
    note = (
        f"hamster [wake-guard]: agent '{to}' has been idle {minutes} min holding "
        f"{tokens // 1000}k tokens; its cache is cold, so this message re-writes all of it "
        f"(~${dollars:.2f}) before the agent reads a word. A fresh agent with a short brief "
        f"is cheaper unless this one holds state that cannot be re-briefed."
    )
    print(json.dumps({"systemMessage": note, "hookSpecificOutput": {
        "hookEventName": "PreToolUse", "additionalContext": note}}))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
