import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "hooks" / "rule-guard.py"
CLI = ROOT / "scripts" / "rules.py"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HAMSTER_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(ROOT))
    monkeypatch.chdir(tmp_path)  # not a git repo → no project scope
    return tmp_path


def guard(tool, tool_input, cwd="/tmp"):
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": cwd})
    return subprocess.run(
        [sys.executable, str(GUARD)], input=payload, capture_output=True, text=True, env=os.environ
    )


def cli(*args):
    return subprocess.run(
        [sys.executable, str(CLI), *args], capture_output=True, text=True, env=os.environ
    )


def test_default_rules_are_green(env):
    r = cli("test")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


def test_block_exits_2_with_message(env):
    r = guard("Bash", {"command": "rm -rf ~"})
    assert r.returncode == 2
    assert "rm-rf-root-or-home" in r.stderr


def test_pass_is_silent(env):
    r = guard("Bash", {"command": "rm -rf ./build && git push origin main"})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


def test_heredoc_body_is_data(env):
    r = guard("Bash", {"command": "cat > notes.md <<'EOF'\nnever run rm -rf /\nEOF"})
    assert r.returncode == 0


@pytest.mark.parametrize("opener", ["<<\"E\"OF", "<<E\\OF", "<<'E'OF", "<<EO\"F\""])
def test_partly_quoted_delimiter_hides_nothing(env, opener):
    """The shell's terminator is `EOF`; read as `E`, the strip ran on to a
    later `E` line and hid the command between (dev-lead review r3, 2026-10-18)."""
    r = guard("Bash", {"command": f"cat {opener}\nx\nEOF\nrm -rf /\nE"})
    assert r.returncode == 2


def test_heredoc_to_shell_still_blocks(env):
    r = guard("Bash", {"command": "bash <<'EOF'\nrm -rf /\nEOF"})
    assert r.returncode == 2


def test_fires_are_counted(env):
    guard("Bash", {"command": "chmod 777 x"})
    guard("Bash", {"command": "chmod 777 y"})
    fires = json.loads((env / "state" / "rule-fires.json").read_text())
    assert fires["chmod-777"]["count"] == 2


def test_untested_block_rule_downgrades_to_warn(env):
    rules = env / "state" / "rules"
    rules.mkdir(parents=True)
    (rules / "no-foo.json").write_text(json.dumps({
        "id": "no-foo", "tool": "Bash", "field": "command", "pattern": r"\bfoo\b",
        "action": "block", "message": "no foo", "tests": [{"input": "foo", "expect": "block"}],
    }))
    r = guard("Bash", {"command": "foo"})
    assert r.returncode == 0
    assert "warn-only" in r.stdout
    assert cli("test").returncode == 1  # a block rule without a pass test is a failure


def test_add_refuses_red_and_installs_green(env):
    bad = env / "bad.json"
    bad.write_text(json.dumps({
        "id": "no-bar", "tool": "Bash", "field": "command", "pattern": r"\bbar\b",
        "action": "block", "message": "no bar",
        "tests": [{"input": "bar", "expect": "block"}, {"input": "bar baz", "expect": "pass"}],
    }))
    r = cli("add", str(bad))
    assert r.returncode == 1 and "FAIL" in r.stdout
    good = env / "good.json"
    good.write_text(json.dumps({
        "id": "no-bar", "tool": "Bash", "field": "command", "pattern": r"\bbar\b",
        "action": "block", "message": "no bar",
        "tests": [{"input": "bar", "expect": "block"}, {"input": "barn", "expect": "pass"}],
    }))
    r = cli("add", str(good))
    assert r.returncode == 0, r.stdout
    assert (env / "state" / "rules" / "no-bar.json").exists()
    assert cli("add", str(good)).returncode == 1  # duplicate id
    assert guard("Bash", {"command": "echo bar"}).returncode == 2


