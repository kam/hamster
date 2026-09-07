#!/usr/bin/env python3
"""Stop hook: when a session has accumulated many tool errors, block the stop
once and ask Claude to write the durable lesson to auto-memory.

Deterministic trigger (error count), model-written lesson. Fires when
>= THRESHOLD new errors have occurred since the last time it fired for this
session, and at most MAX_FIRES times per session; marker files under
~/.claude/hamster/session-errors/ remember the count seen and the fires spent.

Error source, in order: the per-session JSONL written by tool-failure-log.py
(PostToolUseFailure hook), else the transcript's is_error tool_results.

Three mechanisms borrowed from claude-reflect-system / ECC (2026-09-04):
  * fingerprint ledger — sha256 of each normalised error, kept in
    ledger.json with count / sessions / projects, so the reason can say
    "seen in N earlier sessions across M projects";
  * recurrence-gated promotion — a pattern seen in >= 2 projects is told to
    go to the Navigator store as a `solutions` node (`navigator insert`), not
    project memory (NAV-T6c, 2026-09-04);
  * existing-lesson list — feedback-type memory names + descriptions are
    passed in, so "already recorded" is a fact, not a hope.

Lessons written via this hook carry `decay_days` in frontmatter metadata so
memory-prune.py (SessionStart) can archive them when they go stale.

Input (stdin JSON): session_id, transcript_path, cwd, stop_hook_active.
Output: JSON {"decision": "block", "reason": ...} on stdout, else nothing.
Any internal error fails open (exit 0).
"""
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import has_navigator, memory_dir, state_dir  # noqa: E402
from _store import existing_lessons  # noqa: E402

THRESHOLD = int(os.environ.get("ERROR_RETRO_THRESHOLD", "8"))
# At most this many retros per session. Measured 2026-09-04: 23 fires under
# THRESHOLD=5 cost 122 extra assistant turns (~740K input tokens each) and only
# 43% produced a memory or vault write. One retro per session keeps the yield
# and drops the tax.
MAX_FIRES = int(os.environ.get("ERROR_RETRO_MAX_FIRES", "1"))
MARKER_DIR = state_dir("session-errors")
LEDGER = MARKER_DIR / "ledger.json"
SNIPPET_LEN = 140
MAX_SNIPPETS = 8
MAX_EXISTING = 15
DECAY_DAYS = 120
LEDGER_MAX = 2000


# ---------------------------------------------------------------- errors ----
def errors_from_log(session_id):
    p = MARKER_DIR / f"{session_id}.jsonl"
    if not p.exists():
        return None
    out = []
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            tool = d.get("tool") or ""
            text = d.get("error") or ""
            out.append(f"[{tool}] {text}"[:SNIPPET_LEN] if tool else text[:SNIPPET_LEN])
    return out


def errors_from_transcript(transcript_path):
    out = []
    with open(transcript_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            content = (d.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not (isinstance(block, dict) and block.get("type") == "tool_result"
                        and block.get("is_error")):
                    continue
                text = block.get("content")
                if not isinstance(text, str):
                    text = " ".join(
                        b.get("text", "") for b in (text or []) if isinstance(b, dict)
                    )
                text = re.sub(r"\s+", " ", text).strip()
                out.append(text[:SNIPPET_LEN])
    return out


# ---------------------------------------------------------- fingerprints ----
_NOISE = [
    (re.compile(r"/users/[^/\s]+"), "/users/X"),  # applied after lower()
    (re.compile(r"\b[0-9a-f]{7,40}\b"), "HEX"),
    (re.compile(r"\b\d+\b"), "N"),
    (re.compile(r"line N(?::N)?"), "line N"),
]


def fingerprint(snippet):
    s = snippet.lower()
    for rx, rep in _NOISE:
        s = rx.sub(rep, s)
    s = re.sub(r"\s+", " ", s).strip()
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def load_ledger():
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_ledger(ledger):
    if len(ledger) > LEDGER_MAX:
        items = sorted(ledger.items(), key=lambda kv: kv[1].get("last", ""))
        ledger = dict(items[-LEDGER_MAX:])
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=0, sort_keys=True), encoding="utf-8")
    os.replace(tmp, LEDGER)


