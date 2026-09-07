#!/usr/bin/env bash
# Put hamster's local-model entry points on PATH so other plugins can use them
# without knowing the config: hamster-lm-ask <mode> < text  (summarize.py)
#                              hamster-lm (Apple on-device binary, when built)
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/.local/bin"
ln -sf "$HERE/scripts/summarize.py" "$HOME/.local/bin/hamster-lm-ask"
[ -x "$HERE/native/hamster-lm" ] && ln -sf "$HERE/native/hamster-lm" "$HOME/.local/bin/hamster-lm"
echo "linked ~/.local/bin/hamster-lm-ask$([ -x "$HERE/native/hamster-lm" ] && echo ' and hamster-lm')"