def test_edit_rule_on_file_path(env):
    rules = env / "state" / "rules"
    rules.mkdir(parents=True)
    (rules / "no-env-edit.json").write_text(json.dumps({
        "id": "no-env-edit", "tool": ["Edit", "Write"], "field": "file_path",
        "pattern": r"(^|/)\.env(\.|$)", "action": "block", "message": "never edit .env",
        "tests": [{"input": "/app/.env", "expect": "block"}, {"input": "/app/.envrc", "expect": "pass"}],
        "created": "2020-01-01",
    }))
    assert guard("Edit", {"file_path": "/app/.env", "old_string": "a", "new_string": "b"}).returncode == 2
    assert guard("Edit", {"file_path": "/app/.envrc"}).returncode == 0
    assert guard("Read", {"file_path": "/app/.env"}).returncode == 0


def test_prune_lists_old_unfired_and_rm_refuses_default(env):
    rules = env / "state" / "rules"
    rules.mkdir(parents=True)
    (rules / "old.json").write_text(json.dumps({
        "id": "old", "tool": "Bash", "field": "command", "pattern": "zzz", "action": "warn",
        "message": "m", "created": "2020-01-01",
        "tests": [{"input": "zzz", "expect": "block"}, {"input": "a", "expect": "pass"}],
    }))
    out = json.loads(cli("prune", "--json").stdout)
    assert [o["id"] for o in out] == ["old"]
    assert cli("rm", "chmod-777").returncode == 1
    assert cli("rm", "old").returncode == 0
    assert not (rules / "old.json").exists()


def test_guard_disabled_by_env(env, monkeypatch):
    monkeypatch.setenv("HAMSTER_GUARD", "0")
    assert guard("Bash", {"command": "rm -rf /"}).returncode == 0


def _rule(**kw):
    base = {
        "id": "gated", "tool": "Bash", "field": "command", "pattern": r"\bqux\b",
        "action": "block", "message": "no qux",
        "tests": [{"input": "qux", "expect": "block"}, {"input": "quxx", "expect": "pass"}],
    }
    base.update(kw)
    return base


@pytest.fixture
def repo(env):
    subprocess.run(["git", "init", "-q", "-b", "feature/x"], cwd=env, check=True)
    rules = env / "state" / "rules"
    rules.mkdir(parents=True)
    return env, rules


def test_when_files_exist_gates_by_stack(repo):
    env, rules = repo
    (rules / "gated.json").write_text(json.dumps(_rule(when={"files_exist": ["Gemfile", "gems.rb"]})))
    assert guard("Bash", {"command": "qux"}, cwd=str(env)).returncode == 0  # no Gemfile → skip
    (env / "Gemfile").write_text("")
    assert guard("Bash", {"command": "qux"}, cwd=str(env)).returncode == 2


def test_when_branch_gates(repo):
    env, rules = repo
    (rules / "gated.json").write_text(json.dumps(_rule(when={"branch_not": ["feature/x"]})))
    assert guard("Bash", {"command": "qux"}, cwd=str(env)).returncode == 0
    (rules / "gated.json").write_text(json.dumps(_rule(when={"branch": ["feature/x"]})))
    assert guard("Bash", {"command": "qux"}, cwd=str(env)).returncode == 2


def test_when_path_glob_scopes_edit_rules(repo):
    env, rules = repo
    (rules / "gated.json").write_text(json.dumps(_rule(
        tool="Edit", field="content", pattern=r"binding\.pry", when={"path_glob": "app/**/*.rb"},
        tests=[{"input": "binding.pry", "expect": "block"}, {"input": "x", "expect": "pass"}])))
    hit = guard("Edit", {"file_path": f"{env}/app/models/u.rb", "new_string": "binding.pry"}, cwd=str(env))
    miss = guard("Edit", {"file_path": f"{env}/spec/u_spec.rb", "new_string": "binding.pry"}, cwd=str(env))
    assert hit.returncode == 2 and miss.returncode == 0


def test_when_unknown_key_is_invalid(repo):
    env, rules = repo
    (rules / "gated.json").write_text(json.dumps(_rule(when={"language": "ruby"})))
    out = cli("list", "--json").stdout
    assert "unknown when key" in out
    assert guard("Bash", {"command": "qux"}, cwd=str(env)).returncode == 0


