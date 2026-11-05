APPROVED — dev-lead:code-reviewer — 2026-11-05 — fix/decision-guard-channels (dce05e9)

Spec: NO-SPEC (patch lane). Deferred decisions: none.

Correct and narrow; pytest 223 passed, tests/test_hooks.sh passed=59 failed=0. `CHANNEL_QUALIFIER_RE` strips only one trailing balanced, un-nested group; every edge case tried (`(chat)`, `pigeon (chat)`, nested, double, unclosed) passes as intended or fails safe. The decided-row named-person rule is untouched.

Critical / High / Medium: none.

Low (not taken in this patch):
- Edge cases `chat (a (b))`, `chat (a) (b)`, `chat ()` lack keep-tests (tests/test_decisions.py:192-196).
- Error message lists channels lower-cased and does not mention the qualifier (hooks/decision-guard.py:159).

Nitpick: `choice board` / `plan mode` spellings still rejected — add aliases only if real rows show them.
