#!/usr/bin/env python3
"""PreToolUse hook: apply hamster rules to the tool call.

`block`   → exit 2, message on stderr (Claude sees it and must change course).
`rewrite` → the field is substituted and the call runs rewritten: JSON on
            stdout with `updatedInput` (the whole tool_input, one field
            changed) and `additionalContext` naming the rule and the command
            that ran. No `permissionDecision`: the normal permission flow
            still decides whether the rewritten call is allowed. A block in
            the same call wins and no rewrite is emitted.
`warn`    → message on stdout, call proceeds; folded into the JSON when a
            rewrite is emitted (stdout must then be JSON alone).
Another PreToolUse hook may rewrite the same call (RTK's `rtk hook claude`
turns `find`/`grep` into `rtk find`/`rtk grep`). The docs do not say how two
`updatedInput`s merge; on Claude Code 2.1.302 (2026-10-18) this plugin's
rewrite was the one applied in every live call (5/5: `find … -o`, `grep
--include=*.md`, `navigator update`), and the transcript keeps the original
command. Re-check after a Claude Code upgrade: `find x -name a -o -name b`
must list files, not exit 1 from `rtk find`.
Every hit is counted in ~/.claude/hamster/rule-fires.json so /hamster:rules
can show what earns its keep. Fails open on any internal error.
HAMSTER_GUARD=0 disables.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rules import context, evaluate, load_rules, record_fire, rewrite  # noqa: E402


def main():
    if os.environ.get("HAMSTER_GUARD", "1") == "0":
        return
    data = json.load(sys.stdin)
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return
    cwd = data.get("cwd")
    hits = evaluate(load_rules(cwd), tool, tool_input, context(cwd))
    if not hits:
        return
    blocks, warns, rewrites = [], [], []
    for rule, action in hits:
        try:
            record_fire(rule["id"])
        except Exception:
            pass
        {"block": blocks, "rewrite": rewrites}.get(action, warns).append(rule)
    if blocks:
        for r in blocks:
            print(f"hamster blocked [{r['id']}]: {r['message']}", file=sys.stderr)
        sys.exit(2)
    notes = []
    for r in warns:
        note = " (untested rule, warn-only)" if r.get("_untested") else ""
        notes.append(f"hamster warn [{r['id']}]{note}: {r['message']}")
    updated = dict(tool_input)
    changed = []
    for r in rewrites:
        field = r["field"]
        value = updated.get(field)
        if not isinstance(value, str):
            continue
        new = rewrite(r, value)
        if new is None:
            continue
        updated[field] = new
        changed.append(field)
        notes.append(f"hamster rewrote [{r['id']}]: {r['message']}")
    if not changed:
        for line in notes:
            print(line)
        return
    for field in dict.fromkeys(changed):
        notes.append(f"ran {field}: {updated[field]}")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "updatedInput": updated,
        "additionalContext": "\n".join(notes),
    }}))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