def update_ledger(ledger, snippets, session_id, project):
    """Record this session's new errors; return {fp: (prior_sessions, prior_projects)}."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prior = {}
    for s in snippets:
        fp = fingerprint(s)
        rec = ledger.get(fp) or {"count": 0, "sessions": [], "projects": [],
                                 "first": now, "sample": s}
        prior_sessions = [x for x in rec["sessions"] if x != session_id]
        prior_projects = [x for x in rec["projects"] if x != project]
        prior[fp] = (len(prior_sessions), len(prior_projects))
        rec["count"] += 1
        rec["last"] = now
        if session_id not in rec["sessions"]:
            rec["sessions"] = (rec["sessions"] + [session_id])[-20:]
        if project and project not in rec["projects"]:
            rec["projects"] = (rec["projects"] + [project])[-20:]
        ledger[fp] = rec
    return prior


# ----------------------------------------------------------------- main -----
def main():
    data = json.load(sys.stdin)
    if data.get("stop_hook_active"):
        return  # we are the reason Claude continued; don't loop
    session_id = data.get("session_id") or "unknown"
    cwd = data.get("cwd") or os.getcwd()
    project = os.path.basename(cwd.rstrip("/"))

    snippets = errors_from_log(session_id)
    if snippets is None:
        transcript = data.get("transcript_path")
        if not transcript or not os.path.exists(transcript):
            return
        snippets = errors_from_transcript(transcript)
    total = len(snippets)

    MARKER_DIR.mkdir(parents=True, exist_ok=True)
    marker = MARKER_DIR / session_id
    fires_marker = MARKER_DIR / f"{session_id}.fires"
    seen = int(marker.read_text().strip() or 0) if marker.exists() else 0
    new = total - seen
    if new < THRESHOLD:
        return
    try:
        fires = int(fires_marker.read_text().strip() or 0) if fires_marker.exists() else 0
    except (OSError, ValueError):
        fires = 0
    if fires >= MAX_FIRES:
        marker.write_text(str(total))  # keep the count honest; stay silent
        return
    marker.write_text(str(total))
    fires_marker.write_text(str(fires + 1))

    new_snippets = snippets[seen:]
    ledger = load_ledger()
    prior = update_ledger(ledger, new_snippets, session_id, project)
    try:
        save_ledger(ledger)
    except OSError:
        pass

    counts = Counter(new_snippets)
    lines = []
    cross_project = False
    for s, n in counts.most_common(MAX_SNIPPETS):
        ps, pp = prior.get(fingerprint(s), (0, 0))
        tag = f"({n}x) " if n > 1 else ""
        hist = ""
        if ps:
            hist = f"  [seen in {ps} earlier session{'s' if ps != 1 else ''}"
            if pp:
                hist += f" across {pp} other project{'s' if pp != 1 else ''}"
                cross_project = True
            hist += "]"
        lines.append(f"- {tag}{s}{hist}")

    mem = memory_dir(cwd)
    top = counts.most_common(1)[0][0] if counts else None
    existing = existing_lessons(cwd, query=top, project=project)
    existing_block = ""
    if existing:
        existing_block = ("Already recorded (Navigator `solutions/…` slugs and this project's memory; "
                          "update one of these rather than adding a near-duplicate):\n"
                          + "\n".join(f"- {n}: {d}" if d else f"- {n}" for n, d in existing)
                          + "\n")

    promo = ""
    if cross_project and has_navigator():
        promo = ("At least one pattern recurred in another project: that lesson is "
                 "transferable, so save it as a Navigator `solutions` node instead of "
                 "project memory. First `navigator search \"<cause>\" --type solutions "
                 "--limit 3` and `navigator update <slug> --body - --actor agent:claude-code` "
                 "if one already covers it; otherwise\n"
                 "  printf '<Why + How to apply>' | navigator insert --type solutions "
                 f"--title \"<cause pattern>\" --tags <a,b> --source-project \"{project}\" "
                 "--body - --actor agent:claude-code\n"
                 "(the store is the shared vault; `/remember` is the same write).\n")

    reason = (
        f"error-retro hook: {new} tool errors this session since the last check "
        f"({total} total). Before stopping, do a one-step retrospective:\n"
        f"1. Find the durable lesson — the cause pattern behind the errors, not the "
        f"individual failures. Skip one-offs (typos, transient network, a single "
        f"missing Read).\n"
        f"2. If a lesson exists and is not already recorded, write ONE memory file "
        f"in `{mem}/` (auto-memory frontmatter, type feedback or project, with "
        f"**Why** and **How to apply**, and `metadata.decay_days: {DECAY_DAYS}` so it "
        f"can be pruned when stale) and add its one-line entry to MEMORY.md. "
        f"If a fix belongs in a hook, skill, or CLAUDE.md instead, say so in one "
        f"line rather than writing memory. If the lesson is a *pattern a hook could "
        f"catch* (a command shape, a path, a flag), say `/hamster:promote <name>` "
        f"is the next step.\n"
        f"3. Tell the user in one line what you saved, or that nothing was durable.\n"
        f"{promo}{existing_block}"
        f"Errors:\n" + "\n".join(lines)
    )
    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)  # fail open
