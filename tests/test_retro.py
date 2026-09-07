import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RETRO = ROOT / "hooks" / "error-retro.py"
LOG = ROOT / "hooks" / "tool-failure-log.py"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "hooks" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HAMSTER_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # no navigator
    return tmp_path


def run(script, payload):
    return subprocess.run(
        [sys.executable, str(script)], input=json.dumps(payload), capture_output=True, text=True
    )


def test_fingerprint_ignores_paths_numbers_hashes(env):
    m = load("error-retro")
    a = m.fingerprint("[Bash] /Users/kam/x/y.rb:12: error at line 12 sha 0123abcd456")
    b = m.fingerprint("[Bash] /Users/bob/x/y.rb:98: error at line 7 sha deadbeef1234")
    assert a == b
    assert a != m.fingerprint("[Bash] something else")


def test_log_then_retro_fires_once(env):
    sid = "s1"
    for i in range(8):
        r = run(LOG, {"session_id": sid, "cwd": "/tmp/proj", "tool_name": "Read",
                      "tool_input": {"file_path": f"/tmp/missing{i}"}, "error": "File does not exist"})
        assert r.returncode == 0
    lines = (env / "state" / "session-errors" / f"{sid}.jsonl").read_text().splitlines()
    assert len(lines) == 8
    r = run(RETRO, {"session_id": sid, "cwd": "/tmp/proj", "stop_hook_active": False})
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    assert "8 tool errors" in out["reason"]
    assert "hamster:promote" in out["reason"]
    assert "navigator insert" not in out["reason"]  # no CLI on PATH
    # second stop in the same session: MAX_FIRES=1 → silent
    for i in range(8):
        run(LOG, {"session_id": sid, "cwd": "/tmp/proj", "tool_name": "Bash",
                  "tool_input": {"command": "x"}, "error": "boom"})
    r = run(RETRO, {"session_id": sid, "cwd": "/tmp/proj", "stop_hook_active": False})
    assert r.stdout.strip() == ""


def test_below_threshold_is_silent(env):
    run(LOG, {"session_id": "s2", "cwd": "/tmp", "tool_name": "Bash", "tool_input": {}, "error": "e"})
    r = run(RETRO, {"session_id": "s2", "cwd": "/tmp", "stop_hook_active": False})
    assert r.stdout.strip() == ""


def test_interrupts_are_not_logged(env):
    run(LOG, {"session_id": "s3", "cwd": "/tmp", "tool_name": "Bash", "tool_input": {},
              "error": "cancelled", "is_interrupt": True})
    assert not (env / "state" / "session-errors" / "s3.jsonl").exists()


def test_stop_hook_active_never_loops(env):
    r = run(RETRO, {"session_id": "s4", "cwd": "/tmp", "stop_hook_active": True})
    assert r.stdout.strip() == ""


def test_store_uses_navigator_stub(env, monkeypatch, tmp_path):
    binp = tmp_path / "bin"
    binp.mkdir()
    stub = binp / "navigator"
    stub.write_text('#!/bin/sh\necho \'[{"slug":"solutions/x","title":"X lesson"}]\'\n')
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binp}:/usr/bin:/bin")
    st = load("_store")
    assert st.navigator_search("anything") == [("solutions/x", "X lesson")]
    merged = st.existing_lessons("/tmp/nowhere", query="q", project="p")
    assert merged[0] == ("solutions/x", "X lesson")
