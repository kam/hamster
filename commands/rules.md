---
description: List hamster rules with fire counts, flag untested and never-fired ones, and offer to prune.
---

Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rules.py list` and `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rules.py prune --days 60`. Show both outputs verbatim.

Then, for each rule with a `source` of `solutions/<slug>` and `navigator` on PATH, fetch the title with `navigator get <slug> --json` and show it beside the id (skip silently when the CLI is absent).

If the prune list is non-empty, use `AskUserQuestion` (multiSelect) listing each candidate; delete the chosen ones with `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rules.py rm <id>`. Never delete without that answer. Untested rules: say they run warn-only and offer to write the missing `block`/`pass` tests via `/hamster:promote`.
