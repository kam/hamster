"""Local-model slot: any OpenAI-compatible server first, Apple on-device second.

`ask(prompt, instructions, max_tokens, tier)` returns a string or None. None means
"no local model — let the in-session model do it". `tier` is "fast" (yes/no, short
labels) or "quality" (summaries, clustering); each maps to a model in config.

Config: ~/.claude/hamster/config.json (HAMSTER_STATE overrides the dir):

  {"lm": {
     "server": {"url": "http://127.0.0.1:8000/v1",
                "api_key_env": "OMLX_API_KEY",            # or
                "api_key_file": "~/.omlx/settings.json#auth.api_key",
                "models": {"fast": "<id>", "quality": "<id>"},
                "extra": {"chat_template_kwargs": {"enable_thinking": false}}},
     "afm": true }}

Keys are never written to config — only where to read one. Any OpenAI-style server
works: oMLX (:8000), LM Studio (:1234), Ollama (:11434), llama.cpp (:8080), vLLM.
`scripts/lm.py detect` finds them and `/hamster:lm` writes the config.

Order per call: server (if configured and answering) → Apple Foundation Models via
native/hamster-lm (macOS 26+) → None. Server health is probed once per process and
cached in lm-check.json for 10 minutes; a failed server call falls through to AFM.
HAMSTER_LM=0 disables everything; HAMSTER_LM=<path> forces a hamster-lm binary.

Measured 2026-09-08 (evals/haiku-vs-afm): Qwen 3.6-35B-A3B on oMLX = 16/16 on the
nudge at 0.4 s; Qwen 3.8-27B beat Haiku 6-0 on session summaries; Apple's on-device
model lost every task. Hence server first, AFM as the zero-setup fallback.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import state_dir  # noqa: E402

INPUT_CHARS_AFM = 12_000  # ~3k tokens; AFM window is 4–8k
INPUT_CHARS_SERVER = 60_000
TIMEOUT = float(os.environ.get("HAMSTER_LM_TIMEOUT", "120"))  # CLI / skills: first call may load weights
# Hooks run under Claude Code's per-hook budget (see hooks.json); a cold server must
# fall through, not kill the hook. Hooks pass timeout=HOOK_TIMEOUT to ask().
HOOK_TIMEOUT = float(os.environ.get("HAMSTER_LM_HOOK_TIMEOUT", "8"))
CHECK_TTL_AFM = 86_400
CHECK_TTL_SERVER = 600
CONFIG = state_dir("config.json")

KNOWN_SERVERS = [
    ("omlx", "http://127.0.0.1:8000/v1", "~/.omlx/settings.json#auth.api_key"),
    ("lmstudio", "http://127.0.0.1:1234/v1", None),
    ("ollama", "http://127.0.0.1:11434/v1", None),
    ("llamacpp", "http://127.0.0.1:8080/v1", None),
]


# ------------------------------------------------------------------ config ---
def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, CONFIG)


def _check_cache():
    try:
        return json.loads(state_dir("lm-check.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _check_save(d):
    try:
        state_dir("lm-check.json").write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass


# ------------------------------------------------------------------ server ---
def resolve_key(server):
    """API key from env var or `file#dotted.path`; None when neither is set."""
    env = server.get("api_key_env")
    if env and os.environ.get(env):
        return os.environ[env]
    ref = server.get("api_key_file")
    if ref:
        path, _, dotted = ref.partition("#")
        try:
            val = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
            for part in [p for p in dotted.split(".") if p]:
                val = val[part]
            return str(val) if val else None
        except Exception:
            return None
    return None


def _http(url, key=None, body=None, timeout=10):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def server_models(url, key=None, timeout=4):
    """Model ids served at <url>/models, or None when the server is not answering."""
    try:
        d = _http(url.rstrip("/") + "/models", key, timeout=timeout)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    data = d.get("data") or d.get("models") or []  # OpenAI shape; Ollama native lists `models`
    return [m.get("id") or m.get("name") for m in data if isinstance(m, dict) and (m.get("id") or m.get("name"))]


def server_ok(server):
    """Cached health: the configured server answers /models."""
    if os.environ.get("HAMSTER_LM") == "0" or not server or not server.get("url"):
        return False
    cache = _check_cache()
    rec = cache.get("server") or {}
    if rec.get("url") == server["url"] and time.time() - rec.get("ts", 0) < CHECK_TTL_SERVER:
        return bool(rec.get("ok"))
    ok = server_models(server["url"], resolve_key(server)) is not None
    cache["server"] = {"url": server["url"], "ok": ok, "ts": time.time()}
    _check_save(cache)
    return ok


def server_ask(server, prompt, instructions, max_tokens, tier, timeout=None):
    timeout = timeout or TIMEOUT
    model = (server.get("models") or {}).get(tier) or (server.get("models") or {}).get("quality")
    if not model:
        return None
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "messages": [{"role": "system", "content": instructions or ""},
                     {"role": "user", "content": prompt[-INPUT_CHARS_SERVER:]}],
    }
    body.update(server.get("extra") or {})
    key = resolve_key(server)
    text = None
    for attempt in (1, 2):  # one retry: a server that just (re)loaded a model can 5xx once
        try:
            d = _http(server["url"].rstrip("/") + "/chat/completions", key, body, timeout)
            text = d["choices"][0]["message"]["content"]
            break
        except Exception:
            if attempt == 1:
                time.sleep(1.5)
    if text is None:
        # mark the server down only when it is really gone; a bad reply with a live
        # /models keeps it configured so the next hook call tries again
        if server_models(server["url"], key) is None:
            cache = _check_cache()
            cache["server"] = {"url": server["url"], "ok": False, "ts": time.time()}
            _check_save(cache)
        return None
    text = re.sub(r"<think>.*?</think>\s*", "", text or "", flags=re.S).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return text or None


# --------------------------------------------------------------------- afm ---
def afm_binary():
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


def afm_available():
    if load_config().get("lm", {}).get("afm") is False:
        return False
    b = afm_binary()
    if not b:
        return False
    cache = _check_cache()
    rec = cache.get("afm") or {}
    if rec.get("binary") == b and time.time() - rec.get("ts", 0) < CHECK_TTL_AFM:
        return bool(rec.get("ok"))
    try:
        ok = subprocess.run([b, "--check"], capture_output=True, timeout=10).returncode == 0
    except Exception:
        ok = False
    cache["afm"] = {"binary": b, "ok": ok, "ts": time.time()}
    _check_save(cache)
    return ok


def afm_ask(prompt, instructions, max_tokens, timeout=None):
    timeout = timeout or TIMEOUT
    cmd = [afm_binary(), "--max-tokens", str(max_tokens)]
    if instructions:
        cmd += ["--instructions", instructions]
    try:
        out = subprocess.run(cmd, input=prompt[-INPUT_CHARS_AFM:], capture_output=True, text=True,
                             timeout=min(timeout, 30))
    except Exception:
        return None
    text = out.stdout.strip()
    return text if out.returncode == 0 and text else None


# ------------------------------------------------------------------ public ---
def backend():
    """'server', 'afm' or None — what ask() would use right now."""
    if os.environ.get("HAMSTER_LM") == "0":
        return None
    server = load_config().get("lm", {}).get("server")
    if server and server_ok(server):
        return "server"
    if afm_available():
        return "afm"
    return None


def available():
    return backend() is not None


def ask(prompt, instructions=None, max_tokens=400, tier="quality", timeout=None):
    """Reply text, or None when no local model is usable. Never raises.
    `timeout` (seconds) caps one model call; hooks pass HOOK_TIMEOUT."""
    if not prompt or os.environ.get("HAMSTER_LM") == "0":
        return None
    server = load_config().get("lm", {}).get("server")
    if server and server_ok(server):
        out = server_ask(server, prompt, instructions, max_tokens, tier, timeout)
        if out:
            return out
    if afm_available():
        return afm_ask(prompt, instructions, max_tokens, timeout)
    return None


# Prompts the hooks and commands share, so a phrasing fix lands everywhere.
CLUSTER_INSTRUCTIONS = (
    "You group tool-call errors from a coding session by root cause. Output only lines of the "
    "form `<count>x <cause> — <likely fix, under 10 words>`, most frequent first, at most 5 lines. "
    "Counts must add up to the number of input errors."
)
SESSION_INSTRUCTIONS = (
    "You summarise a coding session for a future reader. Output markdown with exactly these "
    "headings: `## Goal`, `## Decisions` (each with its why), `## Problems solved`, "
    "`## Open loops`. Bullets, no preamble, keep names, paths and numbers exact. Only state "
    "what the input supports."
)
LESSON_INSTRUCTIONS = (
    "You draft a durable lesson from repeated tool errors. Output two lines: `Why:` the cause "
    "pattern behind the errors, and `How to apply:` the rule to follow next time. Under 60 words."
)
NUDGE_INSTRUCTIONS = (
    "You judge whether a coding assistant's recent messages contain knowledge worth saving for "
    "future projects: a root cause, a workaround, a gotcha, a config or API fact that was hard "
    "to find. Ordinary progress reports, file edits and plans do not count. Answer on one line: "
    "`YES: <topic in under 12 words>` or `NO`."
)
SAVE_SESSION_INSTRUCTIONS = (
    'From this Claude Code session data, output ONLY a JSON object with keys: "title" (5-10 words, '
    'what was accomplished), "summary" (2-3 sentences), "accomplishments" (array of 2-5 strings), '
    '"decisions" (array of 0-3 strings), "tags" (array of 3-6 lowercase strings, include the '
    'project name). No prose, no code fence. Only state what the input supports.'
)