def test_heredoc_to_sh_named_file_is_data(env):
    r = guard("Bash", {"command": "cat > deploy.sh <<'EOF'\nchmod 777 /srv\nEOF"})
    assert r.returncode == 0
    r = guard("Bash", {"command": "sudo sh <<'EOF'\nchmod 777 /srv\nEOF"})
    assert r.returncode == 2


@pytest.mark.parametrize("head", ["/bin/bash <<'EOF'", "sudo /bin/sh <<EOF", "bash<<EOF", "cat <<EOF | sh",
                                  "cat <<'EOF' | sudo bash -s"])
def test_heredoc_fed_to_a_shell_is_code(env, head):
    """The interpreter may be a path, glued to `<<`, or sit after the marker behind a pipe."""
    assert guard("Bash", {"command": f"{head}\nchmod 777 /srv\nEOF"}).returncode == 2, head


def test_heredoc_redirected_after_marker_is_data(env):
    assert guard("Bash", {"command": "cat <<'EOF' > bin/deploy.sh\nchmod 777 /srv\nEOF"}).returncode == 0


def test_default_rule_coverage(env):
    for cmd in ("rm -rf ~/", 'rm -rf "$HOME"', "rm -rf $HOME/", "git push origin +main",
                "git push origin +HEAD:main", "chmod a=rwx x"):
        assert guard("Bash", {"command": cmd}).returncode == 2, cmd
    for cmd in ("rm -rf ~/.cache/x", 'rm -rf "$HOME/tmp"', "git push origin +feature/x",
                "git push origin +main:feature/x"):
        assert guard("Bash", {"command": cmd}).returncode == 0, cmd


def test_bare_force_push_gated_by_branch(repo):
    env, _ = repo  # branch feature/x
    assert guard("Bash", {"command": "git push --force"}, cwd=str(env)).returncode == 0
    subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=env, check=True)
    assert guard("Bash", {"command": "git push --force"}, cwd=str(env)).returncode == 2


def test_prune_and_recall_skip_defaults_and_keep(env):
    rules = env / "state" / "rules"
    rules.mkdir(parents=True)
    (rules / "kept.json").write_text(json.dumps({
        "id": "kept", "tool": "Bash", "field": "command", "pattern": "zzz", "action": "warn",
        "message": "m", "created": "2020-01-01", "keep": True,
        "tests": [{"input": "zzz", "expect": "block"}, {"input": "a", "expect": "pass"}],
    }))
    assert json.loads(cli("prune", "--json").stdout) == []  # defaults (never fired) and keep:true exempt
    r = subprocess.run([sys.executable, str(ROOT / "hooks" / "rules-recall.py")],
                       input=json.dumps({"cwd": "/tmp"}), capture_output=True, text=True, env=os.environ)
    assert "never fired" not in r.stdout


def test_created_defaults_to_file_date(env):
    rules = env / "state" / "rules"
    rules.mkdir(parents=True)
    (rules / "nodate.json").write_text(json.dumps({
        "id": "nodate", "tool": "Bash", "field": "command", "pattern": "zzz", "action": "warn",
        "message": "m", "tests": [{"input": "zzz", "expect": "block"}, {"input": "a", "expect": "pass"}],
    }))
    row = next(r for r in json.loads(cli("list", "--json").stdout)["rules"] if r["id"] == "nodate")
    assert len(row["created"]) == 10


def test_path_glob_star_stops_at_slash_and_bash_rejected(repo):
    env, rules = repo
    (rules / "gated.json").write_text(json.dumps(_rule(
        tool="Edit", field="content", pattern=r"binding\.pry", when={"path_glob": "app/*.rb"},
        tests=[{"input": "binding.pry", "expect": "block"}, {"input": "x", "expect": "pass"}])))
    assert guard("Edit", {"file_path": f"{env}/app/x.rb", "new_string": "binding.pry"}, cwd=str(env)).returncode == 2
    assert guard("Edit", {"file_path": f"{env}/app/models/u.rb", "new_string": "binding.pry"}, cwd=str(env)).returncode == 0
    (rules / "gated.json").write_text(json.dumps(_rule(when={"path_glob": "app/*.rb"})))
    assert "path_glob needs" in cli("list", "--json").stdout


