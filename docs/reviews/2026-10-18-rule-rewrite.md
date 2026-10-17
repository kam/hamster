APPROVED: feature/rule-rewrite at 3a7b9f4 (hamster 0.8.0). pytest 187 passed, rules.py test 10/10, test_hooks.sh 38/38.
Reviewer: separate opus general-purpose agent; it did not write the diff. 3 rounds, 2026-10-18.
Spec: NO-SPEC. Origin: handoff 2026-10-18-main-guard-false-positives (329 October blocks from three mechanical hamster rules); Kam: "Let's work on the three hamster rules".
Scope: `rewrite` action in the rule engine (PreToolUse `updatedInput` + `additionalContext`). The three live rules at ~/.claude/hamster/rules/ were converted outside the merge, plus a new block rule `unquoted-include-brace`.

**Rounds**
- r1 REQUEST-CHANGES (3 H, 4 N):
  - H1 a match spanning blanked text outside a copied group dropped that text.
  - H2 a literal `"` inserted inside a string the shell runs executed what followed (`echo "a --include=*;id; b"` ran `id`).
  - H3 a template naming a missing group crashed test/add and failed the hook open.
  - N2 the rewritten command was not re-checked by block rules; N3 content rules missed Edit's new_string; N4 strip vs blank heredocs disagreed.
  Fixed: quotes, comments and data heredoc bodies lexed for every rewrite; wholly-inside match is data (skipped in read-only calls, refused otherwise), straddling match refused; template groups validated; rewritten input re-evaluated; new_string fallback.
- r2 REQUEST-CHANGES (1 H, 2 N):
  - H1 quotes nested inside `"$(…)"` or backticks within double quotes defeated the flat lexer; `echo "$(echo "a --include=*;id; b")"` ran `id`.
  Fixed: `_lexable` — any double-quoted span carrying `$(`, a backtick or `${`, or any `$'…'`, refuses every match in the call (blocks, the old behaviour).
- r3 APPROVED. N1 dead backtick branch in `_lexable` (applied); N2 `_lexable` is call-wide, so `x="$(date)"; grep --include=*.md` blocks where it could rewrite — accepted, safe side.

**Verified live (Claude Code 2.1.302)**: `find … -o`, `grep --include=*.md`, `navigator update` without --actor each ran rewritten (5/5 and again after r2); hamster's `updatedInput` was applied over RTK's in every call; the transcript keeps the original command. How two `updatedInput`s merge is undocumented — re-check after a Claude Code upgrade.
