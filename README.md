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
| `/hamster:lm` | command | Point the local-model slot at your server; pick fast + quality models |
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

## Local model (any server, or Apple on-device)

hamster drafts the cheap steps at zero API tokens: the retro's error grouping and lesson draft, the pre-compaction session summary, the "worth remembering?" verdict, and `hamster-lm-ask session|cluster|lesson|nudge|save-session` for skills and other plugins. Order: **your server → Apple on-device (macOS 26+) → the in-session model.**

```bash
/hamster:lm                 # probes oMLX :8000, LM Studio :1234, Ollama :11434, llama.cpp :8080; pick a fast + quality model
python3 scripts/lm.py set --url http://127.0.0.1:1234/v1 --fast <id> --quality <id>   # or by hand; any OpenAI-compatible server
scripts/build-native.sh     # optional: compiles native/hamster-lm (Apple Foundation Models) as the zero-setup fallback
```

Config lives in `~/.claude/hamster/config.json`. Keys are never stored — only an env var name (`--api-key-env`) or a file reference (`--api-key-file ~/.omlx/settings.json#auth.api_key`). `HAMSTER_LM=0` turns the slot off. Every draft is labelled unverified; the frontier model still corrects it, and rule authoring never goes through a local model.

Why two tiers (`evals/haiku-vs-afm/REPORT.md` in kam/claude-settings, Opus blind judge): a Qwen 3.6-35B-A3B MoE gave 16/16 on the yes/no nudge at 0.4 s — as fast as Apple's on-device model, as accurate as Haiku 4.5; a Qwen 3.8-27B dense model beat Haiku 6-0 on session-summary JSON. Apple's on-device model lost every task, so it is the fallback, not the default.

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

- A `when.cmd_exit` gate for PostToolUse rules (react to a failing command, not just its shape).

## Why

Voyager (2023) kept skills as code, not prose. Agent Workflow Memory (2024) induced reusable workflows from past runs. Reflexion (2023) wrote a lesson after each failure. CoALA (2023) named the memory type: procedural. Practitioners hit the same wall: learned rules pile up in prompts and rot. hamster's answer is the keep-test — a rule with no failing test is deleted, and a rule that never fires is retired.

MIT.
