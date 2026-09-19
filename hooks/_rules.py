"""Rule loading, validation and matching shared by rule-guard.py, rules-recall.py
and scripts/rules.py.

A rule is one JSON file. Sources, in load order (later ids override earlier):
  1. <plugin>/rules/default/*.json      bundled
  2. ~/.claude/hamster/rules/*.json     user
  3. <git toplevel>/.claude/hamster/rules/*.json   project (committed, shared)

Required keys: id, tool, field, pattern, action (block|warn), message, tests.
A `block` rule with no test of each kind (expect block AND expect pass) is
downgraded to `warn` at load and flagged `untested` — a guard nobody has
proven is a nuisance, not a rule. Optional: event (default PreToolUse),
flags ("i" for case-insensitive), source, created (defaults to the file's
mtime date), note, keep (true = never a prune candidate), and `when` — an
optional gate checked after the pattern, all keys AND-ed:
  files_exist: ["Gemfile"]        any listed file exists at the git toplevel (language/stack check)
  path_glob:   "app/**/*.rb"      the tool's file_path matches (Edit/Write only; `*` stops at `/`,
                                  `**` crosses directories)
  branch:      ["main"]           current branch is one of these
  branch_not:  ["main"]           current branch is none of these
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import git, state_dir  # noqa: E402

REQUIRED = ("id", "tool", "field", "pattern", "action", "message", "tests")
WHEN_KEYS = ("files_exist", "path_glob", "branch", "branch_not")
ACTIONS = ("block", "warn")
ID_RX = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
FIRES = state_dir("rule-fires.json")

# Heredoc bodies that are data (cat > f <<EOF) must not trip a pattern; bodies
# fed to a shell interpreter execute and are kept. Same logic as bash-guard.py.
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n(.*?)\n\2(?=\n|$)", re.S)
# The interpreter must stand as a word of its own, bare or by path (`bash <<EOF`,
# `sudo /bin/sh <<EOF`); `cat > deploy.sh <<EOF` is data even though the filename ends in `sh`.
_SHELL = re.compile(r"(?:^|[\s;&|(/])((?:ba|z|da)?sh|eval|source)(?:\s|$)")


def strip_heredocs(cmd):
    def repl(m):
        line_start = cmd.rfind("\n", 0, m.start()) + 1
        tail = cmd[m.end(2) + len(m.group(1)) : m.start(3)]  # after the marker: `<<EOF | sh`
        if _SHELL.search(cmd[line_start : m.start()]) or _SHELL.search(tail):
            return m.group(0)
        return m.group(0)[: m.start(3) - m.start()] + "\n" + m.group(2)

    return _HEREDOC.sub(repl, cmd)


def plugin_root():
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    return Path(root) if root else Path(__file__).resolve().parent.parent


def rule_dirs(cwd=None):
    dirs = [("default", plugin_root() / "rules" / "default"), ("user", state_dir("rules"))]
    top = git(["rev-parse", "--show-toplevel"], cwd or os.getcwd())
    if top and os.path.realpath(top) != os.path.realpath(str(Path.home())):
        dirs.append(("project", Path(top) / ".claude" / "hamster" / "rules"))
    return dirs


def validate(rule):
    """Return a list of problems (empty = valid)."""
    problems = []
    for k in REQUIRED:
        if k not in rule:
            problems.append(f"missing `{k}`")
    if problems:
        return problems
    if not ID_RX.match(str(rule["id"])):
        problems.append("id must be kebab-case [a-z0-9-], 2-61 chars")
    if rule["action"] not in ACTIONS:
        problems.append(f"action must be one of {ACTIONS}")
    try:
        re.compile(rule["pattern"], re.I if "i" in str(rule.get("flags", "")) else 0)
    except re.error as e:
        problems.append(f"pattern does not compile: {e}")
    when = rule.get("when")
    if when is not None:
        if not isinstance(when, dict):
            problems.append("when must be an object")
        else:
            for k in when:
                if k not in WHEN_KEYS:
                    problems.append(f"unknown when key `{k}` (allowed: {', '.join(WHEN_KEYS)})")
            tools = rule["tool"] if isinstance(rule["tool"], list) else [rule["tool"]]
            if "path_glob" in when and all(t == "Bash" for t in tools):
                problems.append("path_glob needs a tool with a file_path (Edit/Write); Bash has none")
    tests = rule["tests"]
    if not isinstance(tests, list):
        problems.append("tests must be a list")
    else:
        for t in tests:
            if not isinstance(t, dict) or "input" not in t or t.get("expect") not in ("block", "pass"):
                problems.append(f"bad test {t!r}: needs input + expect block|pass")
    return problems


def is_tested(rule):
    kinds = {t.get("expect") for t in rule.get("tests", []) if isinstance(t, dict)}
    return {"block", "pass"} <= kinds


def load_rules(cwd=None):
    """{id: rule} with `_scope`, `_path`, `_untested`, `_effective` filled in.
    Invalid files are skipped and listed under the returned dict's `_errors`."""
    rules, errors = {}, []
    for scope, d in rule_dirs(cwd):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                rule = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                errors.append(f"{p}: {e}")
                continue
            probs = validate(rule)
            if probs:
                errors.append(f"{p}: " + "; ".join(probs))
                continue
            rule["_scope"], rule["_path"] = scope, str(p)
            if not rule.get("created"):
                rule["created"] = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).date().isoformat()
            rule["_untested"] = not is_tested(rule)
            rule["_effective"] = "warn" if rule["_untested"] else rule["action"]
            rules[rule["id"]] = rule
    rules["_errors"] = errors
    return rules


