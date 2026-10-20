APPROVED WITH NITS — dev-lead:code-reviewer (opus) — 2026-10-20 — branch fix/stale-guard-warn

The hook contract is right. It exits 0 and prints JSON with a top-level `systemMessage` (a field every hook event accepts) and `hookSpecificOutput.hookEventName: "UserPromptSubmit"` plus `additionalContext` (both valid for this event). It sets no `decision` or `continue:false`, so nothing blocks the prompt. `json` was already imported. The fail-open wrapper is unchanged and covers the new `json.dumps`, and `HAMSTER_STALE_GUARD=0` is still checked first in `main()`. The lane limit holds: 2 files, about 39 changed lines.

- MED (Docs) README.md:21: this branch does not change the README row; the corrected row is on fix/rm-rf-segment. Fix: merge all three as one set. (Resolved: merged as one set.)
- LOW (Dead code) hooks/_cache.py: `confirmed()`, `RETRY_WINDOW_S`, `import time`, `state_dir` are unused once both hook branches land. Delete in whichever branch merges last. (Resolved: removed on fix/rm-rf-segment.)
- LOW (Wording) hooks/stale-guard.py: "this message paid" → "pays". (Resolved.)
- Nitpick (Tests) the second-run assertion uses an unchanged transcript; fine as written.

Tests: `git archive fix/stale-guard-warn` into a temp dir, `python3 -m pytest tests/ -q` → 221 passed in 27.91s.
