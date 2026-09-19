---
description: Turn a lesson (auto-memory name, Navigator solutions slug, or free text) into a deterministic hamster rule with keep-tests. Refuses to install a blocking rule that is not proven.
argument-hint: <memory-name | solutions/slug | "text"> [--scope user|project]
---

Promote a lesson into a rule the `rule-guard` hook enforces without the model's help. A rule earns its place only if a test proves it blocks the bad shape and passes the good one.

## 1. Read the lesson

`$ARGUMENTS` is one of:
- an auto-memory name → read `~/.claude/projects/<cwd-slug>/memory/<name>.md`
- `solutions/<slug>` → `navigator get solutions/<slug>`
- free text → use as-is

Extract the **shape** the lesson forbids: a command pattern, a path, a flag, a file being edited. If the lesson is about judgement (when to ask, how to plan) and has no textual shape a regex can catch, stop and say so in one line — it stays a memory, not a rule.

## 2. Draft the rule

Write `/tmp/hamster-rule-<id>.json` in this format (`${CLAUDE_PLUGIN_ROOT}/rules/default/*.json` are examples):

```json
{
  "id": "kebab-id",
  "tool": "Bash",                 // or Edit | Write | ["Edit","Write"]
  "field": "command",             // Bash: command; Edit/Write: file_path or content
  "pattern": "<python regex>",    // add "flags": "i" for case-insensitive
  "action": "block",              // or warn
  "message": "<what to do instead, one sentence>",
  "source": "memory:<name>" | "solutions/<slug>" | "text",
  "keep": false,                  // true = never listed for pruning (hard-safety rules)
  "tests": [
    {"input": "<the exact bad shape>", "expect": "block"},
    {"input": "<a near-miss that must still work>", "expect": "pass"}
  ]
}
```

At least one `block` and one `pass` test (that is what makes a rule *tested*); add more `pass` tests than you think you need — each is a legitimate command the rule must not touch. Prefer `warn` when the bad shape is sometimes right.

## 3. Prove it, then install

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rules.py add /tmp/hamster-rule-<id>.json --scope user
```

Optional `when` gate (`files_exist`, `path_glob` for Edit/Write, `branch`, `branch_not`) narrows where the rule applies; see the README.

`--scope project` writes to `<repo>/.claude/hamster/rules/` (committed, shared with the team) — use it when the lesson is about this repo only. The command refuses on any red test or a duplicate id; fix the pattern, never the test, and rerun. Then `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rules.py check Bash "<bad shape>"` once more as a live confirmation.

## 4. Link back

- Memory source: add `promoted_to: rule/<id>` under `metadata:` in the memory file's frontmatter (Read it first, then Edit).
- Navigator source: `navigator update solutions/<slug> --set promoted_to=rule/<id> --actor agent:claude-code`.

Report in three lines: rule path, the tests run, where the back-link went. The rule is live on the next tool call — hooks reload rules on every call.
