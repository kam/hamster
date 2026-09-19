#!/usr/bin/env python3
"""hamster local-model setup.

  lm.py detect                 probe oMLX / LM Studio / Ollama / llama.cpp; list models (JSON with --json)
  lm.py set --url U [--fast M] [--quality M] [--api-key-env E | --api-key-file F#dotted.path]
                                   [--extra JSON] [--no-afm]        write ~/.claude/hamster/config.json
  lm.py show                   current config + which backend ask() would use
  lm.py test                   one round-trip per tier through the configured chain
  lm.py clear                  remove the server entry (AFM / in-session fallback remain)
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import _lm  # noqa: E402


def cmd_detect(a):
    found = []
    for name, url, keyref in _lm.KNOWN_SERVERS:
        key = _lm.resolve_key({"api_key_file": keyref}) if keyref else None
        models = _lm.server_models(url, key, timeout=3)
        if models is None:
            continue
        found.append({"name": name, "url": url, "api_key_file": keyref, "models": models})
    if a.json:
        print(json.dumps({"servers": found, "afm": _lm.afm_available()}, indent=2))
        return 0
    if not found:
        print("no local OpenAI-compatible server answering on :8000/:1234/:11434/:8080")
    for f in found:
        print(f"{f['name']}  {f['url']}" + (f"  (key from {f['api_key_file']})" if f["api_key_file"] else ""))
        for m in f["models"]:
            print(f"  - {m}")
    print(f"apple on-device (hamster-lm): {'available' if _lm.afm_available() else 'not available'}")
    return 0


def cmd_set(a):
    cfg = _lm.load_config()
    lm = cfg.setdefault("lm", {})
    server = {"url": a.url.rstrip("/"), "models": {}}
    if a.fast:
        server["models"]["fast"] = a.fast
    if a.quality:
        server["models"]["quality"] = a.quality
    if not server["models"]:
        print("need --fast and/or --quality model id")
        return 1
    if a.api_key_env:
        server["api_key_env"] = a.api_key_env
    if a.api_key_file:
        server["api_key_file"] = a.api_key_file
    if a.extra:
        try:
            server["extra"] = json.loads(a.extra)
        except ValueError as e:
            print(f"--extra is not JSON: {e}")
            return 1
    models = _lm.server_models(server["url"], _lm.resolve_key(server))
    if models is None:
        print(f"refused: {server['url']} is not answering /models (start the server, check the key)")
        return 1
    for tier, mid in server["models"].items():
        if mid not in models:
            print(f"refused: {tier} model `{mid}` is not served there. Served: {', '.join(models)}")
            return 1
    lm["server"] = server
    lm["afm"] = not a.no_afm
    _lm.save_config(cfg)
    _lm._check_save({})
    print(f"saved {_lm.CONFIG}")
    subprocess.run(["bash", str(Path(__file__).resolve().parent / "install-shims.sh")], check=False)
    return cmd_show(a)


def cmd_show(a):
    cfg = _lm.load_config().get("lm", {})
    print(json.dumps(cfg, indent=2) if cfg else "no lm config (AFM / in-session fallback only)")
    print(f"backend now: {_lm.backend() or 'none (in-session model)'}")
    return 0


def cmd_test(a):
    _lm._check_save({})  # fresh probe: a stale "down" mark must not fake the result
    for tier, prompt in (("fast", "Answer YES or NO: is 2+2 equal to 4?"),
                         ("quality", "In one sentence, what does a PreToolUse hook do in Claude Code?")):
        out = _lm.ask(prompt, "Answer briefly.", 60, tier=tier)
        print(f"{tier:<8} via {_lm.backend() or 'none'}: {out!r}")
    return 0 if _lm.available() else 3


def cmd_clear(a):
    cfg = _lm.load_config()
    cfg.get("lm", {}).pop("server", None)
    _lm.save_config(cfg)
    _lm._check_save({})
    print("server entry removed")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lm.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("detect"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_detect)
    s = sub.add_parser("set"); s.add_argument("--url", required=True); s.add_argument("--fast"); s.add_argument("--quality")
    s.add_argument("--api-key-env"); s.add_argument("--api-key-file"); s.add_argument("--extra"); s.add_argument("--no-afm", action="store_true"); s.set_defaults(fn=cmd_set)
    s = sub.add_parser("show"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("test"); s.set_defaults(fn=cmd_test)
    s = sub.add_parser("clear"); s.set_defaults(fn=cmd_clear)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
