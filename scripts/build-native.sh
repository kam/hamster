#!/usr/bin/env bash
# Build native/hamster-lm (Apple Foundation Models CLI). macOS 26+ with Xcode 26+.
# Picks a DEVELOPER_DIR that has the FoundationModels SDK when xcode-select points at
# CommandLineTools. No-op with a notice elsewhere.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
[ "$(uname)" = "Darwin" ] || { echo "hamster-lm: macOS only, skipping"; exit 0; }
major="$(sw_vers -productVersion | cut -d. -f1)"
[ "$major" -ge 26 ] || { echo "hamster-lm: needs macOS 26+, found $(sw_vers -productVersion); skipping"; exit 0; }
for d in "${DEVELOPER_DIR:-}" "$(xcode-select -p 2>/dev/null)" /Applications/Xcode.app/Contents/Developer /Applications/Xcode-beta.app/Contents/Developer; do
  [ -n "$d" ] && [ -d "$d/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk/System/Library/Frameworks/FoundationModels.framework" ] && { export DEVELOPER_DIR="$d"; break; }
done
[ -n "${DEVELOPER_DIR:-}" ] || { echo "hamster-lm: no Xcode with the FoundationModels SDK found; skipping"; exit 0; }
swiftc -O -o "$HERE/native/hamster-lm" "$HERE/native/hamster-lm.swift"
"$HERE/native/hamster-lm" --check && echo "built $HERE/native/hamster-lm"
