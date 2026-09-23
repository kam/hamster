"""Prompt-cache cost helpers shared by wake-guard and stale-guard. Stdlib only.

A transcript's last assistant `usage` says how many tokens the next call will
carry; its timestamp says whether the cache that held them is still warm. Every
helper fails soft: unreadable input yields None, never an exception.
"""

import datetime as dt
import json
import os
import time

from _common import state_dir

RETRY_WINDOW_S = 600

# $/M cache-write tokens, list price. First substring match wins.
WRITE_PRICE = {"fable": 12.5, "opus-5-5": 5.0, "opus": 6.25, "sonnet": 2.5,
               "haiku": 1.25}
_TAIL_STEPS = (400_000, 4_000_000)  # one image line can exceed the first window


def write_price(model):
    model = model or ""
    for key, price in WRITE_PRICE.items():
        if key in model:
            return price
    return WRITE_PRICE["opus"]


def last_call(path):
    """(context_tokens, utc_timestamp, model) of the last billed assistant
    message in a transcript, or None."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    for window in _TAIL_STEPS:
        try:
            with open(path, "rb") as fh:
                fh.seek(max(0, size - window))
                lines = fh.read().decode("utf-8", errors="replace").splitlines()
        except OSError:
            return None
        for line in reversed(lines):
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
                msg = d.get("message") or {}
                u = msg.get("usage") or {}
                stamp = dt.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))
            except (ValueError, KeyError, AttributeError, TypeError):
                continue
            if d.get("type") != "assistant":
                continue
            tokens = sum(
                u.get(k) or 0
                for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
            )
            if tokens:
                return tokens, stamp, msg.get("model") or ""
        if window >= size:
            break
    return None


def confirmed(store, key):
    """Block-once memory. True when `key` was blocked within the retry window
    (the repeat is the confirmation); records the block otherwise."""
    path = state_dir(store)
    now = time.time()
    try:
        seen = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {}
    seen = {k: v for k, v in seen.items() if now - v < 86400}
    ok = now - seen.get(key, 0) < RETRY_WINDOW_S
    if ok:
        seen.pop(key, None)
    else:
        seen[key] = now
    try:
        path.write_text(json.dumps(seen), encoding="utf-8")
    except OSError:
        return True  # cannot remember the block → never block twice
    return ok


def cold(path, idle_seconds, min_tokens):
    """(tokens, idle_minutes, dollars) when the transcript's cache has gone cold
    and re-warming it costs real money; None when it is warm, small, or unknown."""
    call = last_call(path)
    if not call:
        return None
    tokens, stamp, model = call
    idle = (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds()
    if idle < idle_seconds or tokens < min_tokens:
        return None
    return tokens, int(idle // 60), tokens * write_price(model) / 1e6
