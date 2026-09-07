import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "hooks" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def stub(tmp_path, monkeypatch):
    monkeypatch.setenv("HAMSTER_STATE", str(tmp_path / "state"))
    b = tmp_path / "hamster-lm"
    b.write_text('#!/bin/sh\nif [ "$1" = "--check" ]; then echo available; exit 0; fi\n'
                 'echo "2x File does not exist — check the path first"\n')
    b.chmod(0o755)
    monkeypatch.setenv("HAMSTER_LM", str(b))
    return tmp_path


def test_ask_uses_binary_and_caches_check(stub):
    lm = load("_lm")
    assert lm.available()
    assert (stub / "state" / "lm-check.json").exists()
    assert "File does not exist" in lm.ask("errors", lm.CLUSTER_INSTRUCTIONS)


def test_disabled_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HAMSTER_STATE", str(tmp_path))
    monkeypatch.setenv("HAMSTER_LM", "0")
    lm = load("_lm")
    assert lm.ask("anything") is None


def test_summarize_cli_exit_3_without_model(monkeypatch, tmp_path):
    monkeypatch.setenv("HAMSTER_STATE", str(tmp_path))
    monkeypatch.setenv("HAMSTER_LM", "0")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "summarize.py"), "session"],
                       input="x", capture_output=True, text=True, env=os.environ)
    assert r.returncode == 3


def test_retro_includes_local_draft(stub, monkeypatch):
    monkeypatch.setenv("CLAUDE_HOME", str(stub / "home"))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    log = ROOT / "hooks" / "tool-failure-log.py"
    retro = ROOT / "hooks" / "error-retro.py"
    for i in range(8):
        subprocess.run([sys.executable, str(log)], input=json.dumps(
            {"session_id": "L", "cwd": "/tmp/p", "tool_name": "Read", "tool_input": {}, "error": "File does not exist"}),
            capture_output=True, text=True, env=os.environ)
    r = subprocess.run([sys.executable, str(retro)], input=json.dumps(
        {"session_id": "L", "cwd": "/tmp/p", "stop_hook_active": False}), capture_output=True, text=True, env=os.environ)
    assert "Local draft from the local model" in json.loads(r.stdout)["reason"]
