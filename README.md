# hamster — the wheel

A self-learning loop for [Claude Code](https://code.claude.com). It captures what went wrong, asks for the lesson once, keeps your working state across compaction, and turns lessons into deterministic hook rules that are proven by tests and pruned when they stop firing.

```
run ──► fail ──► capture ──► retro ──► lesson ──► promote ──► rule + keep-test ──► prune
 ▲                                        │                        │
 └──────────── handoff carries state ─────┘      rule-guard blocks the next repeat
```

The premise: a lesson that lives as prose gets forgotten. A lesson that lives as a hook does not. Every rule needs a test that shows it blocks the bad shape and passes the good one; a blocking rule without both runs warn-only. Rules that never fire for 60 days are listed for deletion.

## What you get

| Piece | Event | Does |
|---|---|---|
| `hooks/tool-failure-log.py` | PostToolUseFailure | One JSONL line per failed tool call, `~/.claude/hamster/session-errors/` |
| `hooks/error-retro.py` | Stop | After 8 new errors, blocks the stop once and asks for the one durable lesson. Fingerprint ledger says "seen in N sessions across M projects". |
| `hooks/rule-guard.py` | PreToolUse Bash/Edit/Write | Applies every rule; `block` = exit 2 with the message, `warn` = note. Counts fires. |
| `hooks/rules-recall.py` | SessionStart | One line: rules active, untested, stale. Plus earlier Navigator lessons for this repo. |
| `hooks/memory-prune.py` | SessionStart | Archives auto-memory files whose `decay_days` elapsed; sweeps old markers |
| `hooks/handoff-load.py` / `handoff-precompact.py` | SessionStart / PreCompact | The [claude-handoff](https://github.com/kam/claude-handoff) pair, now bundled |
| `skills/handoff` | `/handoff`, `/handoff resume`, `/handoff done` | Durable session state instead of lossy compaction |
| `/hamster:retro` | command | Manual retrospective; routes each fix to rule / skill / CLAUDE.md / memory / Navigator |
| `/hamster:promote <lesson>` | command | Drafts a rule + tests from a memory, Navigator node or text; installs only when green |
| `/hamster:rules` | command | Fire counts, untested rules, prune candidates (deletion needs your click) |
| `/hamster:test` | command | Keep-tests for every rule + hook scenario tests |
| `rules/default/` | bundled | `rm -rf` on root/home, `chmod 777`, force-push to protected branches |

State lives in `~/.claude/hamster/`. Project rules live in `<repo>/.claude/hamster/rules/` and are meant to be committed.

## A rule

```json
{
  "id": "no-cd-into-worktree",
  "tool": "Bash",
  "field": "command",
  "pattern": "(^|[;&|]\\s*)cd\\s+\\S*\\.worktrees/",
  "action": "block",
  "message": "Use absolute paths; cd into a linked worktree drifts cwd for every later call.",
  "source": "memory:feedback_worktree_cd",
  "tests": [
    {"input": "cd .worktrees/x && ls", "expect": "block"},
    {"input": "ls .worktrees/x", "expect": "pass"}
  ]
}
```

Optional `when` gate, checked before the pattern (all keys AND-ed):

```json
"when": {"files_exist": ["Gemfile"], "path_glob": "app/**/*.rb", "branch_not": ["main"]}
```

`files_exist` is the stack check (Gemfile = Ruby, Cargo.toml = Rust) — no language list to maintain. `path_glob` scopes Edit/Write rules to a folder; `branch` / `branch_not` relax or tighten by branch.

`python3 scripts/rules.py add rule.json` validates, runs the tests, and refuses on red. `check Bash "<cmd>"` is a dry run. Heredoc bodies that are data never trip a pattern; bodies piped to a shell do.

## Navigator

When the [`navigator`](https://github.com/kam/navigator) CLI is on `PATH`, hamster reads and writes cross-project lessons as `solutions` nodes and session records as `sessions` nodes: the retro lists matching solutions as "already recorded", `/handoff done` files a session node, `/hamster:promote` back-links the node with `promoted_to`, and session start shows this repo's earlier lessons. Without it everything falls back to Claude Code auto-memory. Nothing writes the vault markdown directly.

## On-device model (macOS 26+)

```bash
scripts/build-native.sh     # compiles native/hamster-lm with the FoundationModels SDK
```

With the binary present, hamster uses Apple's on-device model for the cheap steps, at zero API tokens: the retro's error grouping and lesson first draft, a session summary inside the pre-compaction snapshot, and `scripts/summarize.py session|cluster|lesson` for `/handoff done` and `/hamster:retro`. Every output is labelled unverified; the frontier model still corrects it. Rule authoring never goes through the local model. Without the binary (or `HAMSTER_LM=0`) everything falls back to the in-session model.

## Install

Marketplace: add the repo to a marketplace and enable `hamster`; Claude Code wires `hooks/hooks.json` itself.

Plain:

```bash
git clone https://github.com/kam/hamster.git && cd hamster
./install.sh            # symlink; --copy to copy; --uninstall to remove
```

Requires `python3` and `git`. Restart Claude Code. Commands are then `/hamster-retro`, `/hamster-promote`, `/hamster-rules`, `/hamster-test`, `/handoff`.

## Tests

```bash
python3 scripts/rules.py test && bash tests/test_hooks.sh && python3 -m pytest -q tests
```

## Roadmap

- Structured output from `hamster-lm` (`@Generable`) so the cluster step returns JSON, not lines.
- A `when.cmd_exit` gate for PostToolUse rules (react to a failing command, not just its shape).

## Why

Voyager (2023) kept skills as code, not prose. Agent Workflow Memory (2024) induced reusable workflows from past runs. Reflexion (2023) wrote a lesson after each failure. CoALA (2023) named the memory type: procedural. Practitioners hit the same wall: learned rules pile up in prompts and rot. hamster's answer is the keep-test — a rule with no failing test is deleted, and a rule that never fires is retired.

MIT.