def test_q_flag_ignores_quoted_text():
    sys.path.insert(0, str(ROOT / "hooks"))
    import _rules

    rule = {"pattern": r"(?:^|[;&|]\s*)navigator\s+update\b", "flags": "q"}
    assert not _rules.matches(rule, "grep -E 'foo|navigator update' notes.txt")
    # an escape means no blanking: the raw text matches (fail-closed)
    assert _rules.matches(rule, 'grep -E "a\\"|navigator update" x')
    assert _rules.matches(rule, "ls | navigator update task/x")
    assert _rules.matches({**rule, "pattern": r"\$\(navigator\s+update"},
                          'echo "$(navigator update task/x)"')
    assert _rules.matches({**rule, "flags": ""}, "grep -E 'foo|navigator update' notes.txt")


def test_q_flag_escaped_quote_opens_no_string():
    sys.path.insert(0, str(ROOT / "hooks"))
    import _rules

    rule = {"pattern": r"(?:^|[;&|]\s*)navigator\s+update\b", "flags": "q"}
    assert _rules.matches(rule, "echo it\\'s; navigator update task/x; echo 'y'")


def test_q_flag_comment_apostrophe_opens_no_string():
    sys.path.insert(0, str(ROOT / "hooks"))
    import _rules

    rule = {"pattern": r"(?:^|[;&|]\s*)navigator\s+update\b", "flags": "q"}
    assert _rules.matches(rule, "ls # don't\nnavigator update task/x\necho 'ok'")
    assert not _rules.matches(rule, "ls # navigator update task/x")


def test_q_flag_exotic_syntax_matches_raw():
    sys.path.insert(0, str(ROOT / "hooks"))
    import _rules

    rule = {"pattern": r"(?:^|[;&|\n]\s*)navigator\s+update\b", "flags": "q"}
    assert _rules.matches(rule, "echo $'it\\'s'; navigator update task/x; echo 'y'")
    assert _rules.matches(rule, "ls;# don't\nnavigator update task/x\necho 'ok'")


def test_q_flag_executed_strings_match_raw():
    """2026-10-13 review r4 H3: a quoted string the shell runs is a command."""
    sys.path.insert(0, str(ROOT / "hooks"))
    import _rules

    rule = {"pattern": r"(?:^|[;&|\n]\s*)navigator\s+delete\b", "flags": "q"}
    for cmd in ("bash -c 'true; navigator delete task/foo'", 'sh -c "true; navigator delete task/foo"',
                "zsh -c 'x | navigator delete task/foo'", "eval 'true; navigator delete task/foo'",
                "ssh h 'cd x && navigator delete task/foo'", "watch -n1 'ls; navigator delete task/foo'",
                "tmux send-keys 'clear; navigator delete task/foo' Enter",
                '''python3 -c "import os; os.system('ls; navigator delete task/foo')"'''):
        assert _rules.matches(rule, cmd), cmd
    assert not _rules.matches(rule, "grep -E 'x|navigator delete' notes.txt")


EXECUTORS = ['echo "true; navigator delete task/foo" | bash', "echo 'true; navigator delete task/foo' | sh", 'bash <(echo "true; navigator delete task/foo")', "trap 'x; navigator delete task/foo' EXIT", "alias n='x; navigator delete task/foo'; n", 'perl -e \'system("x; navigator delete task/foo")\'', "node -e 'x; navigator delete task/foo'", "osascript -e 'x; navigator delete task/foo'", 'awk \'BEGIN{system("x; navigator delete task/foo")}\'', "tmux new-window 'x; navigator delete task/foo'", "tmux run-shell 'x; navigator delete task/foo'", "git rebase -x 'x; navigator delete task/foo' main", "env -S 'sh -c x; navigator delete task/foo'", "script -q /dev/null 'x; navigator delete task/foo'", "make X='x; navigator delete task/foo'", "exec sh -c'x; navigator delete task/foo'"]


def test_q_flag_only_blanks_read_only_commands():
    """2026-10-13 review r5 H2: any command not known read-only matches raw."""
    sys.path.insert(0, str(ROOT / "hooks"))
    import _rules

    rule = {"pattern": r"(?:^|[;&|\n(]\s*)navigator\s+delete\b", "flags": "q"}
    for cmd in EXECUTORS:
        assert _rules.matches(rule, cmd), cmd


