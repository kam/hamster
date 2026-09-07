"""Optional on-device summariser: Apple Foundation Models via native/hamster-lm.

The slot is a function, `ask(prompt, instructions, max_tokens)`, that returns a
string or None. None means "no local model — let the in-session model do it".
Backend lookup: $HAMSTER_LM (explicit binary), else <plugin>/native/hamster-lm,
else `hamster-lm` on PATH. HAMSTER_LM=0 disables. Availability is probed once
per process with `--check` and cached in ~/.claude/hamster/lm-check.json for a
day so hooks don't pay the probe on every call.

The model's context is ~4k tokens, so prompts are clipped at INPUT_CHARS
(≈ 3k tokens at 4 chars/token) — callers pass the *tail* of long inputs.
Rule authoring never goes through here; that stays with the frontier model.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import state_dir  # noqa: E402

INPUT_CHARS = 12_000
TIMEOUT = float(os.environ.get("HAMSTER_LM_TIMEOUT", "20"))
CHECK_TTL = 86_400


def binary():
    env = os.environ.get("HAMSTER_LM")
    if env == "0":
        return None
    if env:
        return env if os.access(env, os.X_OK) else None
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).resolve().parent.parent)
    local = Path(root) / "native" / "hamster-lm"
    if os.access(local, os.X_OK):
        return str(local)
    return shutil.which("hamster-lm")


def available():
    b = binary()
    if not b:
        return False
    cache = state_dir("lm-check.json")
    try:
        rec = json.loads(cache.read_text(encoding="utf-8"))
        if rec.get("binary") == b and time.time() - rec.get("ts", 0) < CHECK_TTL:
            return bool(rec.get("ok"))
    except (OSError, ValueError):
        pass
    try:
        ok = subprocess.run([b, "--check"], capture_output=True, timeout=10).returncode == 0
    except Exception:
        ok = False
    try:
        cache.write_text(json.dumps({"binary": b, "ok": ok, "ts": time.time()}), encoding="utf-8")
    except OSError:
        pass
    return ok


def ask(prompt, instructions=None, max_tokens=400):
    """Reply text, or None when no local model is usable. Never raises."""
    if not prompt or not available():
        return None
    prompt = prompt[-INPUT_CHARS:]
    cmd = [binary(), "--max-tokens", str(max_tokens)]
    if instructions:
        cmd += ["--instructions", instructions]
    try:
        out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=TIMEOUT)
    except Exception:
        return None
    text = out.stdout.strip()
    return text if out.returncode == 0 and text else None


# Prompts the hooks and commands share, so a phrasing fix lands everywhere.
CLUSTER_INSTRUCTIONS = (
    "You group tool-call errors from a coding session by root cause. Output only lines of the "
    "form `<count>x <cause> — <likely fix, under 10 words>`, most frequent first, at most 5 lines."
)
SESSION_INSTRUCTIONS = (
    "You summarise a coding session for a future reader. Output markdown with exactly these "
    "headings: `## Goal`, `## Decisions` (each with its why), `## Problems solved`, "
    "`## Open loops`. Bullets, no preamble, keep names, paths and numbers exact."
)
LESSON_INSTRUCTIONS = (
    "You draft a durable lesson from repeated tool errors. Output two lines: `Why:` the cause "
    "pattern behind the errors, and `How to apply:` the rule to follow next time. Under 60 words."
)
