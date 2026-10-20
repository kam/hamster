#!/usr/bin/env python3
"""UserPromptSubmit hook: say what a cold chat cost, without stopping it.

The main session's prompt cache lives ~1 hour. The first prompt after a longer
gap re-writes the whole context at cache-write price (measured 2026-09: 64
such resumes, ~$77). Until 0.8.4 the hook blocked that prompt once (exit 2)
and asked the user to resend; the cost was already committed by then, so the
block only added a resend. Now it exits 0 with a `systemMessage` the user sees
and an `additionalContext` note for the model. Slash commands always pass.
Fails open. HAMSTER_STALE_GUARD=0 disables; HAMSTER_STALE_IDLE_S and
HAMSTER_STALE_MIN_TOKENS tune the thresholds.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cache import cold  # noqa: E402
from _common import env_int  # noqa: E402


def main():
    if os.environ.get("HAMSTER_STALE_GUARD", "1") == "0":
        return
    data = json.load(sys.stdin)
    path = data.get("transcript_path")
    if not path or "/subagents/" in path or str(data.get("prompt") or "").lstrip().startswith("/"):
        return
    hit = cold(
        path, env_int("HAMSTER_STALE_IDLE_S", 3600), env_int("HAMSTER_STALE_MIN_TOKENS", 100000)
    )
    if not hit:
        return
    tokens, minutes, dollars = hit
    idle = f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes} min"
    note = (
        f"hamster [stale-guard]: this chat sat idle {idle} holding {tokens // 1000}k tokens; "
        f"its cache was cold, so this message pays ~${dollars:.2f} to reload it. "
        f"New topic? /handoff then /clear is cheaper than carrying this context."
    )
    print(json.dumps({"systemMessage": note, "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit", "additionalContext": note}}))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