def test_q_flag_refuses_prefixes_git_and_code_options():
    """2026-10-13 review r6 H2: env prefixes, git and options that run code."""
    sys.path.insert(0, str(ROOT / "hooks"))
    import _rules

    rule = {"pattern": r"(?:^|[;&|\n(]\s*)navigator\s+(?:update|delete)\b", "flags": "q"}
    for cmd in ('GIT_EDITOR="true; navigator update task/x --status done" git commit',
                'GIT_EXTERNAL_DIFF="true;navigator delete task/x" git diff HEAD~1',
                'GIT_PAGER="true; navigator delete task/x" git log -1',
                'PAGER="true;navigator delete task/x" git show',
                'git "-c" "core.pager=true; navigator delete task/x" log',
                'git grep -O"true; navigator delete task/x" foo',
                'LESSOPEN="|navigator delete task/x %s" less f',
                "less '+!true;navigator delete task/x' f",
                "rg --pre 'x; navigator delete task/x' foo",
                'X="a; navigator delete task/x" grep y f'):
        assert _rules.matches(rule, cmd), cmd


def test_q_flag_quoted_command_word_matches_raw():
    """2026-10-13 review r7 H1: a quoted command word is still a command."""
    sys.path.insert(0, str(ROOT / "hooks"))
    import _rules

    rule = {"pattern": r"(?:^|[;&|\n(]\s*)navigator\s+delete\b", "flags": "q"}
    for cmd in ('"eval" echo "x; navigator delete task/foo"', "'eval' printf 'x; navigator delete task/foo'",
                '"watch" echo "x; navigator delete task/foo"', '"eval" "x; navigator delete task/foo"',
                "'sh' '-c' 'true; navigator delete task/foo'"):
        assert _rules.matches(rule, cmd), cmd
    assert not _rules.matches(rule, "grep -E 'x|navigator delete' notes.txt")


def test_q_flag_code_running_options_match_raw():
    """2026-10-13 review r8: quoted `--pre`, and sort --compress-program."""
    sys.path.insert(0, str(ROOT / "hooks"))
    import _rules

    rule = {"pattern": r"(?:^|[;&|\n(]\s*)navigator\s+delete\b", "flags": "q"}
    for cmd in ("echo 'true; navigator delete task/foo' > /tmp/p; rg '--pre=sh' x /tmp/p",
                """echo 'true; navigator delete task/foo' > /tmp/p; rg "--pre" sh x /tmp/p""",
                "echo 'true; navigator delete task/foo' > /tmp/p; rg --p're'=sh x /tmp/p",
                "printf 'x; navigator delete task/foo ' | sort --compress-program=sh -S 1",
                "printf 'x; navigator delete task/foo ' | sort --comp=sh -S 1"):
        assert _rules.matches(rule, cmd), cmd


# ---- rewrite rules (0.8.0) ----------------------------------------------------

def _rewrite_rule(**kw):
    base = {
        "id": "quote-glob", "tool": "Bash", "field": "command",
        "pattern": r"((?:^|\s)--include=)(?!['\"])([^\s'\"\\{}]*[*?\[][^\s'\"\\{}]*)",
        "action": "rewrite", "replace": r'\1"\2"', "message": "quoted the glob",
        "tests": [
            {"input": "grep -r --include=*.md foo .", "expect": "rewrite",
             "output": 'grep -r --include="*.md" foo .'},
            {"input": "grep -r --include='*.md' foo .", "expect": "pass"},
        ],
    }
    base.update(kw)
    return base


def _install(env, rule):
    rules = env / "state" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    (rules / f"{rule['id']}.json").write_text(json.dumps(rule))
    return rules


