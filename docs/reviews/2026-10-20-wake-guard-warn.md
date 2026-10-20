APPROVED WITH NITS — dev-lead:code-reviewer (opus) — 2026-10-20 — branch fix/wake-guard-warn

The hook contract is right. On PreToolUse, `hookSpecificOutput` has `hookEventName: "PreToolUse"` and `additionalContext` but no `permissionDecision` or `decision`, so the normal permission flow runs and the send goes through. The output matches hooks/rule-guard.py:93-96, which uses the same shape. Top-level `systemMessage` is valid. The fail-open wrapper is unchanged, and `HAMSTER_WAKE_GUARD=0` is still the first check. The lane limit holds: 2 files, about 45 changed lines.

- MED (Docs) README.md:20: same split as the stale-guard branch; the row and the 0.8.4 bump are on fix/rm-rf-segment. (Resolved: merged as one set.)
- LOW (Dead code) hooks/_cache.py:71: the same `confirmed()` leftovers once both branches land. (Resolved: removed on fix/rm-rf-segment.)
- LOW (Tests) tests/test_cache_guards.py test_wake_disabled_and_bad_input_fail_open: the disabled case checks only `stdout == ""`; assert `returncode == 0` too. (Resolved.)
- Nitpick: the model-facing note arrives after the send has gone through; it can still guide the next send.

Tests: `git archive fix/wake-guard-warn` into a temp dir, `python3 -m pytest tests/ -q` → 221 passed in 27.76s.
