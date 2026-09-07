#!/usr/bin/env bash
# Install hamster into a plain Claude Code home without a marketplace.
#   ./install.sh            symlink the checkout to ~/.claude/hamster-plugin (edits apply live)
#   ./install.sh --copy     copy instead of symlink
#   ./install.sh --uninstall
# Skills → ~/.claude/skills/<name>, commands → ~/.claude/commands/hamster-<name>.md,
# hooks → merged into ~/.claude/settings.json from hooks/hooks.json (backup written first).
# Marketplace users don't need this: enable the plugin and Claude Code wires hooks.json itself.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CLAUDE="${CLAUDE_HOME:-$HOME/.claude}"
MODE="${1:-link}"
ROOT="$CLAUDE/hamster-plugin"

command -v python3 >/dev/null || { echo "python3 is required (hooks are Python)"; exit 1; }

if [ "$MODE" = "--uninstall" ]; then
  rm -rf "$ROOT"
  for s in "$HERE"/skills/*/; do rm -rf "$CLAUDE/skills/$(basename "$s")"; done
  rm -f "$CLAUDE"/commands/hamster-*.md
  python3 - "$CLAUDE/settings.json" "$ROOT" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]); root = sys.argv[2]
if not p.exists(): sys.exit(0)
d = json.loads(p.read_text()); h = d.get("hooks", {})
for ev in list(h):
    kept = []
    for e in h[ev]:
        e["hooks"] = [x for x in e.get("hooks", []) if root not in x.get("command", "")]
        if e["hooks"]: kept.append(e)
    h[ev] = kept
    if not h[ev]: h.pop(ev)
p.write_text(json.dumps(d, indent=2) + "\n")
PY
  echo "Removed hamster plugin, skills, commands and settings entries. State in $CLAUDE/hamster/ was left alone."
  exit 0
fi

mkdir -p "$CLAUDE/skills" "$CLAUDE/commands"
rm -rf "$ROOT"
if [ "$MODE" = "--copy" ]; then cp -R "$HERE" "$ROOT"; else ln -s "$HERE" "$ROOT"; fi
for s in "$ROOT"/skills/*/; do
  n="$(basename "$s")"; rm -rf "$CLAUDE/skills/$n"; ln -s "$ROOT/skills/$n" "$CLAUDE/skills/$n"
done
for c in "$ROOT"/commands/*.md; do
  n="$(basename "$c" .md)"; ln -sf "$ROOT/commands/$n.md" "$CLAUDE/commands/hamster-$n.md"
done

SETTINGS="$CLAUDE/settings.json"
[ -f "$SETTINGS" ] && cp "$SETTINGS" "$SETTINGS.bak-hamster-$(date +%Y%m%d%H%M%S)"
python3 - "$SETTINGS" "$ROOT" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]); root = sys.argv[2]
d = json.loads(p.read_text()) if p.exists() else {}
h = d.setdefault("hooks", {})
spec = json.loads((pathlib.Path(root) / "hooks" / "hooks.json").read_text())["hooks"]
for ev, entries in spec.items():
    for entry in entries:
        entry = json.loads(json.dumps(entry).replace("${CLAUDE_PLUGIN_ROOT}", root))
        cmds = {x["command"] for x in entry["hooks"]}
        if any(x.get("command") in cmds for e in h.get(ev, []) for x in e.get("hooks", [])):
            continue
        h.setdefault(ev, []).append(entry)
p.write_text(json.dumps(d, indent=2) + "\n")
PY
echo "Installed ($MODE) at $ROOT. Restart Claude Code. Commands: /hamster-retro, /hamster-promote, /hamster-rules, /hamster-test, /handoff."