def test_rewrite_emits_updated_input(env):
    _install(env, _rewrite_rule())
    r = guard("Bash", {"command": "grep -r --include=*.md foo .", "description": "d"})
    assert r.returncode == 0 and r.stderr == ""
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["updatedInput"] == {"command": 'grep -r --include="*.md" foo .', "description": "d"}
    assert "permissionDecision" not in out
    assert "hamster rewrote [quote-glob]: quoted the glob" in out["additionalContext"]
    assert 'ran command: grep -r --include="*.md" foo .' in out["additionalContext"]
    fires = json.loads((env / "state" / "rule-fires.json").read_text())
    assert fires["quote-glob"]["count"] == 1


def test_rewrite_pass_is_silent(env):
    _install(env, _rewrite_rule())
    r = guard("Bash", {"command": "grep -r --include='*.md' foo ."})
    assert r.returncode == 0 and r.stdout == ""


def test_rewrite_every_match_and_groups_from_original(env):
    _install(env, _rewrite_rule())
    r = guard("Bash", {"command": "grep -r --include=*.md --include=*.rb foo ."})
    assert json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]["command"] == \
        'grep -r --include="*.md" --include="*.rb" foo .'


def test_rewrite_leaves_data_heredoc_alone(env):
    _install(env, _rewrite_rule())
    cmd = "cat > notes.sh <<'EOF'\ngrep -r --include=*.md foo .\nEOF\ngrep -r --include=*.rb bar ."
    r = guard("Bash", {"command": cmd})
    new = json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]["command"]
    assert new == "cat > notes.sh <<'EOF'\ngrep -r --include=*.md foo .\nEOF\ngrep -r --include=\"*.rb\" bar ."
    # a body fed to a shell is code and is rewritten
    r = guard("Bash", {"command": "bash <<'EOF'\ngrep -r --include=*.md foo .\nEOF"})
    assert '--include="*.md"' in json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]["command"]


def test_rewrite_q_flag_skips_quoted_text_but_fills_groups_from_original():
    sys.path.insert(0, str(ROOT / "hooks"))
    import _rules

    rule = {"field": "command", "flags": "q", "replace": r"\1navigator \2 --actor agent:claude-code",
            "pattern": r"(^|[;&|(\n]\s*)navigator\s+(update|delete)\b(?!(?:'[^']*'|\"(?:[^\"\\]|\\.)*\"|[^;&|\n'\"])*--actor)"}
    assert _rules.rewrite(rule, "grep -E 'x|navigator update' notes.txt") == (None, 0)
    assert _rules.rewrite(rule, "navigator update task/x --set 'note=a; b'") == \
        ("navigator update --actor agent:claude-code task/x --set 'note=a; b'", 0)
    assert _rules.rewrite(rule, "navigator update task/x --actor human") == (None, 0)


def test_block_beats_rewrite_in_one_call(env):
    _install(env, _rewrite_rule())
    r = guard("Bash", {"command": "chmod 777 x; grep -r --include=*.md foo ."})
    assert r.returncode == 2 and r.stdout == "" and "chmod-777" in r.stderr


def test_warn_rides_inside_rewrite_json(env):
    _install(env, _rewrite_rule())
    _install(env, {
        "id": "warn-foo", "tool": "Bash", "field": "command", "pattern": r"\bfoo\b", "action": "warn",
        "message": "foo noted", "tests": [{"input": "foo", "expect": "block"}, {"input": "x", "expect": "pass"}],
    })
    r = guard("Bash", {"command": "grep -r --include=*.md foo ."})
    out = json.loads(r.stdout)  # stdout is JSON alone
    assert "hamster warn [warn-foo]: foo noted" in out["hookSpecificOutput"]["additionalContext"]
    r = guard("Bash", {"command": "grep foo x"})
    assert r.stdout.strip() == "hamster warn [warn-foo]: foo noted"


def test_untested_rewrite_downgrades_to_warn(env):
    _install(env, _rewrite_rule(tests=[{"input": "grep -r --include=*.md foo .", "expect": "rewrite",
                                        "output": 'grep -r --include="*.md" foo .'}]))
    r = guard("Bash", {"command": "grep -r --include=*.md foo ."})
    assert r.returncode == 0 and r.stdout.startswith("hamster warn [quote-glob] (untested rule, warn-only)")
    assert cli("test").returncode == 1


