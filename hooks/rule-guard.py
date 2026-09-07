#!/usr/bin/env python3
"""PreToolUse hook: apply hamster rules to the tool call.

`block` → exit 2, message on stderr (Claude sees it and must change course).
`warn`  → message on stdout, call proceeds. Every hit is counted in
~/.claude/hamster/rule-fires.json so /hamster:rules can show what earns its
keep. Fails open on any internal error. HAMSTER_GUARD=0 disables.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rules import context, evaluate, load_rules, record_fire  # noqa: E402


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
    blocks, warns = [], []
    for rule, action in hits:
        try:
            record_fire(rule["id"])
        except Exception:
            pass
        (blocks if action == "block" else warns).append(rule)
    for r in warns:
        note = " (untested rule, warn-only)" if r.get("_untested") else ""
        print(f"hamster warn [{r['id']}]{note}: {r['message']}")
    if blocks:
        for r in blocks:
            print(f"hamster blocked [{r['id']}]: {r['message']}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
