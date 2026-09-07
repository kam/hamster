#!/usr/bin/env python3
"""SessionStart hook: one line on the rule set, plus up to three Navigator
`solutions` titles for this repo when the CLI is on PATH. Silent when there
are no rules and no hits. Fails open. HAMSTER_RECALL=0 disables."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rules import iter_rules, load_fires, load_rules  # noqa: E402
from _store import navigator_search  # noqa: E402

STALE_DAYS = 60


def main():
    if os.environ.get("HAMSTER_RECALL", "1") == "0":
        return
    data = json.load(sys.stdin)
    cwd = data.get("cwd") or os.getcwd()
    rules = load_rules(cwd)
    fires = load_fires()
    active = list(iter_rules(rules))
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)
    stale, untested = [], []
    for r in active:
        if r.get("_untested"):
            untested.append(r["id"])
        rec = fires.get(r["id"]) or {}
        created = r.get("created", "")
        try:
            old = datetime.fromisoformat(created).replace(tzinfo=timezone.utc) < cutoff
        except ValueError:
            old = False
        if old and not rec.get("count"):
            stale.append(r["id"])
    lines = []
    if active:
        line = f"hamster: {len(active)} rule(s) active"
        if untested:
            line += f"; {len(untested)} untested → warn-only ({', '.join(untested[:3])})"
        if stale:
            line += f"; {len(stale)} never fired in {STALE_DAYS}d → /hamster:rules to prune"
        if rules.get("_errors"):
            line += f"; {len(rules['_errors'])} invalid file(s) skipped"
        lines.append(line)
    project = os.path.basename(cwd.rstrip("/"))
    hits = navigator_search(None, limit=3, source_project=project)
    if hits:
        lines.append("hamster: earlier lessons for this project (navigator get <slug>):")
        lines += [f"  - {slug} — {title}"[:160] for slug, title in hits]
    if lines:
        print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