def test_rewrite_validation_and_tests(env):
    bad = env / "bad.json"
    bad.write_text(json.dumps(_rewrite_rule(replace=None)))
    assert "needs `replace`" in cli("add", str(bad)).stdout
    bad.write_text(json.dumps({**_rewrite_rule(), "action": "block"}))
    assert "only belongs on a rewrite rule" in cli("add", str(bad)).stdout
    bad.write_text(json.dumps(_rewrite_rule(tests=[{"input": "grep -r --include=*.md foo .", "expect": "block"},
                                                    {"input": "x", "expect": "pass"}])))
    assert "needs one test expecting rewrite" in cli("add", str(bad)).stdout
    bad.write_text(json.dumps({**_rewrite_rule(action="block"), "tests": [
        {"input": "grep -r --include=*.md foo .", "expect": "rewrite", "output": "x"}, {"input": "x", "expect": "pass"}]}))
    assert "only belongs on a rewrite rule" in cli("add", str(bad)).stdout
    bad.write_text(json.dumps(_rewrite_rule(replace=r"\1\3")))
    assert "names group 3" in cli("add", str(bad)).stdout
    bad.write_text(json.dumps(_rewrite_rule(replace=r"\g<nope>")))
    assert "names group 'nope'" in cli("add", str(bad)).stdout
    bad.write_text(json.dumps(_rewrite_rule(tests=[{"input": "grep -r --include=*.md foo .", "expect": "rewrite"},
                                                    {"input": "x", "expect": "pass"}])))
    assert "needs the exact `output`" in cli("add", str(bad)).stdout
    bad.write_text(json.dumps(_rewrite_rule(tests=[
        {"input": "grep -r --include=*.md foo .", "expect": "rewrite", "output": "grep -r --include='*.md' foo ."},
        {"input": "x", "expect": "pass"}])))
    r = cli("add", str(bad))
    assert r.returncode == 1 and "wanted" in r.stdout and "got" in r.stdout
    good = env / "good.json"
    good.write_text(json.dumps(_rewrite_rule()))
    assert cli("add", str(good)).returncode == 0
    assert cli("test", "quote-glob").returncode == 0
    out = cli("check", "Bash", "grep -r --include=*.md foo .").stdout
    assert "rewrite quote-glob" in out and '→ grep -r --include="*.md" foo .' in out


def test_rewrite_on_edit_file_path(env):
    _install(env, {
        "id": "tmp-to-scratch", "tool": ["Edit", "Write"], "field": "file_path", "pattern": r"^/tmp/(?=notes-)",
        "action": "rewrite", "replace": "/tmp/scratch/", "message": "notes go under scratch",
        "tests": [{"input": "/tmp/notes-1.md", "expect": "rewrite", "output": "/tmp/scratch/notes-1.md"},
                  {"input": "/tmp/other.md", "expect": "pass"}],
    })
    r = guard("Write", {"file_path": "/tmp/notes-1.md", "content": "x"})
    assert json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"] == {"file_path": "/tmp/scratch/notes-1.md", "content": "x"}
    assert guard("Read", {"file_path": "/tmp/notes-1.md"}).stdout == ""


# ---- review r1: a rewrite must never land inside quoted text ------------------

def test_rewrite_never_inserts_inside_quoted_text(env):
    """r1 H2: inserting `"` into a string the shell runs executes what follows."""
    _install(env, _rewrite_rule())
    for cmd in ('echo "a --include=*;id; b"', 'git commit -m "docs: use --include=*.md here"',
                "printf %s 'grep --include=*.md x' > notes.txt", 'bash -c "grep -r --include=*.md x ."'):
        r = guard("Bash", {"command": cmd})
        assert r.stdout == "", cmd
        # data in a read-only call passes; anything else is refused (the old block)
        if cmd.startswith(("echo", "printf")):
            assert r.returncode == 0, cmd
        else:
            assert r.returncode == 2 and "quote-glob" in r.stderr, cmd
    r = guard("Bash", {"command": 'echo "keep" --include=*.md'})
    assert json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]["command"] == 'echo "keep" --include="*.md"'


