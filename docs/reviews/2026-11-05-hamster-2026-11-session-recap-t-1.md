APPROVED — dev-lead:code-reviewer (opus) — 2026-11-05 — branch feature/hamster-2026-11-session-recap-t-1 — spec/hamster-2026-11-session-recap

Round 1 REQUEST-CHANGES (12 findings), round 2 APPROVED. Spec compliant on all three Acceptance items. `_transcript.py` matches the old precompact parsers, apart from a non-dict `records()` guard.

- MED (Correctness) Compaction summaries (`isCompactSummary`) were listed as prompts. (Resolved: skipped in `typed_prompt`, and tested.)
- MED (Correctness) `[Request interrupted…` markers were counted as prompts. (Resolved: added to NOT_PROMPTS, and tested.)
- MED (Tests) Nothing tested the git log time window. (Resolved: IN-WINDOW/OUT-WINDOW commits with fixed dates, also run under TZ=Pacific/Auckland.)
- MED (Correctness) A concurrent session could be recapped instead of the cleared one. (Resolved in part: headless `sdk-cli` sessions are skipped, and the concurrent-interactive limit is documented in the README and docstring. Rejected: a recent-mtime skip, because on /clear the just-cleared file is exactly the recent one.)
- LOW: UI commands crowded the prompt list; literal `<command-name>` text inside a prompt was parsed as a command; the file was read three times; commits were taken from HEAD only; a file vanishing between glob and stat killed the recap. (All resolved: SKIP_COMMANDS widened, a start-anchored command parse, a single-pass `read_session()` at about 0.12 s on a 40 MB transcript, branch-aware `commits()`, and one stat per file.)
- LOW (Security) Round 2: a transcript `gitBranch` starting with `-` could reach git as an option. (Resolved after approval: such a branch falls back to HEAD.)
- LOW: over-redaction of long path segments. (Accepted as is: harmless.)

Tests: `bash tests/test_hooks.sh` → 59 passed, 0 failed; `python3 -m pytest -q tests` → 221 passed; `uvx ruff check --config ruff.toml` on the touched hooks → clean.
