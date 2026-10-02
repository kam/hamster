---
description: Stand-up report for this repo — open tasks from Navigator by status, the next one this session can pick up, and what waits on humans. Read-only; falls back to the handoff and git log without Navigator.
---

Stand-up report for this repo: say where things stand. Read-only — this command never writes a node, claims a task, cuts a branch or creates a file. It orients the session; starting work belongs to the workflow that gates it.

## Current State
!`cat .navigator 2>/dev/null || echo "(no .navigator file)"`
!`git branch --show-current`
!`git log --oneline -5`

## Steps

Navigator is the task record when the `navigator` CLI is on PATH. Read it fresh here — no task state carries over from a previous session.

1. **Project.** `P=$(cat .navigator)` when the file exists. When it is missing, look the project up without writing anything: `navigator get project/<repo dir name> --json`, then `project/<parent dir>-<repo dir name>`; use the first that resolves and whose `extras.repo` is empty or this repo's path. A `.navigator` that names a node `navigator get` cannot resolve is a stop: report it, do not guess a slug.
2. **No Navigator.** If the CLI is absent or no project resolves, report from what the session has instead: the handoff loaded at session start (its `next_action` and Open loops; newest file for this branch in `.claude/handoffs/`), the branch, and the last five commits. Say "No Navigator project for this repo" in one line and stop.
3. **Open tasks.** One listing per status: `navigator search --type task --project $P --status <todo|doing|blocked|review> --limit 200 --json`. Query by project, never through specs — a task filed without a spec is still open work. If all four are empty, say "No open tasks in Navigator for `$P`." and stop.
4. **Group and order.** Group by the hit's `spec` where one exists, tasks with none under "no spec". Within a spec, order by the trailing `-t-<n>` ordinal; spec-less tasks follow, by slug. Refer to a task by its slug, never by a position in the listing. If more than one spec has open tasks, report all of them — name each spec's status once (`navigator get spec/<stem> --json`; a `draft` spec is one line, not re-litigated).
5. **Resolve blockers.** `navigator get task/<stem> --json` for each `todo` task, in order, until one is unblocked: every `blocked_by` slug must be `done` or `dropped` (`get` each blocker once; a blocker that does not resolve blocks). That task is the next available.
6. **Sort before announcing.** A task waiting on a person or an environment — tags `human`/`external`/`deploy`/`ops`, or a body that defers to "confirm with", "provision", "obtain", credentials, a VPS, or a third party — is *human-gated*. A `doing` task with no `extras.branch` and none of those signals is a bookkeeping gap (a session set `doing` and never recorded where the work lives), not a human wait: name it once as such.
7. **Announce:**
   - Open task count per status.
   - Any `doing` task, with its `extras.branch` when it has one — inspect that before starting anything else.
   - The next available task: slug, title, and what it unblocks.
   - `review` tasks in one line, as waiting on whatever closes them in this repo.
   - Human-gated tasks as **one line total**: "N tasks waiting on humans: T-1 provisioning, T-2 tokens, T-16 VPS." List in full only tasks this session can pick up.
8. **How to start, as the last line.** If `/next-task` is among this session's commands (dev-lead is enabled), point to it — it asks deferred decisions, claims the task and cuts the branch its guards read. Otherwise print the claim for the user to run or approve, and do not run it: `navigator update task/<stem> --status doing --actor agent:claude-code`.
