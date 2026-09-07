#!/usr/bin/env python3
"""summarize.py <session|cluster|lesson> < text — on-device draft via hamster-lm.

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
    SESSION_INSTRUCTIONS,
    ask,
    available,
)

MODES = {
    "session": (SESSION_INSTRUCTIONS, 700),
    "cluster": (CLUSTER_INSTRUCTIONS, 250),
    "lesson": (LESSON_INSTRUCTIONS, 150),
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in MODES:
        print(f"usage: summarize.py {{{'|'.join(MODES)}}} < text", file=sys.stderr)
        return 2
    if not available():
        print("no local model (build native/hamster-lm on macOS 26+); write the summary yourself")
        return 3
    instructions, max_tokens = MODES[sys.argv[1]]
    out = ask(sys.stdin.read(), instructions, max_tokens)
    if not out:
        print("local model returned nothing; write the summary yourself")
        return 3
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
