APPROVED: feature/decision-log at 7c53a9f (hamster 0.7.0). pytest 171 passed, test_hooks.sh 38/38.
Reviewer: separate opus general-purpose agent; it did not write the diff. 4 rounds, 2026-10-14.
Spec: NO-SPEC. Design: docs/research/2026-10-14-decision-capture.md. Kam decided: sources gitignored, repo file only for v1.
Deferred decisions: folding decision-guard into rule-guard (one Python process per Bash/Edit/Write instead of two). Follow-up.

**Rounds**
- r1 REQUEST-CHANGES (14):
  - `\|` escape did not parse.
  - The guard fired on any repo's own `docs/decisions.md`; the header is now the opt-in.
  - `git log` pastes read as email, and CI logs read as notes.
  - Quoted text tripped the Bash write check; rm, perl -i and git checkout were missed.
  - The load banner trusted committed text.
  - Secrets could reach cells.
  - Names were rejected: "Na Li", "Ai Tanaka".
  - Stop state was one repo per session.
  - IDs were not unique across the log and archive.
  - Nested paste markers broke.
  - `.gitignore` negation was not checked.
  - State was never pruned.
- r2 REQUEST-CHANGES (6):
  - The full `redact()` on cells blocked auth decisions; the check now uses token shapes only.
  - Teams and Zoom chat prefixes read as noise.
  - `restore --staged` was blocked.
  - The bare paste marker did not match.
  - A row with no closing pipe was dropped.
  - Relative mine `--out` resolved inconsistently.
- r3 REQUEST-CHANGES (1 + 2 nits):
  - The `sk-` shape had no left boundary ("task-management-…" was flagged).
  - The shape lists are now named.
  - A bearer value must hold a digit in the cell check.
- r4 APPROVED.

**Verified by reviewer**
- The Stop hook marks sources nudged before blocking, so it cannot loop. It runs safely alongside error-retro and dev-lead handoff-stop.
- Live paste markers confirmed in real transcripts: `<pasted_content id="2327">` … `</pasted_content id="2327">`.