def iter_rules(rules):
    return (r for k, r in rules.items() if not k.startswith("_"))


def prunable(rule):
    """Bundled defaults and `keep: true` rules are never prune candidates."""
    return rule.get("_scope") != "default" and not rule.get("keep")


def rule_input(rule, tool_name, tool_input):
    """The string a rule inspects, or None when the tool/field don't apply."""
    tools = rule["tool"] if isinstance(rule["tool"], list) else [rule["tool"]]
    if tool_name not in tools:
        return None
    field = rule["field"]
    if field == "command":
        cmd = tool_input.get("command")
        return strip_heredocs(cmd) if isinstance(cmd, str) else None
    val = tool_input.get(field)
    if val is None and field == "content":
        val = tool_input.get("new_string")
    return val if isinstance(val, str) else None


def matches(rule, text):
    flags = re.I if "i" in str(rule.get("flags", "")) else 0
    return re.search(rule["pattern"], text, flags | re.M) is not None


def context(cwd=None):
    """Repo facts every `when` gate reads, computed once per hook call."""
    cwd = cwd or os.getcwd()
    top = git(["rev-parse", "--show-toplevel"], cwd)
    return {"cwd": cwd, "top": top, "branch": git(["branch", "--show-current"], cwd) or ""}


def _glob_rx(pattern):
    """Glob → regex with directory-aware semantics: `**` crosses `/`, `*` and `?` do not."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?"); i += 3
        elif pattern.startswith("**", i):
            out.append(".*"); i += 2
        elif c == "*":
            out.append("[^/]*"); i += 1
        elif c == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(c)); i += 1
    return re.compile("^" + "".join(out) + "$")


def _glob_match(path, pattern, top):
    p = path
    if top and os.path.isabs(p):
        try:
            p = os.path.relpath(p, top)
        except ValueError:
            pass
    rx = _glob_rx(pattern)
    return bool(rx.match(p) or rx.match(path))


def when_ok(rule, tool_input, ctx):
    """True when the rule's `when` gate passes (or there is none)."""
    when = rule.get("when") or {}
    if not when:
        return True
    if "files_exist" in when:
        base = ctx.get("top") or ctx.get("cwd") or "."
        names = when["files_exist"] if isinstance(when["files_exist"], list) else [when["files_exist"]]
        if not any(os.path.exists(os.path.join(base, n)) for n in names):
            return False
    if "branch" in when and ctx.get("branch") not in when["branch"]:
        return False
    if "branch_not" in when and ctx.get("branch") in when["branch_not"]:
        return False
    if "path_glob" in when:
        path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
        if not path or not _glob_match(path, when["path_glob"], ctx.get("top")):
            return False
    return True


def evaluate(rules, tool_name, tool_input, ctx=None):
    """[(rule, effective_action)] for every rule that fires."""
    hits = []
    ctx = ctx if ctx is not None else context()
    for rule in iter_rules(rules):
        text = rule_input(rule, tool_name, tool_input)
        if text is None or not matches(rule, text):
            continue
        if not when_ok(rule, tool_input, ctx):
            continue
        hits.append((rule, rule["_effective"]))
    return hits


def load_fires():
    try:
        return json.loads(FIRES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_fire(rule_id):
    fires = load_fires()
    rec = fires.get(rule_id) or {"count": 0}
    rec["count"] += 1
    rec["last"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fires[rule_id] = rec
    tmp = FIRES.with_suffix(".tmp")
    tmp.write_text(json.dumps(fires, indent=0, sort_keys=True), encoding="utf-8")
    os.replace(tmp, FIRES)


def run_tests(rule):
    """[(test, ok)] — each test's input is checked against the rule's pattern."""
    out = []
    for t in rule.get("tests", []):
        tool = rule["tool"] if isinstance(rule["tool"], str) else rule["tool"][0]
        text = rule_input(rule, tool, {rule["field"]: t["input"]})
        fired = text is not None and matches(rule, text)
        out.append((t, fired == (t["expect"] == "block")))
    return out
