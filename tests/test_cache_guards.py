import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WAKE = ROOT / "hooks" / "wake-guard.py"
STALE = ROOT / "hooks" / "stale-guard.py"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HAMSTER_STATE", str(tmp_path / "state"))
    for name in ("HAMSTER_WAKE_GUARD", "HAMSTER_STALE_GUARD"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def run(script, payload):
    return subprocess.run(
        [sys.executable, str(script)], input=json.dumps(payload), capture_output=True, text=True
    )


def transcript(path, tokens, minutes_ago, model="claude-opus-5"):
    stamp = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
    line = {
        "type": "assistant",
        "timestamp": stamp.isoformat().replace("+00:00", "Z"),
        "message": {"model": model, "usage": {"input_tokens": 5, "cache_read_input_tokens": tokens}},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "user", "message": {}}) + "\n" + json.dumps(line) + "\n")


def session(tmp, name, tokens, minutes_ago):
    main = tmp / "sess.jsonl"
    transcript(main, 50000, 0)
    sub = tmp / "sess" / "subagents"
    transcript(sub / f"agent-a{name}-abc123.jsonl", tokens, minutes_ago)
    (sub / f"agent-a{name}-abc123.meta.json").write_text(json.dumps({"name": name}))
    return {"session_id": "s1", "transcript_path": str(main), "tool_name": "SendMessage"}


def test_wake_warns_idle_agent_without_blocking(env):
    payload = session(env, "t9-impl", 200000, 30) | {"tool_input": {"to": "t9-impl", "message": "x"}}
    first = run(WAKE, payload)
    assert first.returncode == 0 and first.stderr == ""
    out = json.loads(first.stdout)
    assert "idle 30 min" in out["systemMessage"] and "200k" in out["systemMessage"] and "$1.25" in out["systemMessage"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert json.loads(run(WAKE, payload).stdout)["systemMessage"]  # priced every time, never blocked


@pytest.mark.parametrize(
    "tokens,minutes,to",
    [
        (200000, 2, "t9-impl"),  # cache still warm
        (20000, 30, "t9-impl"),  # too small to matter
        (200000, 30, "main"),  # report to the lead
        (200000, 30, "someone-else"),  # no transcript → unknown → pass
    ],
)
def test_wake_passes(env, tokens, minutes, to):
    payload = session(env, "t9-impl", tokens, minutes) | {"tool_input": {"to": to}}
    r = run(WAKE, payload)
    assert r.returncode == 0 and r.stdout == ""


def test_wake_matches_agent_id_and_sender_inside_subagent(env):
    payload = session(env, "t9-impl", 200000, 30)
    payload["transcript_path"] = str(env / "sess" / "subagents" / "agent-aother-1.jsonl")
    payload["tool_input"] = {"to": "at9-impl-abc123"}
    assert "wake-guard" in json.loads(run(WAKE, payload).stdout)["systemMessage"]


def test_wake_disabled_and_bad_input_fail_open(env, monkeypatch):
    payload = session(env, "t9-impl", 200000, 30) | {"tool_input": {"to": "t9-impl"}}
    monkeypatch.setenv("HAMSTER_WAKE_GUARD", "0")
    r = run(WAKE, payload)
    assert r.returncode == 0 and r.stdout == ""
    monkeypatch.delenv("HAMSTER_WAKE_GUARD")
    bad = subprocess.run([sys.executable, str(WAKE)], input="not json", capture_output=True, text=True)
    assert bad.returncode == 0


def test_stale_warns_cold_chat_without_blocking(env):
    main = env / "chat.jsonl"
    transcript(main, 210000, 185, model="claude-fable-5-1")
    payload = {"session_id": "s2", "transcript_path": str(main), "prompt": "carry on"}
    first = run(STALE, payload)
    assert first.returncode == 0 and first.stderr == ""
    out = json.loads(first.stdout)
    assert "3h05m" in out["systemMessage"] and "210k" in out["systemMessage"] and "/clear" in out["systemMessage"]
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert json.loads(run(STALE, payload).stdout)["systemMessage"]  # priced every time, never blocked


@pytest.mark.parametrize(
    "tokens,minutes,prompt",
    [(210000, 20, "carry on"), (40000, 185, "carry on"), (210000, 185, "/clear"), (210000, 185, " /handoff")],
)
def test_stale_passes(env, tokens, minutes, prompt):
    main = env / "chat.jsonl"
    transcript(main, tokens, minutes)
    payload = {"session_id": "s3", "transcript_path": str(main), "prompt": prompt}
    r = run(STALE, payload)
    assert r.returncode == 0 and r.stdout == ""


def test_last_call_reads_past_a_huge_trailing_line(env):
    sys.path.insert(0, str(ROOT / "hooks"))
    from _cache import last_call

    main = env / "big.jsonl"
    transcript(main, 150000, 90)
    with open(main, "a") as fh:
        fh.write(json.dumps({"type": "user", "message": {"content": "x" * 600000}}) + "\n")
    assert last_call(main)[0] == 150005


@pytest.mark.parametrize("model, price", [
    ("claude-opus-5-5", 5.0),
    ("claude-opus-5", 6.25),
    ("claude-fable-5-1", 12.5),
    ("claude-haiku-5-5", 0.125),
    ("claude-haiku-4-5", 1.25),
    ("", 6.25),
])
def test_write_price_per_model(model, price):
    sys.path.insert(0, str(ROOT / "hooks"))
    from _cache import write_price

    assert write_price(model) == price


def test_write_price_haiku_5_5_long_prompt_tier():
    sys.path.insert(0, str(ROOT / "hooks"))
    from _cache import write_price

    assert write_price("claude-haiku-5-5", 100_000) == 0.125
    assert write_price("claude-haiku-5-5", 150_000) == 0.625
    assert write_price("claude-opus-5-5", 150_000) == 5.0
