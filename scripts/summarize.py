#!/usr/bin/env python3
"""summarize.py <session|cluster|lesson|nudge|save-session> < text
(installed on PATH as `hamster-lm-ask` so other plugins can call it without knowing the config) — draft via the local model chain (server → AFM).

Exit 0 with the draft on stdout; exit 3 with a one-line notice when no local
model is available (the caller then writes the summary itself). Used by
/handoff done, /hamster:retro and the handoff skill; safe to call blind.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from _lm import (  # noqa: E402
    CLUSTER_INSTRUCTIONS,
    LESSON_INSTRUCTIONS,
    NUDGE_INSTRUCTIONS,
    SAVE_SESSION_INSTRUCTIONS,
    SESSION_INSTRUCTIONS,
    ask,
    available,
)

MODES = {  # mode: (instructions, max_tokens, tier)
    "session": (SESSION_INSTRUCTIONS, 700, "quality"),
    "cluster": (CLUSTER_INSTRUCTIONS, 250, "quality"),
    "lesson": (LESSON_INSTRUCTIONS, 150, "quality"),
    "nudge": (NUDGE_INSTRUCTIONS, 40, "fast"),
    "save-session": (SAVE_SESSION_INSTRUCTIONS, 400, "quality"),
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in MODES:
        print(f"usage: summarize.py {{{'|'.join(MODES)}}} < text", file=sys.stderr)
        return 2
    if not available():
        print("no local model (run `/hamster:lm` to point at a server, or build native/hamster-lm on macOS 26+); write the summary yourself")
        return 3
    instructions, max_tokens, tier = MODES[sys.argv[1]]
    out = ask(sys.stdin.read(), instructions, max_tokens, tier=tier)
    if not out:
        print("local model returned nothing; write the summary yourself")
        return 3
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