def test_rewrite_drops_nothing_from_a_blanked_span():
    """r1 H1: a match that spans blanked text outside a copied group blocks."""
    sys.path.insert(0, str(ROOT / "hooks"))
    import _rules

    rule = {"field": "command", "flags": "q", "pattern": r"echo\s+x", "replace": "echo y"}
    assert _rules.rewrite(rule, 'echo "keep" x') == (None, 1)
    rule = {"field": "command", "flags": "q", "pattern": r"echo(\s+)x", "replace": r"echo\1y"}
    assert _rules.rewrite(rule, 'echo "keep" x') == ('echo "keep" y', 0)  # the group copies it back
    # the group copies the quoted text back verbatim: safe
    rule = {"field": "command", "pattern": r"find(\s.*?\s-o\s)", "replace": r"rtk proxy find\1"}
    assert _rules.rewrite(rule, "find . -name 'a b' -o -name c") == ("rtk proxy find . -name 'a b' -o -name c", 0)
    # a match wholly inside a heredoc body is data
    rule = {"field": "command", "pattern": r"(^|\n)find ", "replace": r"\1rtk proxy find "}
    assert _rules.rewrite(rule, "cat > s <<'EOF'\nfind . -o x\nEOF") == (None, 0)


def test_rewritten_call_still_faces_block_rules(env):
    """r1 N2: the rewritten command is re-evaluated; a block there wins."""
    _install(env, {
        "id": "expand-home", "tool": "Bash", "field": "command", "pattern": r"^rm -rf HOMEDIR$",
        "action": "rewrite", "replace": "rm -rf ~", "message": "m",
        "tests": [{"input": "rm -rf HOMEDIR", "expect": "rewrite", "output": "rm -rf ~"}, {"input": "x", "expect": "pass"}],
    })
    r = guard("Bash", {"command": "rm -rf HOMEDIR"})
    assert r.returncode == 2 and "rm-rf-root-or-home" in r.stderr and r.stdout == ""


def test_rewrite_content_rule_reaches_new_string(env):
    """r1 N3: an Edit carries new_string, not content."""
    _install(env, {
        "id": "no-pry", "tool": ["Edit", "Write"], "field": "content", "pattern": r"binding\.pry\n",
        "action": "rewrite", "replace": "", "message": "pry removed",
        "tests": [{"input": "x\nbinding.pry\ny", "expect": "rewrite", "output": "x\ny"}, {"input": "x", "expect": "pass"}],
    })
    r = guard("Edit", {"file_path": "/a.rb", "old_string": "x", "new_string": "x\nbinding.pry\ny"})
    assert json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]["new_string"] == "x\ny"


def test_rewrite_block_test_kind(env):
    """A rewrite rule may carry a `block` test for a shape it refuses."""
    good = env / "good.json"
    good.write_text(json.dumps(_rewrite_rule(tests=_rewrite_rule()["tests"] + [
        {"input": 'git commit -m "x --include=*.md"', "expect": "block"},
        {"input": 'echo "x --include=*.md"', "expect": "pass"}])))
    r = cli("add", str(good))
    assert r.returncode == 0, r.stdout
    out = cli("check", "Bash", 'git commit -m "x --include=*.md"').stdout
    assert "blocks: the rewrite would land inside quoted text" in out


def test_rewrite_refuses_nested_substitution_quotes(env):
    """r2 H1: quotes inside `$(…)` within a double-quoted string defeat the flat
    lexer; such a call blocks on any match instead of being rewritten."""
    _install(env, _rewrite_rule())
    for cmd in ('echo "$(echo "a --include=*;id; b")"', 'echo "`echo "a --include=*;id; b"`"',
                'git commit -m "$(printf "%s" "a --include=*;id; b")"', "echo $'it\\'s --include=*.md x'",
                'echo "${X:-"a --include=*.md"}"'):
        r = guard("Bash", {"command": cmd})
        assert r.returncode == 2 and r.stdout == "" and "quote-glob" in r.stderr, cmd
    # an unquoted substitution still rewrites
    r = guard("Bash", {"command": "echo $(grep -r --include=*.md foo .)"})
    assert json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]["command"] == 'echo $(grep -r --include="*.md" foo .)'
