#!/usr/bin/env python3
"""Stop hook: a saved decision source must not end the session unrecorded.

For every source decision-capture.py saved this session, look for its
`sha:<12>` in docs/decisions.md or docs/decisions/archive.md. A source with
no citation blocks the stop once (exit 2, stderr goes to the model); it is
then marked nudged and never blocks again. Chat cues never reach this hook, so
an ordinary session never stops here.

The model may answer "no decision in it" — the block is a check, not a
demand to invent a row. Fails open. HAMSTER_DECISIONS=0 disables.
"""

import json
import os
import sys
from pathlib import Path

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _decisions import ARCHIVE, LOG, SHA_RE, load_state, read, save_state
except Exception:
    sys.exit(0)


def main():
    if os.environ.get("HAMSTER_DECISIONS", "1") == "0":
        return
    data = json.load(sys.stdin)
    if data.get("stop_hook_active"):
        return
    sid = data.get("session_id")
    state = load_state(sid)
    top = state.get("top")
    pending = [s for s in state.get("sources", []) if not s.get("nudged")]
    if not top or not pending:
        return
    cited = set()
    for rel in (LOG, ARCHIVE):
        cited |= set(SHA_RE.findall(read(Path(top) / rel) or ""))
    missing = [s for s in pending if s["sha"] not in cited]
    for s in pending:
        s["nudged"] = True
    save_state(sid, state)
    if not missing:
        return
    listing = "\n".join(f"  - {s['kind']}: {s['path']} sha:{s['sha']}" for s in missing)
    print(
        "hamster [decisions]: pasted source(s) saved this session have no row in "
        f"{LOG}:\n{listing}\n"
        "Read each one. If it records a decision, add a row citing `<path> sha:<sha>` "
        "(`decided` only with the named person, channel and date; otherwise `proposed`). "
        "If none carries a decision, say so in one line and stop — this check fires once.",
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
