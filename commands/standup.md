---
description: Stand-up report for this repo — open tasks from Navigator by status, the next one this session can pick up, and what waits on humans. Read-only; falls back to the handoff and git log without Navigator.
---

Stand-up report for this repo: say where things stand. Read-only — this command never writes a node, claims a task, cuts a branch or creates a file. It orients the session; starting work belongs to the workflow that gates it.

## Steps

Navigator is the task record when the `navigator` CLI is on PATH. Read it fresh here — no task state carries over from a previous session.

1. **Repo.** `cat .navigator`, `git branch --show-current`, `git log --oneline -5`.
2. **Project.** With a `.navigator`, `P` is its one line; `navigator get $P --json` must resolve — if it does not, stop and report it, do not guess a slug. Without the file, look the project up and write nothing: `navigator get project/<repo dir name> --json`, then `project/<parent dir>-<repo dir name>`; use the first that resolves and whose `extras.repo` is empty or this repo's path.
3. **No Navigator.** If the CLI is absent or no project resolves, report from what the session has instead: the handoff loaded at session start (its `next_action` and Open loops; newest file for this branch in `.claude/handoffs/`), the branch, and the last five commits. Say "No Navigator project for this repo" in one line and stop.
4. **Open tasks.** One listing per status: `navigator search --type task --project $P --status <todo|doing|blocked|review> --limit 200 --json`. Query by project, never through specs — a task filed without a spec is still open work. If all four are empty, say "No open tasks in Navigator for `$P`." and stop.
5. **Read each open task.** A listing hit carries only slug, title, status, spec and tags. `navigator get task/<stem> --json` for every `doing`, `todo` and `blocked` task to read its `blocked_by`, extras and body (`review` tasks need no `get`). Past 40 open tasks, `get` every `doing` task and the `todo` tasks in step 6's order until step 8 has its answer; classify the rest from tags alone and say so.
6. **Group and order.** Group by `spec` where one exists, tasks with none under "no spec". Specs in slug order; within a spec, by the trailing `-t-<n>` ordinal; spec-less tasks last, by slug. Refer to a task by its slug, never by a position in the listing. If more than one spec has open tasks, report all of them — name each spec's status once (`navigator get spec/<stem> --json`; a `draft` spec is one line, not re-litigated).
7. **Sort out what waits on humans.** A task waiting on a person or an environment — tags `human`/`external`/`deploy`/`ops`, or a body that defers to "confirm with", "provision", "obtain", credentials, a VPS, or a third party — is *human-gated*. A `doing` task with no `extras.branch` and none of those signals is a bookkeeping gap (a session set `doing` and never recorded where the work lives), not a human wait: name it once as such.
8. **Next available.** The first `todo` task in step 6's order that is not human-gated and whose every `blocked_by` slug is `done` or `dropped` (`get` each blocker once; a blocker that does not resolve blocks).
9. **Announce:**
   - Open task count per status.
   - Any `doing` task, with its `extras.branch` when it has one — inspect that before starting anything else.
   - The next available task: slug, title, and what it unblocks.
   - `review` tasks in one line, as waiting on whatever closes them in this repo.
   - Human-gated tasks as **one line total**: "N tasks waiting on humans: T-1 provisioning, T-2 tokens, T-16 VPS." List in full only tasks this session can pick up.
10. **How to start, as the last line.** If `/next-task` is among this session's commands (dev-lead is enabled), point to it — it asks deferred decisions, claims the task and cuts the branch its guards read. Otherwise print the claim for the user to run, and do not run it: `navigator update task/<stem> --status doing --actor <whoever runs it>`.
