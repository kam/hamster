#!/usr/bin/env python3
"""UserPromptSubmit hook: say what a cold chat costs before it is paid.

The main session's prompt cache lives ~1 hour. The first prompt after a longer
gap re-writes the whole context at cache-write price (measured 2026-09: 64
such resumes, ~$77). First prompt → exit 2: the user sees the cost and the
choice (/clear for new work, or send again to continue). The next prompt
within 10 minutes passes. Slash commands always pass.
Fails open. HAMSTER_STALE_GUARD=0 disables; HAMSTER_STALE_IDLE_S and
HAMSTER_STALE_MIN_TOKENS tune the thresholds.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cache import cold, confirmed  # noqa: E402
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
    if not hit or confirmed("stale-guard.json", str(data.get("session_id"))):
        return
    tokens, minutes, dollars = hit
    idle = f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes} min"
    print(
        f"hamster [stale-guard]: this chat sat idle {idle} holding {tokens // 1000}k tokens. "
        f"Its cache is cold, so your next message pays ~${dollars:.2f} just to load it again.\n"
        f"  New topic?   /clear first (a handoff reloads by itself).\n"
        f"  Continuing?  Press up-arrow and send again; it will pass.",
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
