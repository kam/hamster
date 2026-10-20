APPROVED WITH NITS — dev-lead:code-reviewer (opus) — 2026-10-20 — branch fix/rm-rf-segment

The JSON is valid, and the pattern diff is one minimal hunk with no reformatting. The 17 original keep-tests keep their intent. Dangerous shapes still block (checked old and new patterns side by side): `rm -rf -- /`, `rm -rf "$HOME"`, `rm -rf ~/`, `rm -rf '~'`, `sudo rm -rf /`, `rm -rf foo $HOME`, `rm -rf ${HOME}`, `rm -Rf .`, `rm --recursive --force /`, `rm -rf /tmp/x;rm -rf ..`, `rm -rf foo<TAB>.` all BLOCK. The intended fixes now pass: `rm -rf /tmp/x || ls ..`, `rm -rf /tmp/x 2>/dev/null; ls .`, `rm -rf /tmp/x | tee .`. The lane limit holds: 2 non-Markdown files, 10 non-doc lines.

- MED (Correctness, newline separator) rules/default/rm-rf-root-or-home.json:5: the trailing `\s+` in `([^\s;&|]+\s+)*` still matches `\n`, so `rm -rf /tmp/x\ndu -sh .` still blocks. Fix: `([^\s;&|]+[^\S\n]+)*` plus keep-tests for the pass and block shapes. (Resolved.)
- MED (Scope) README.md:20-21 document the two hook branches; merged alone the README would describe behaviour that does not exist yet. Fix: merge the three as one set; regenerate the marketplace and commit the `chore(marketplace): hamster 0.8.4 entry` pointer. (Resolved.)
- LOW (New misses, contrived) `rm -rf "a;b" /`, `rm -rf a&b ~`, `rm -rf /tmp/a>&2 /` now pass; none is a realistic agent command. Trade-off accepted.
- LOW (Pre-existing, out of scope) `(rm -rf /)`, `rm -rf ./`, `rm -rf ../`, `rm -rf ./*` pass both old and new: `)` is not a terminator and `(/\*?)?` is missing after `\.\.?`. Follow-up.
- Nitpick: the history entry's "6 of 7 blocks in October" figure is not verified here.

Tests on the checked-out branch: `python3 scripts/rules.py test` all 10 bundled rules ok; `python3 -m pytest tests/test_cache_guards.py -q` 20 passed; JSON loads.
