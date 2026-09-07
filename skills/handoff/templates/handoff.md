---
status: active
branch: <branch>
project: <repo dir name>
created: <YYYY-MM-DDTHH:MM>
updated: <YYYY-MM-DDTHH:MM>
next_action: <one executable line>
tasks_file: <docs/prd/<name>.tasks.md, or omit>
---

# Handoff: <title>

## Goal and why

<One or two sentences: what this branch delivers and why it matters to the user.>

## Current state

- Branch `<branch>` at `<sha>`; <N> commits ahead of main; <clean | uncommitted: paths>
- Tests: <green | red: which>
- Merged: <what>; Open: <PR/branch>

## Constraints (the user's words)

- "<verbatim constraint, requirement, or ruling>" — <what it rules in or out>

## Decisions (with why, and options rejected)

- **<Decision>** because <why>. Ruled out <option> because <reason>. (<user's words if given>)

## Tried and failed — do not repeat

- <What> — failed because <reason>; evidence: <error text | path | figure>

## Problems solved — do not re-derive

- <Problem hit> — resolved by <fix>; <why that worked | the gotcha behind it>

## Open loops — blockers, questions, promises

- <Blocker or unanswered question, and who/what resolves it>
- Promised: <something offered or committed to the user and not yet delivered>

## Next steps

1. **<The one executable next action>**
2. <then>
3. <then, or "then `/resume`" when a tasks file exists>

## Artifacts (paths and URLs only)

- `<path>` — <what it is>
- <URL> — <what it is>

## Resume and validate

```bash
git checkout <branch> && git status --short
<test command>
```

## Audit log

- <YYYY-MM-DD HH:MM> created — <one line>
