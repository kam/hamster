#!/usr/bin/env python3
"""SessionStart hook: archive auto-memory files whose `decay_days` has elapsed.

Opt-in per file — only memories that declare `decay_days` under `metadata:`
(error-retro.py writes them that way) are ever touched. Age is measured from
the `modified` stamp Claude Code adds on write, else the file mtime. Expired
files move to `memory/_archive/` (never deleted) and their MEMORY.md line is
removed. Prints one line when something was archived; silent otherwise.

Why: two independent projects (BayramAnnakov/claude-reflect decay_days 45–180,
affaan-m/ecc PENDING_TTL_DAYS 30) converged on TTL as the answer to memory
bloat — the dominant complaint about auto-memory in 2026. Auto-memory's
200-line / 25 KB MEMORY.md cap makes stale lines actively harmful: they push
live ones off the index.

Also sweeps ~/.claude/hamster/session-errors/ — the per-session marker, .fires and
.jsonl files error-retro.py and tool-failure-log.py leave behind grow without
bound otherwise. Anything older than MARKER_MAX_AGE_DAYS goes; ledger.json and
baseline files are never touched.

Env: MEMORY_PRUNE=0 disables. Fails open.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import memory_dir, state_dir  # noqa: E402

MARKER_DIR = state_dir("session-errors")
MARKER_MAX_AGE_DAYS = 30
MARKER_KEEP = {"ledger.json", "ledger.tmp"}


def sweep_markers(now):
    """Delete stale per-session error markers. Returns the count removed."""
    if not MARKER_DIR.is_dir():
        return 0
    removed = 0
    for p in MARKER_DIR.iterdir():
        if not p.is_file() or p.name in MARKER_KEEP or p.name.startswith("baseline-"):
            continue
        try:
            age = (now - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)).days
            if age >= MARKER_MAX_AGE_DAYS:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    return m.group(1) if m else ""


def parse_date(s):
    s = s.strip().strip("'\"")
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def main():
    if os.environ.get("MEMORY_PRUNE", "1") == "0":
        return
    data = json.load(sys.stdin)
    now = datetime.now(timezone.utc)
    swept = sweep_markers(now)
    mem = memory_dir(data.get("cwd") or os.getcwd())
    if not mem.is_dir():
        if swept:
            print(f"memory-prune: removed {swept} stale session-error marker(s)")
        return
    archived = []
    for p in sorted(mem.glob("*.md")):
        if p.name == "MEMORY.md":
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = frontmatter(text)
        m = re.search(r"^\s*decay_days:\s*(\d+)", fm, re.M)
        if not m:
            continue
        decay = int(m.group(1))
        stamp = None
        mm = re.search(r"^\s*modified:\s*(.+)$", fm, re.M)
        if mm:
            stamp = parse_date(mm.group(1))
        if stamp is None:
            stamp = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        if (now - stamp).days < decay:
            continue
        archive = mem / "_archive"
        archive.mkdir(exist_ok=True)
        p.rename(archive / p.name)
        archived.append(p.name)

    if not archived:
        if swept:
            print(f"memory-prune: removed {swept} stale session-error marker(s)")
        return
    index = mem / "MEMORY.md"
    if index.exists():
        lines = index.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        keep = [l for l in lines if not any(f"({n})" in l or f"/{n}" in l for n in archived)]
        if len(keep) != len(lines):
            index.write_text("".join(keep), encoding="utf-8")
    print(f"memory-prune: archived {len(archived)} expired auto-memory file(s) to "
          f"memory/_archive/: {', '.join(archived)}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
