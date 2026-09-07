---
description: Run hamster's keep-tests (every rule) and the hook scenario tests.
---

Run, in order, and show the output of each:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rules.py test
bash ${CLAUDE_PLUGIN_ROOT}/tests/test_hooks.sh
python3 -m pytest -q ${CLAUDE_PLUGIN_ROOT}/tests
```

Open with PASS or FAIL. On FAIL name the rule or test and the expected-vs-actual line; do not edit rules to make tests pass — a failing keep-test means the rule drifted, and the fix is the pattern or a deliberate removal via `/hamster:rules`.
