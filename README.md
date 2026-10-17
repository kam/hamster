# hamster — the wheel

A self-learning loop for [Claude Code](https://code.claude.com). It captures what went wrong, asks for the lesson once, keeps your working state across compaction, and turns lessons into deterministic hook rules that are proven by tests and pruned when they stop firing.

```
run ──► fail ──► capture ──► retro ──► lesson ──► promote ──► rule + keep-test ──► prune
 ▲                                        │                        │
 └──────────── handoff carries state ─────┘      rule-guard blocks the next repeat
```

The premise: a lesson that lives as prose gets forgotten. A lesson that lives as a hook does not. Every rule needs a test that shows it blocks the bad shape and passes the good one; a blocking rule without both runs warn-only. User and project rules that never fire for 60 days are listed for deletion; bundled rules and rules marked `keep: true` are exempt — a hard-safety rule that never fires is doing its job.

## What you get

| Piece | Event | Does |
|---|---|---|
| `hooks/tool-failure-log.py` | PostToolUseFailure | One JSONL line per failed tool call, `~/.claude/hamster/session-errors/` |
| `hooks/error-retro.py` | Stop | After 8 new errors, blocks the stop once and asks for the one durable lesson. Fingerprint ledger says "seen in N sessions across M projects". |
| `hooks/rule-guard.py` | PreToolUse Bash/Edit/Write | Applies every rule; `block` = exit 2 with the message, `rewrite` = the call runs substituted (`updatedInput`) and Claude is told what ran, `warn` = note. Counts fires. |
| `hooks/wake-guard.py` | PreToolUse SendMessage | Blocks, once, a message to a sub-agent idle past its ~5-minute cache with 60k+ tokens; states the re-write cost. The same send again within 10 minutes passes. `HAMSTER_WAKE_GUARD=0` disables. |
| `hooks/stale-guard.py` | UserPromptSubmit | Blocks, once, the first prompt into a chat idle past its ~1-hour cache with 100k+ tokens; states the cost and the choice (`/clear`, or send again). Slash commands pass. `HAMSTER_STALE_GUARD=0` disables. |
| `hooks/rules-recall.py` | SessionStart | One line: rules active, untested, stale. Plus earlier Navigator lessons for this repo. |
| `hooks/memory-prune.py` | SessionStart | Archives auto-memory files whose `decay_days` elapsed; sweeps old markers |
| `hooks/handoff-load.py` / `handoff-precompact.py` | SessionStart / PreCompact | The [claude-handoff](https://github.com/kam/claude-handoff) pair, now bundled |
| `hooks/decision-capture.py` | UserPromptSubmit | A pasted email, or a long paste with a decision cue, is redacted and saved once by sha to `.claude/decisions/sources/` (git-excluded); the model is told to record it in `docs/decisions.md`. Chat cues ("agreed", "go with") nudge at most 3 times a session, only where a log exists. No model call. `HAMSTER_DECISIONS=0` disables capture, stop check and load. |
| `hooks/decision-stop.py` | Stop | Blocks once per saved source whose `sha:` no row cites; the model records it or says there was no decision |
| `hooks/decisions-load.py` | SessionStart | Standing `decided` rows, one line each, capped at 30 rows / 3,000 chars; proposed as a count, superseded never |
| `hooks/decision-guard.py` | PreToolUse Bash/Edit/Write/MultiEdit | Table shape on `docs/decisions.md` + archive: unique `DEC-n`, dates, status, a named person and channel on `decided`, live supersede targets, IDs unique across log and archive, no secrets in cells. Blocks shell writes to the log (best effort). Acts only on a file carrying the skill's header, so a repo's own ADR `docs/decisions.md` is untouched. Fails closed. `HAMSTER_DECISION_GUARD=off` disables |
| `skills/decisions` | `/decisions init\|record\|supersede\|archive\|mine` | The decision log; `mine` backfills `proposed` rows from past transcripts and handoffs |
| `skills/handoff` | `/handoff`, `/handoff resume`, `/handoff done` | Durable session state instead of lossy compaction |
| `/hamster:standup` | command | Where things stand: open Navigator tasks by status, the next one to pick up, what waits on humans. Read-only; handoff + git log without Navigator |
| `/hamster:retro` | command | Manual retrospective; routes each fix to rule / skill / CLAUDE.md / memory / Navigator |
| `/hamster:promote <lesson>` | command | Drafts a rule + tests from a memory, Navigator node or text; installs only when green |
| `/hamster:rules` | command | Fire counts, untested rules, prune candidates (deletion needs your click) |
| `/hamster:test` | command | Keep-tests for every rule + hook scenario tests |
| `/hamster:lm` | command | Point the local-model slot at your server; pick fast + quality models |
| `rules/default/` | bundled | `rm -rf` on root/home, `chmod 777`, force-push to protected branches (named, or bare `--force` while on one) |

State lives in `~/.claude/hamster/`. The decision log is committed and shared: the session-start load strips markup and labels rows as context, but treat it like any file teammates can push to. Project rules live in `<repo>/.claude/hamster/rules/` and are meant to be committed.

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

`files_exist` is the stack check (Gemfile = Ruby, Cargo.toml = Rust) — no language list to maintain. `path_glob` scopes Edit/Write rules to a folder (`*` stops at `/`, `**` crosses directories; Bash has no path, so `path_glob` is rejected there); `branch` / `branch_not` relax or tighten by branch. `keep: true` exempts a rule from pruning; `created` defaults to the file's date.

A mechanical fix — a flag to quote, a prefix to add — is a `rewrite` rule: `replace` is a Python `re.sub` template over the pattern's groups, the hook substitutes it and the call runs as rewritten, and its tests expect `rewrite` with the exact `output`. Something a human must change course on stays `block`.

```json
{
  "id": "unquoted-include-glob",
  "tool": "Bash", "field": "command",
  "pattern": "((?:^|\\s)--(?:include|exclude|exclude-dir|glob)=)(?!['\"])([^\\s'\"\\\\{}]*[*?\\[][^\\s'\"\\\\{}]*)",
  "action": "rewrite",
  "replace": "\\1\"\\2\"",
  "message": "zsh globs an unquoted --include=*.md; quoted for you.",
  "tests": [
    {"input": "grep -rn --include=*.md foo .", "expect": "rewrite", "output": "grep -rn --include=\"*.md\" foo ."},
    {"input": "grep -rn --include='*.md' foo .", "expect": "pass"}
  ]
}
```

A rewrite is emitted as PreToolUse `updatedInput`; Claude sees the rule's message and the command that ran as `additionalContext`, the transcript keeps the original. When another hook (RTK) also rewrites the call, which `updatedInput` wins is undocumented — on Claude Code 2.1.302 hamster's was applied every time; a `block` in the same call always wins over a rewrite.

`python3 scripts/rules.py add rule.json` validates, runs the tests, and refuses on red. `check Bash "<cmd>"` is a dry run. Heredoc bodies that are data never trip a pattern; bodies piped to a shell do.

## Navigator

When the [`navigator`](https://github.com/kam/navigator) CLI is on `PATH`, hamster reads and writes cross-project lessons as `solutions` nodes and session records as `sessions` nodes: the retro lists matching solutions as "already recorded", `/handoff done` files a session node, `/hamster:promote` back-links the node with `promoted_to`, and session start shows this repo's earlier lessons. Without it everything falls back to Claude Code auto-memory. Nothing writes the vault markdown directly.

`/hamster:standup` reads the repo's `task` nodes to orient a session and writes none: hamster owns session state and lessons, not work state. Claiming a task belongs to the workflow that gates the work (dev-lead's `/next-task` in a code repo); elsewhere the stand-up prints the one `navigator update` line and leaves it to you.

## Local model (any server, or Apple on-device)

hamster drafts the cheap steps at zero API tokens: the retro's error grouping and lesson draft, and the pre-compaction session summary. `hamster-lm-ask session|cluster|lesson|nudge|save-session` exposes the same chain to skills and other plugins (the `nudge` "worth remembering?" verdict and `save-session` JSON are for those callers; hamster itself does not use them). Order: **your server → Apple on-device (macOS 26+) → the in-session model.**

Inside hooks a model call is capped at `HAMSTER_LM_HOOK_TIMEOUT` (8 s) so a cold server falls through instead of eating the hook's budget; the pre-compaction snapshot is written before the summary is attempted.

```bash
/hamster:lm                 # probes oMLX :8000, LM Studio :1234, Ollama :11434, llama.cpp :8080; pick a fast + quality model
python3 scripts/lm.py set --url http://127.0.0.1:1234/v1 --fast <id> --quality <id>   # or by hand; any OpenAI-compatible server
scripts/build-native.sh     # optional: compiles native/hamster-lm (Apple Foundation Models) as the zero-setup fallback
```

`hamster-lm-ask` is linked into `~/.local/bin` by `install.sh`, `/hamster:lm`, or `scripts/install-shims.sh`. Config lives in `~/.claude/hamster/config.json`. Keys are never stored — only an env var name (`--api-key-env`) or a file reference (`--api-key-file ~/.omlx/settings.json#auth.api_key`). `HAMSTER_LM=0` turns the slot off. Every draft is labelled unverified; the frontier model still corrects it, and rule authoring never goes through a local model.

**Optional decision model for `nudge`.** On oMLX 0.7.1+, add `"decision": "<id>"` (for example `Jundot--clef-flash-oQ4e`) to `server.models` by hand. Decision models are hidden from `/models`, so `lm.py set` cannot validate the id. With it set, the decision model answers the yes/no at `POST /v1/systemone` (a probability against 0.4) and the fast tier writes the topic only after a yes. Any failure falls back to the single generative call. The CLI budgets the whole chain at `HAMSTER_NUDGE_TIMEOUT` (7 s), under the memory-vault Stop hook's 8 s kill. Author's eval, 2026-10-12: Clef-flash 16/16 at 0.16 s; the 35B wrote a specific topic on 8/8 yes cases.

Why two tiers (author's eval, 2026-09-08, Opus as blind judge): a Qwen 3.6-35B-A3B MoE gave 16/16 on the yes/no nudge at 0.4 s — as fast as Apple's on-device model, as accurate as Haiku 4.5; a Qwen 3.8-27B dense model beat Haiku 6-0 on session-summary JSON. Apple's on-device model lost every task, so it is the fallback, not the default.

## Install

Marketplace: add the repo to a marketplace and enable `hamster`; Claude Code wires `hooks/hooks.json` itself.

Plain:

```bash
git clone https://github.com/kam/hamster.git && cd hamster
./install.sh            # symlink; --copy to copy; --uninstall to remove
```

Requires `python3` and `git`. Restart Claude Code. The installer copies commands and skills with the plugin path filled in, so commands are `/hamster-standup`, `/hamster-retro`, `/hamster-promote`, `/hamster-rules`, `/hamster-test`, `/hamster-lm`, `/handoff` (the marketplace forms are `/hamster:standup` … and `/hamster:handoff`). Rerun `./install.sh` after editing a command or skill.

## pi

`package.json` is a [pi](https://github.com/earendil-works/pi-coding-agent) package: `pi/extensions/hooks-bridge.ts` replays `hooks/hooks.json` inside pi (PreToolUse, Stop, SessionStart; PostToolUseFailure and PreCompact have no pi equivalent, so the error retro and auto-snapshot are Claude Code only), and `commands/` doubles as the prompt set. Active where `enabledPlugins["hamster@…"]` is true in `.claude/settings.json`.

## Tests

```bash
python3 scripts/rules.py test && bash tests/test_hooks.sh && python3 -m pytest -q tests
```

## Roadmap

- A `when.cmd_exit` gate for PostToolUse rules (react to a failing command, not just its shape).

## Why

Voyager (2023) kept skills as code, not prose. Agent Workflow Memory (2024) induced reusable workflows from past runs. Reflexion (2023) wrote a lesson after each failure. CoALA (2023) named the memory type: procedural. Practitioners hit the same wall: learned rules pile up in prompts and rot. hamster's answer is the keep-test — a rule with no failing test is deleted, and a rule that never fires is retired.

MIT.
