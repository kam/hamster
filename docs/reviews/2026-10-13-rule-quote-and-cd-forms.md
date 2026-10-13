APPROVED WITH NITS: both round-8 findings are closed and all suites pass. The residual hunt (step 2) is only partly done; see Low.
Spec: NO-SPEC. This is a review-round fix branch with no task node cited.
Deferred decisions: none.

**Verified**
- **dev-lead unchanged.** `fix/guard-residuals-2026-10` HEAD is `0d6eae9985695f277aa528ade250c6a7454f0ba3` and the working tree is clean.
- **hamster.** HEAD is `099b3f1` on `fix/rule-quote-and-cd-forms` and the tree is clean. The diff touches only `/Users/kam/Projects/smile/multiply-plugins/hamster/hooks/_rules.py`.
- **H1 closed.** In `/tmp/rv8hunt2.py`, every quoted `--pre` form now prints raw True and q True: `'--pre=sh'`, `--pre-glob` plus `--pre`, and the stdin form.
- **H2 closed.** The three `sort --compress-program` and `--comp` forms in `/tmp/rv8hunt2.py` print True/True. `sort` is no longer in `_READ_ONLY`, so any `sort` segment makes `_quotes_are_data` return False and the rule matches raw.
- **`/tmp/rv8hunt.py`** prints nothing. It only prints LOOSER lines, so none of its 7 commands loosens either rule.
- **Suites:**
  - hamster pytest: 90 passed.
  - `rules.py test`: every rule ok, 0 non-ok lines.
  - dev-lead `test_guards.py`: 144 tests OK.
- **hmatrix.** The `/tmp/devlead-audit/hmatrix.py` output matches `/tmp/devlead-audit/hmatrix-r9.txt` byte for byte (rerun saved to `/tmp/hm-r9-rerun.txt`).

### Critical
None found.
### High
None found.
### Medium
None found.
### Low
- **Residual hunt incomplete (UNVERIFIED).** A safety classifier stopped my response while I was writing new probe commands, so I ran no new raw-True/q-False probes after the round-8 scripts. The read-through of `_rules.py` below found no gap, but none of it is tested:
  - **Redirections.** `>` and `<` stay inside a segment, and the command word is still checked. `>|` splits at the `|`, so the next segment's command word is the filename. That word is not in `_READ_ONLY`, so the rule matches raw (fail-closed).
  - **Newlines.** `_SEGMENT` splits on `\n`. `_EXOTIC` rejects any backslash, so a line continuation also matches raw.
  - **Spliced options.** `--p're'=sh` becomes `--pre=sh` once quotes are stripped, and `_RUNS_CODE` catches it.
  - **Other allowlisted tools.** I know of no option that runs code in GNU or BSD grep/egrep/fgrep, head, tail, wc, uniq, cut or tr. Bash `printf -v` assigns a variable but runs nothing. ripgrep `-z`/`--search-zip` runs only fixed decompressors. Confidence: medium. I did not test whether ripgrep accepts an abbreviated `--pr`, and `_RUNS_CODE` would miss it.

  Before merge, a separate reviewer should run a short probe of those last two items (`rg --pr…` abbreviation, `-z`), using a `touch /tmp/...` payload as the brief requires.
### Nitpick
- **Docstring.** The `_rules.py` module docstring (the `flags` paragraph) still lists `sort …` among the read-only commands, but r8 H2 removed `sort` from `_READ_ONLY`. It should be updated to match. Confidence: high.

I modified no files, apart from writing `/tmp/hm-r9-rerun.txt`.

---
Round 9 of 9 (separate opus reviewer). Rounds 1-8 were REQUEST-CHANGES; each finding fixed on fix/guard-residuals-2026-10 and fix/rule-quote-and-cd-forms. Author probe after this review: rg 15.2.0 rejects abbreviated --pr (unrecognized flag), closing the reviewer's open Low.
