APPROVED — the r5 recursion is gone in all three copies, nothing the shell runs is hidden, legit heredocs still strip, and every suite passes.
Spec: NO-SPEC — patch-lane fix branches; no task node.
Deferred decisions: none

**Per repo**
- **dev-lead** (`fix/heredoc-opener-in-a-closed-substitution`, b4a1ef5): APPROVED. 177 tests OK (46.5s).
- **hamster** (`fix/heredoc-opener-context`, b94fd4e): APPROVED. 221 passed (28.5s).
- **bash-guard** (`/tmp/claude-bash-guard`, `fix/bash-guard-heredoc-delimiter`, 4d43e80): APPROVED. 82 of 82 pass.

**Checks you asked for**
- **Six shared functions:** `_scan_line`, `_push`, `_depth`, `_opener_hidden`, `_ctx_top` and `_body_follows` are byte-identical across the three copies. I compared them by AST source segment (`/tmp/hdreview6/cmp.py`).
- **Recording at the first `i >= start`:** this is exact, because no token can straddle `start`. In git-guard, `start = m.end()` falls just past a word character, `.`, `-` or a closing quote. The `(?=[\s;&|<>()]|$)` lookahead also rules out a trailing `\`. In bash-guard and hamster, `start` falls just past `\w+` plus an optional closing quote. Every multi-character token (`$(`, `$((`, `((`, `$'`, `<(`, `))`) starts with `$`, `(`, `<`, `>` or `)`. None of those can be the last character of the delimiter, and a three-character token would need both of the two characters before `start` to be `$(`. The `escaped` flag is not recorded, but it only affects the next character and not the stack or quote state, so this is harmless. If a straddle ever did happen (unreachable today), the recorded state would be the state after the token. That is the unsafe direction, so it would not fail safe. Any change to the regex that lets a delimiter end in `$`, `<`, `>` or `(` would reopen this; see the Low finding.
- **`$((echo a)` rewrite with identity comparison:** these combine safely.
  - The rewrite builds a new node, so a rewrite after the opener breaks identity, the opener is dropped, and the body stays visible.
  - A rewrite before the opener is the recorded node, so a legit body still strips.
  - Identity alone already implies nothing at or below the recorded depth changed. A pop can only return to `rest`, and every push builds a new node. The min-depth test is a redundant backstop.
  - `"))"` entries are always 2-tuples, so the rewrite drops no `_ctx_top` link.
  - Probes in `/tmp/hdreview6/r6.py` (17 cases, all three copies agree):
    - Rewrite before the opener: the body strips.
    - Rewrite in the line's closing `)`: the body stays visible.
    - Arithmetic or plain paren holding the opener: visible.
    - `x="$(cat <<EOF)"`: visible.
    - Close then reopen (`$(cat <<EOF) $(`): visible.
    - Quote left open after the opener: visible.
    - Closed `<(`: visible.
    - Quoted, double-quoted, `<<-` delimiters, inside `$(`, two openers on one line, a trailing comment, and an escaped `\$(`: all strip correctly.
- **Other comparisons or recursion over the linked stack:** I found none.
  - The only remaining comparison is `next_ctx[:2] == (None, None)` at `hooks/git-guard.py:766`. A tuple compared with None returns at once, without walking the chain.
  - Line 720 tests `[0][0] is None`.
  - No `repr`, `%r`, `!r`, hash, set or dict key touches a context in any of the three files.
  - Deallocation is safe: CPython's tuple dealloc uses the trashcan. Freeing a 200k-deep chain plus `gc.collect()` took 4 ms, with no crash.
- **Nothing hidden, timing:**
  - `rec.py`: bash-guard and hamster exit 2 on all five deep shapes. git-guard exits 0 as before, because it has no rm rule.
  - `fn.py`: everything is visible. The 200k case takes 0.20s in git-guard.
  - `r4.py` matches round 4. `p.py` stays at 0.05s or less.
  - `r4t.py`: worst case is git-guard at 1.07s on 600 KB. bash-guard is 0.03s or less and hamster 0.11s or less.
  - My deep probes (`/tmp/hdreview6/deep.py`) ran three shapes at 60k and 200k: open body, closed on the same line, and a deep rewrite. The command after the terminator stays visible every time. The worst case is 0.69s (git-guard, 200k rewrite, which goes over budget so nothing strips, which is safe). Through each hook end to end, a 60k line ending in `rm -rf ~` blocks: bash-guard in 0.06s, hamster in 0.42s.

### Critical
None.

### High
None.

### Medium
None.

### Low
- **Straddle safety rests on the delimiter regex, and the code doesn't say so.** Files: `hooks/git-guard.py:486-488` and `_body_follows` (git-guard about 667; bash-guard about 150; hamster `_rules.py` about 174). Exact recording depends on the delimiter never ending in a character that starts a multi-character token. Widening `_HEREDOC_RE` or `_HEREDOC` (for example, for the zsh spellings you listed as out of scope) could make the recorded state the post-token state, which is the unsafe direction. Fix: one line in the `_body_follows` docstring stating the invariant, or record before processing when `i + token length > start`. Confidence: high that it is safe today, medium on future risk.
- **[Scope] Out-of-scope files on the hamster branch.** Commit 5851bf7 adds six `pi/prompts/*.md` mirrors (`lm`, `promote`, `retro`, `rules`, `standup`, `test`). The dev-lead branch likewise touches `pi/prompts/next-task.md`, `pi/prompts/ship.md` and `package.json`. These are generator output in their own commit and harmless, but they are unrelated to the heredoc fix. Fix: keep them in this PR deliberately or split them off. Confidence: high.

### Nitpick
- **The 60000-deep tests prove no crash, not correct stripping.** Locations: `hooks/test_guards.py` (r5 case), the bash-guard `test_bash_guard.py` r5 tuple, and hamster `tests/test_rules.py`. In all three the blocked command sits on the line before the deep line, so they show the line is decided without an error but not that the deep heredoc is handled right. Fix: add a variant with the blocked command after the terminator (`"echo " + "$(" * 60000 + " cat <<E\nbody\nE\n<blocked cmd>"`). My probe shows it passes in all three. Confidence: high.
- **Redundant min-depth test.** `low[1] == _depth(stack)` in `_body_follows` is implied by `stack is low[2][1]`. Keeping it as a backstop is reasonable; a one-word comment would stop a future reader from wondering. Confidence: high.

Probes: `/tmp/hdreview6/cmp.py`, `/tmp/hdreview6/r6.py`, `/tmp/hdreview6/deep.py`. The repos were not edited.
