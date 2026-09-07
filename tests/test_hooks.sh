#!/usr/bin/env bash
# Scenario tests for the handoff hooks. Runs in throwaway repos under mktemp.
# Usage: tests/test_hooks.sh   (exit 0 = all pass)
set -u
export HAMSTER_LM=0   # scenario tests stay deterministic; the model is covered by tests/test_lm.py
HOOKS="$(cd "$(dirname "$0")/.." && pwd)/hooks"
LOAD="python3 $HOOKS/handoff-load.py"
PRE="python3 $HOOKS/handoff-precompact.py"
fail=0; pass=0
ok()   { pass=$((pass+1)); echo "  ok   $1"; }
bad()  { fail=$((fail+1)); echo "  FAIL $1"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }

T=$(mktemp -d); cd "$T"
git init -q -b feature/demo; git config user.email t@t; git config user.name t
echo hi > a.txt; git add a.txt; git commit -qm "init secret=notreally"; echo more >> a.txt
cat > tr.jsonl <<'J'
{"type":"user","message":{"role":"user","content":"fix login; key sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789 and postgres://u:p@h/db"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Reading auth.rb"},{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/x/app/auth.rb"}}]}}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"ok"}]}}
{"type":"user","message":{"role":"user","content":"<div> not rendering, fix it"}}
{"type":"user","isMeta":true,"message":{"role":"user","content":"meta"}}
{"type":"user","message":{"role":"user","content":"<command-name>/compact</command-name>"}}
{"type":"user","message":{"role":"user","content":"ruled out cookies, use sessions"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Done; tests green. eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"}]}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"ls"}}]}}
J
pre(){ echo "{\"cwd\":\"$T\",\"transcript_path\":\"$T/tr.jsonl\",\"trigger\":\"$1\"}" | $PRE; }
load(){ echo "{\"cwd\":\"$T\",\"source\":\"${1:-startup}\"}" | $LOAD; }

echo "# precompact"
pre auto; SNAP=$(/bin/ls .claude/handoffs/*auto-snapshot.md 2>/dev/null | head -1)
check "writes timestamped snapshot" '[ -n "$SNAP" ] && [[ "$SNAP" =~ [0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}-feature-demo-auto-snapshot ]]'
check "exclude line added" 'grep -qx ".claude/handoffs/" .git/info/exclude'
check "git status clean of handoffs" '! git status --short | grep -q .claude'
check "anthropic key redacted" '! grep -q "sk-ant" "$SNAP"'
check "conn string redacted" '! grep -q "u:p@h" "$SNAP"'
check "jwt redacted" '! grep -q "eyJhbGci" "$SNAP"'
check "commit message redacted" '! grep -q "secret=notreally" "$SNAP"'
check "<div> prompt kept" 'grep -q "<div> not rendering" "$SNAP"'
check "wrapper/meta/tool_result dropped" '! grep -qE "command-name|^[0-9]+\. meta|tool_result" "$SNAP"'
check "assistant message labelled with turn" 'grep -q "after user prompt 3 of 3" "$SNAP"'
sleep 1; touch -d 2020-01-01 "$SNAP" 2>/dev/null || touch -t 202001010000 "$SNAP"
SNAP1=".claude/handoffs/2020-01-01-0000-feature-demo-auto-snapshot.md"; mv "$SNAP" "$SNAP1"
pre auto; N=$(/bin/ls .claude/handoffs/*auto-snapshot.md | wc -l | tr -d ' ')
check "second snapshot does not overwrite first" '[ "$N" -ge 2 ]'
for i in 1 2 3 4 5 6; do cp "$SNAP1" ".claude/handoffs/2020-01-0$i-000$i-feature-demo-auto-snapshot.md"; done
pre auto; N=$(/bin/ls .claude/handoffs/*auto-snapshot.md | wc -l | tr -d ' ')
check "pruned to 5 per branch" '[ "$N" -eq 5 ]'
HANDOFF_FRESH_MINUTES=off pre auto; check "bad env fails open (exit 0)" '[ $? -eq 0 ]'
rm -f .claude/handoffs/*; pre auto; pre auto; N=$(/bin/ls .claude/handoffs/*auto-snapshot.md | wc -l | tr -d ' ')
check "same-minute snapshot gets a suffix, not overwritten" '[ "$N" -eq 2 ] && /bin/ls .claude/handoffs | grep -qE "^[0-9-]+\.2-feature-demo-auto-snapshot"'
for i in 1 2 3 4 5 6 7; do printf -- '---\nstatus: auto-snapshot\nbranch: demo\n---\n' > ".claude/handoffs/2020-01-0$i-000$i-demo-auto-snapshot.md"; done
pre auto; N=$(/bin/ls .claude/handoffs/*-demo-auto-snapshot.md | grep -vc feature-demo | tr -d ' ')
check "prune ignores other branch with suffix-matching slug" '[ "$N" -eq 7 ]'
git branch -q up && git branch -q -u up && pre auto && git branch -q --unset-upstream
check "snapshot omits '0 commits ahead' when even with upstream" '! grep -q "0 commit(s) ahead" "$(/bin/ls -t .claude/handoffs/*feature-demo-auto-snapshot.md | head -1)"'
HANDOFF_SNAPSHOT_PROMPTS=0 pre auto; L=$(/bin/ls -t .claude/handoffs/*auto-snapshot.md | head -1)
check "prompt capture opt-out" 'grep -q "capture disabled" "$L" && ! grep -q "ruled out cookies" "$L"'
rm -f .claude/handoffs/*

echo "# loader"
check "silent with empty dir" '[ -z "$(load)" ]'
printf -- '---\nstatus: active\nupdated: 9999-12-31T00:00\n---\nEVIL no branch\n' > .claude/handoffs/evil.md
check "file without branch ignored" '! load | grep -q EVIL'
printf -- '---\nstatus: active\nbranch: feature/demo\nupdated: 2026-01-01T09:00\n---\nOLD-MANUAL\n' > .claude/handoffs/m.md
printf -- '---\nstatus: auto-snapshot\nbranch: feature/demo\nupdated: 2026-01-01T12:00\n---\nNEW-SNAP\n' > .claude/handoffs/s.md
OUT=$(load compact)
check "newer snapshot loads alongside manual" 'grep -q OLD-MANUAL <<<"$OUT" && grep -q NEW-SNAP <<<"$OUT"'
check "manual printed first" '[ "$(grep -n -E "OLD-MANUAL|NEW-SNAP" <<<"$OUT" | head -1)" != "${OUT##*NEW-SNAP}" ] && [ $(grep -n OLD-MANUAL <<<"$OUT" | cut -d: -f1) -lt $(grep -n NEW-SNAP <<<"$OUT" | cut -d: -f1) ]'
check "untrusted banner present" 'grep -q "not instructions" <<<"$OUT"'
printf -- '---\nstatus: active\nbranch: feature/demo\nupdated: 9999-01-01T00:00\n---\nFUTURE\n' > .claude/handoffs/f.md
touch -t 202001010000 .claude/handoffs/f.md
check "future stamp falls back to mtime, loses" '! load | grep -q "^FUTURE"'
rm .claude/handoffs/f.md
printf -- '---\nstatus: active\nbranch: feature/demo\nupdated: 2026-02-01T00:00\n---\nTRACKED\n' > .claude/handoffs/t.md
git add -f .claude/handoffs/t.md; git commit -qm track
OUT=$(load)
check "tracked file refused with notice" '! grep -q "^TRACKED" <<<"$OUT" && grep -q "tracked by git" <<<"$OUT"'
check "untracked files still load" 'grep -q NEW-SNAP <<<"$OUT"'
git rm -q --cached .claude/handoffs/t.md; git commit -qm untrack; rm .claude/handoffs/t.md
printf -- '---\nstatus: active\nbranch: other\nupdated: 2026-03-01T00:00\n---\nOTHER\n' > .claude/handoffs/o.md
OUT=$(load)
check "other-branch active does not suppress mine" 'grep -q NEW-SNAP <<<"$OUT" && ! grep -q "^OTHER" <<<"$OUT"'
rm .claude/handoffs/m.md .claude/handoffs/s.md
check "only other-branch -> notice" 'load | grep -q "Handoffs exist for: other"'
printf '\xef\xbb\xbf---\nstatus: active\nbranch: '"'"'feature/demo'"'"'\nupdated: 2026-02-01\n---\nBOM-OK\n' > .claude/handoffs/b.md
check "BOM + single quotes parsed" 'load | grep -q BOM-OK'
rm .claude/handoffs/*.md
printf -- '---\nstatus: active\nbranch: feature/demo\nupdated: 2026-01-01T12:00+00:00\n---\nUTC-NOON\n' > .claude/handoffs/u.md
printf -- '---\nstatus: active\nbranch: feature/demo\nupdated: 2026-01-01T11:00+00:00\n---\nUTC-ELEVEN\n' > .claude/handoffs/v.md
touch -t 202001010000 .claude/handoffs/u.md .claude/handoffs/v.md
check "offset-aware stamps compare as instants" 'TZ=Asia/Tokyo load | grep -q "^UTC-NOON"'
rm .claude/handoffs/*.md
HANDOFF_LOAD_CAP= load; check "bad env fails open" '[ $? -eq 0 ]'

echo "# git edge cases"
git checkout -q --detach; pre auto; OUT=$(load compact)
check "detached HEAD round-trips" 'grep -q "detached@" <<<"$OUT" && grep -q "auto-snapshot" <<<"$OUT"'
git checkout -q feature/demo; rm -f .claude/handoffs/*
W="$T/wt"; git worktree add -q "$W" -b wt/branch
echo "{\"cwd\":\"$W\",\"transcript_path\":\"$T/tr.jsonl\",\"trigger\":\"auto\"}" | $PRE
check "worktree: snapshot written" '[ -n "$(/bin/ls "$W"/.claude/handoffs/ 2>/dev/null)" ]'
check "worktree: excluded via common dir" '! git -C "$W" status --short | grep -q .claude'
echo '{"cwd":"'"$HOME"'","transcript_path":"'"$T"'/tr.jsonl","trigger":"auto"}' | $PRE
check "never writes into \$HOME" '[ ! -d "$HOME/.claude/handoffs" ]'
echo '{"cwd":"/tmp"}' | $LOAD; check "outside git: silent, exit 0" '[ $? -eq 0 ]'

echo "# installer"
CH="$T/claude-home"; INST="$(dirname "$HOOKS")/install.sh"
mkdir -p "$CH"; CLAUDE_HOME="$CH" bash "$INST" --copy >/dev/null
check "hook command follows CLAUDE_HOME" 'grep -q "$CH/hamster-plugin/hooks/handoff-load.py" "$CH/settings.json"'
python3 - "$CH/settings.json" <<'J'
import json, sys; p=sys.argv[1]; d=json.load(open(p))
d["hooks"]["SessionStart"][0]["hooks"].append({"type":"command","command":"echo keep-me"})
json.dump(d, open(p,"w"))
J
CLAUDE_HOME="$CH" bash "$INST" --uninstall >/dev/null
check "uninstall keeps unrelated sibling hook" 'grep -q keep-me "$CH/settings.json" && ! grep -q handoff- "$CH/settings.json"'
CLAUDE_HOME="$CH" bash "$INST" --copy >/dev/null; CLAUDE_HOME="$CH" bash "$INST" --uninstall >/dev/null
check "uninstall on default-shaped install leaves no hook block" '! grep -q handoff- "$CH/settings.json"'

echo; echo "passed=$pass failed=$fail"; cd /; rm -rf "$T"; exit $fail
