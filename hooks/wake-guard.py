#!/usr/bin/env python3
"""PreToolUse hook on SendMessage: stop the lead waking an idle agent.

A sub-agent's prompt cache lives ~5 minutes. A message to one that has sat
longer re-writes its whole context at cache-write price before it reads a
word (measured 2026-09: 73 of 81 sub-agent cold rewrites followed an incoming
message). First attempt → exit 2 with the cost and the cheaper move (fresh
spawn with a short brief). The same send repeated within 10 minutes passes, so
an agent holding state that cannot be re-briefed is still reachable.
Fails open. HAMSTER_WAKE_GUARD=0 disables; HAMSTER_WAKE_IDLE_S and
HAMSTER_WAKE_MIN_TOKENS tune the thresholds.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cache import cold, confirmed  # noqa: E402
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
    if not hit or confirmed("wake-guard.json", f"{data.get('session_id')}:{to}"):
        return
    tokens, minutes, dollars = hit
    print(
        f"hamster blocked [wake-guard]: agent '{to}' has been idle {minutes} min holding "
        f"{tokens // 1000}k tokens; its cache is cold, so this message re-writes all of it "
        f"(~${dollars:.2f}) before the agent reads a word. Spawn a fresh agent with a short "
        f"brief (paste the prior report's conclusions) instead. If only this agent can do it, "
        f"send the same message again within 10 minutes and it will pass.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
