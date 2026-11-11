# Review: Fable 5.2 cache-write price

- **Verdict:** APPROVED
- **Date:** 2026-11-11
- **Branch:** `fix/fable-5-2-cache-write-price`, commit `5fbfbf8`
- **Reviewer:** `general-purpose` sub-agent on `opus`, separate from the session that wrote the diff. `dev-lead:code-reviewer` is not enabled in the `~/.claude` project.

## Change

`hooks/_cache.py` priced every `fable` model at Fable 5.1's 5-minute cache-write price ($12.50/M). Fable 5.2 lists at $8/M input, so its write price is $10/M. The commit adds `"fable-5-2": 10.0` ahead of `"fable"` and one test row.

## Rounds

This commit was reviewed together with a design-skills prompt change.

- **Round 1:** the joint verdict was REQUEST-CHANGES, for the design-skills change only. On this commit the reviewer wrote "can merge as is": the price matches Anthropic's pricing page (read 2026-11-11), the key order gives `claude-fable-5-2` 10.0 and leaves `claude-fable-5-1` and `claude-fable-5` at 12.5, `_cache.write_price` is the only price table in the repo, and `python3 -m pytest tests -q` gave 224 passed.
- **Round 2:** APPROVED on the joint change. This commit was unchanged and the round-2 reviewer did not re-read it.

## Follow-ups, not fixed here

- **Low, pre-existing:** no `mythos` key, so Mythos models fall through to the Opus default of 6.25. The page lists Mythos 5.2 at $10 and Mythos 5.1 and 5 at $12.50.
- **Low, pre-existing:** `stale-guard.py` prices a reload after the 1-hour cache expires at the 5-minute write rate. If Claude Code writes 1-hour cache there, the 1-hour rate (Fable 5.2 $16) is the right one. Not checked.
- **nit:** `"fable-5-2"` would also match a dated id such as `claude-fable-5-20260101`. No such id exists in the docs or local transcripts.
