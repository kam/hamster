"""_lm server chain: config, key resolution, fallback to AFM stub, lm.py set/refuse."""
import http.server
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "hooks" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Handler(http.server.BaseHTTPRequestHandler):
    models = ["small-1b", "big-27b"]
    key = None
    calls = []

    def _auth(self):
        if self.key and self.headers.get("Authorization") != f"Bearer {self.key}":
            self.send_response(401); self.end_headers(); return False
        return True

    def do_GET(self):
        if not self._auth():
            return
        body = json.dumps({"data": [{"id": m} for m in self.models]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self._auth():
            return
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n))
        Handler.calls.append(req)
        reply = {"choices": [{"message": {"content": f"<think>hmm</think>```json\nREPLY from {req['model']}\n```"}}]}
        body = json.dumps(reply).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    Handler.calls = []; Handler.key = None
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HAMSTER_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("HAMSTER_LM", "0")  # start with everything off; tests opt in
    monkeypatch.delenv("HAMSTER_LM")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "noplugin"))  # no native binary
    return tmp_path


def write_cfg(tmp, server):
    d = tmp / "state"; d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps({"lm": {"server": server, "afm": True}}))


def test_server_used_with_tiers_and_cleanup(env, server):
    write_cfg(env, {"url": server, "models": {"fast": "small-1b", "quality": "big-27b"},
                    "extra": {"chat_template_kwargs": {"enable_thinking": False}}})
    lm = load("_lm")
    assert lm.backend() == "server"
    assert lm.ask("q", "i", 20, tier="fast") == "REPLY from small-1b"
    assert lm.ask("q", "i", 20, tier="quality") == "REPLY from big-27b"
    assert Handler.calls[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_key_from_file_ref(env, server, tmp_path):
    Handler.key = "sekrit"
    (tmp_path / "s.json").write_text(json.dumps({"auth": {"api_key": "sekrit"}}))
    write_cfg(env, {"url": server, "models": {"quality": "big-27b"},
                    "api_key_file": f"{tmp_path}/s.json#auth.api_key"})
    lm = load("_lm")
    assert lm.ask("q", "i", 20) == "REPLY from big-27b"
    cfg_text = (env / "state" / "config.json").read_text()
    assert "sekrit" not in cfg_text


def test_server_down_falls_to_afm_stub(env, tmp_path):
    stub = tmp_path / "hamster-lm"
    stub.write_text('#!/bin/sh\n[ "$1" = "--check" ] && { echo available; exit 0; }\ncat >/dev/null; echo AFM\n')
    stub.chmod(0o755)
    os.environ["HAMSTER_LM"] = str(stub)
    write_cfg(env, {"url": "http://127.0.0.1:9/v1", "models": {"quality": "x"}})
    lm = load("_lm")
    assert lm.backend() == "afm"
    assert lm.ask("q", "i", 20) == "AFM"
    del os.environ["HAMSTER_LM"]


def test_nothing_available(env):
    lm = load("_lm")
    assert lm.backend() is None and lm.ask("q") is None


def test_lm_cli_set_refuses_unserved_model_and_saves_good(env, server):
    cli = [sys.executable, str(ROOT / "scripts" / "lm.py")]
    r = subprocess.run([*cli, "set", "--url", server, "--fast", "nope"], capture_output=True, text=True, env=os.environ)
    assert r.returncode == 1 and "not served" in r.stdout
    r = subprocess.run([*cli, "set", "--url", server, "--fast", "small-1b", "--quality", "big-27b"],
                       capture_output=True, text=True, env=os.environ)
    assert r.returncode == 0, r.stdout
    cfg = json.loads((env / "state" / "config.json").read_text())
    assert cfg["lm"]["server"]["models"] == {"fast": "small-1b", "quality": "big-27b"}
    r = subprocess.run([*cli, "clear"], capture_output=True, text=True, env=os.environ)
    assert "server" not in json.loads((env / "state" / "config.json").read_text())["lm"]
