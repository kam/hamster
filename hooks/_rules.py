"""Rule loading, validation and matching shared by rule-guard.py, rules-recall.py
and scripts/rules.py.

A rule is one JSON file. Sources, in load order (later ids override earlier):
  1. <plugin>/rules/default/*.json      bundled
  2. ~/.claude/hamster/rules/*.json     user
  3. <git toplevel>/.claude/hamster/rules/*.json   project (committed, shared)

Required keys: id, tool, field, pattern, action (block|warn|rewrite), message, tests.
A `block` rule with no test of each kind (expect block AND expect pass) is
downgraded to `warn` at load and flagged `untested` — a guard nobody has
proven is a nuisance, not a rule. A `rewrite` rule carries `replace` (a Python
re.sub template, `\\1` / `\\g<name>` groups) and the hook substitutes it into
the field instead of blocking: the call runs rewritten (PreToolUse
`updatedInput`), and the message reaches Claude as `additionalContext`. Its
tests expect `rewrite` with the exact `output`, plus `pass` (and `block` for
a shape the rule refuses); untested, it is warn-only like a block. A match
whose replaced text would land inside a quoted string, a comment or a data
heredoc body is never rewritten: a match wholly inside such text is data
(skipped when every command is read-only, else the call blocks); one that
straddles it blocks. Optional: event (default PreToolUse),
flags ("i" for case-insensitive; "q" blanks quoted strings before matching, but
only when every command in the call is a bare read-only one — grep, rg, echo,
printf, head, tail, wc, uniq, cut, tr — so a verb inside a grep pattern or a message
does not fire; anything else matches raw), source, created (defaults to the file's
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
ACTIONS = ("block", "warn", "rewrite")
EXPECTS = ("block", "pass", "rewrite")
ID_RX = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
FIRES = state_dir("rule-fires.json")

# Heredoc bodies that are data (cat > f <<EOF) must not trip a pattern; bodies
# fed to a shell interpreter execute and are kept. Same logic as bash-guard.py.
# A partly quoted delimiter (`E\OF`, `"E"OF`) ends at `EOF` to the shell, which
# `\2` cannot express, as is any word cut short (`E.OF`, `E@OF`): a shell
# metacharacter or the line end must follow, else nothing matches and the body stays visible.
# `<<-` strips leading tabs, so its terminator may be indented.
_HEREDOC = re.compile(
    r"(?<!<)<<(?!<)(?P<dash>-)?\s*(?P<q>['\"]?)(?P<delim>\w+)(?P=q)(?=[ \t;&|<>()]|\n)[^\n]*\n"
    r"(?P<body>.*?)\n(?(dash)\t*)(?P=delim)(?=\n|$)", re.S)
# The interpreter must stand as a word of its own, bare or by path (`bash <<EOF`,
# `sudo /bin/sh <<EOF`); `cat > deploy.sh <<EOF` is data even though the filename ends in `sh`.
_SHELL = re.compile(r"(?:^|[\s;&|(/])((?:ba|z|da)?sh|eval|source)(?:\s|$)")


# _scan_line, _opener_hidden and _body_follows are dev-lead hooks/git-guard.py's, verbatim:
# keep the two in step.
def _scan_line(text, ctx=None, low=None):
    """Walk one line of shell as the shell lexes it: `(ctx, comment)`. `ctx`
    is `(quote, stack)`: the quote open at the end ('\\'', '"', "$'" or
    None) and the open `$(`, backtick, `$((` and nested `(` contexts, each
    remembering the quote it interrupted and its closer. Carried line to
    line, so `)"` closes what an earlier `"$(` opened. `comment` is the
    offset of an unquoted word-start `#` (scanning stops there; `a#b` and
    `${#x}` are not comments). `$(` and a backtick open a fresh unquoted
    context even inside double quotes, so `"$(cat <<'EOF'` is a real opener
    and a `'` inside `"$(…)"` closes nothing it did not open. The third
    element, `joined`, says the line ended `x\\`: the shell glues the next
    line onto that word, so its column 0 is not a word start (`a\\` then
    `#"` is the word `a#"`, not a comment). `low`, a list `[start, depth]`,
    gets the least stack depth seen from offset `start` on, in the same pass."""
    state, stack, joined = ctx if ctx else (None, (), False)
    stack, escaped, word_start, i = list(stack), False, not joined, 0
    while i < len(text):
        ch = text[i]
        at_word_start, word_start = word_start, False
        if escaped:
            escaped = False
        elif ch == "\\" and state != "'":
            escaped = True
        elif state in ("'", "$'"):
            if ch == "'":
                state = None
        elif state == '"':
            if ch == '"':
                state = None
            elif text.startswith("$((", i):
                stack.append(('"', "))")); state = None; i += 2
            elif text.startswith("$(", i):
                stack.append(('"', ")")); state = None; i += 1
            elif text.startswith("${", i) or text.startswith("$[", i):
                stack.append(('"', "}" if text[i + 1] == "{" else "]")); state = None; i += 1
            elif ch == "`":
                stack.append(('"', "`")); state = None
        else:
            closer = stack[-1][1] if stack else None
            if text.startswith("$'", i):
                state = "$'"; i += 1
            elif ch in "'\"":
                state = ch
            elif ch == "#" and at_word_start:
                return (state, tuple(stack), False), i
            elif text.startswith("$((", i) or (at_word_start and text.startswith("((", i)):
                stack.append((None, "))")); i += 1 + (ch == "$")
            elif text.startswith("$(", i):
                stack.append((None, ")")); i += 1
            elif text.startswith("${", i) or text.startswith("$[", i):
                stack.append((None, "}" if text[i + 1] == "{" else "]")); i += 1
            elif ch == "`" and closer != "`":
                stack.append((None, "`"))
            elif ch in "<>" and text.startswith("(", i + 1):
                stack.append((None, ")")); i += 1  # `<(…)`, `>(…)`: a substitution too
            elif ch == "(" and stack:
                stack.append((None, ")"))  # a plain paren inside a substitution
            elif closer == "))" and ch == ")" and not text.startswith("))", i):
                stack[-1] = (stack[-1][0], ")")  # `$((echo a) | cat)`: bash fell back to `$( (…`
            elif closer and text.startswith(closer, i):
                state = stack.pop()[0]; i += len(closer) - 1
            else:
                word_start = ch in " \t;&|()"
        if low and i >= low[0]:
            low[1] = min(low[1], len(stack))
        i += 1
    joined = escaped and len(text) > 1 and text[-2] not in " \t"
    return (state, tuple(stack), joined), None


def _opener_hidden(prefix, ctx=None):
    """True when a `<<` right after `prefix` is comment, quoted or arithmetic
    text to the shell, not a heredoc opener (review of 0.11.0, 2026-10-01:
    the lines after such an opener run, and were blanked from every gate)."""
    (quote, stack, _), comment = _scan_line(prefix, ctx)
    return comment is not None or quote is not None or bool(stack and stack[-1][1] in ("))", "]", "}"))


def _body_follows(line, end, ctx):
    """True when the body starts on the next line: the line ends in the
    opener's own context and nothing closed that context in between. In
    `x="$(cat <<EOF)"` the substitution closes first, so the heredoc is empty
    and the shell runs the next lines (review r4, 2026-10-18); a quote or
    substitution left open after the opener moves the body later. Either way
    the opener is dropped, which shows more lines, never fewer. `end` is the
    offset just past the opener's delimiter."""
    at = _scan_line(line[:end], ctx)[0][:2]
    low = [end, len(at[1])]
    return _scan_line(line, ctx, low)[0][:2] == at and low[1] == len(at[1])


_HEREDOC_BUDGET = 1_000_000


def _sub_heredocs(repl, cmd):
    """`_HEREDOC.sub(repl, cmd)` over the heredocs the shell really opens. Shell
    lines are lexed in order, so a `<<` that is comment, quoted, arithmetic or
    escaped text, or whose substitution closes on its own line, opens nothing
    and the lines after it stay visible. Body lines are never lexed. Each
    opener rescans its line, so past `_HEREDOC_BUDGET` (openers × length)
    nothing is stripped: a guard that runs out its hook timeout lets the
    call through. Same budget as git-guard.py."""
    if cmd.count("<<") * len(cmd) > _HEREDOC_BUDGET:
        return cmd
    out, done, pos, line_start, ctx = [], 0, 0, 0, None
    while m := _HEREDOC.search(cmd, pos):
        ls = cmd.rfind("\n", 0, m.start()) + 1
        for line in cmd[line_start:ls].split("\n")[:-1]:
            ctx = _scan_line(line, ctx)[0]
        line_start = ls
        line, prefix = cmd[ls:m.start("body") - 1], cmd[ls:m.start()]
        if (re.search(r"(?<!\\)(?:\\\\)*\\$", prefix) or _opener_hidden(prefix, ctx)
                or not _body_follows(line, m.end("delim") + len(m.group("q")) - ls, ctx)):
            pos = m.start() + 2
            continue
        out += [cmd[done:m.start()], repl(m)]
        ctx = _scan_line(line, ctx)[0]
        done = line_start = pos = m.end()
    return "".join(out) + cmd[done:]


def strip_heredocs(cmd):
    def repl(m):
        line_start = cmd.rfind("\n", 0, m.start()) + 1
        tail = cmd[m.end("delim") + len(m.group("q")) : m.start("body")]  # after the marker: `<<EOF | sh`
        if _SHELL.search(cmd[line_start : m.start()]) or _SHELL.search(tail):
            return m.group(0)
        return m.group(0)[: m.start("body") - m.start()] + "\n" + m.group("delim")

    return _sub_heredocs(repl, cmd)


def blank_heredocs(cmd):
    """Like strip_heredocs, but length-preserving: a data body becomes spaces,
    so a match position on the result is the same position in `cmd`."""
    def repl(m):
        line_start = cmd.rfind("\n", 0, m.start()) + 1
        tail = cmd[m.end("delim") + len(m.group("q")) : m.start("body")]
        if _SHELL.search(cmd[line_start : m.start()]) or _SHELL.search(tail):
            return m.group(0)
        head = m.group(0)[: m.start("body") - m.start()]
        return head + " " * (m.end("body") - m.start("body")) + m.group(0)[m.end("body") - m.start() :]

    return _sub_heredocs(repl, cmd)


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
    rewrite_rule = rule["action"] == "rewrite"
    if rewrite_rule and not isinstance(rule.get("replace"), str):
        problems.append("a rewrite rule needs `replace` (a re.sub template)")
    elif "replace" in rule and not rewrite_rule:
        problems.append("`replace` only belongs on a rewrite rule")
    elif rewrite_rule and not problems:
        rx = _regex(rule)
        for g in template_groups(rule["replace"]):
            if (isinstance(g, int) and g > rx.groups) or (isinstance(g, str) and g not in rx.groupindex):
                problems.append(f"replace names group {g!r}, which the pattern does not have")
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
            if not isinstance(t, dict) or "input" not in t or t.get("expect") not in EXPECTS:
                problems.append(f"bad test {t!r}: needs input + expect block|pass|rewrite")
            elif t["expect"] == "rewrite" and not isinstance(t.get("output"), str):
                problems.append(f"bad test {t!r}: expect rewrite needs the exact `output`")
            elif t["expect"] == "rewrite" and not rewrite_rule:
                problems.append(f"bad test {t!r}: a {rule['action']} rule's tests expect block|pass")
    return problems


def is_tested(rule):
    kinds = {t.get("expect") for t in rule.get("tests", []) if isinstance(t, dict)}
    fires = "rewrite" if rule.get("action") == "rewrite" else "block"
    return {fires, "pass"} <= kinds


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
        return blank_heredocs(cmd) if isinstance(cmd, str) else None
    val = tool_input.get(field)
    if val is None and field == "content":
        val = tool_input.get("new_string")
    return val if isinstance(val, str) else None


# An escaped character outside quotes is consumed first, so `it\'s` opens no
# string; a `#` comment is consumed whole, so `# don't` opens none either.
_QUOTED = re.compile(r"\\.|(?<!\S)#[^\n]*|\"(?:[^\"\\]|\\.)*\"|'[^']*'", re.S)


def blank_quotes(text):
    """Quoted strings → spaces of the same length, so a `|` or a verb inside a
    grep pattern or a message is not a command. A double-quoted string that
    carries `$(` or a backtick is kept: the shell runs what is inside it."""
    def repl(m):
        s = m.group(0)
        if s[0] == "\\" or (s[0] == '"' and ("$(" in s or "`" in s)):
            return s
        return " " * len(s)

    return _QUOTED.sub(repl, text)


# Syntax the blanker cannot lex reliably (`$'…'`, escapes, heredocs, word-start
# `#`; dev-lead git-guard's _EXOTIC_RE) and substitutions that run code.
_EXOTIC = re.compile(r"<<|\\|\$'|(?<![^\s;&|(])#|`|\$\(|[<>]\(")
_SEGMENT = re.compile(r"[^;&|\n]+")
# Commands whose quoted arguments are only data. A list of executors can never
# be complete (`| bash`, `trap`, `perl -e`, `GIT_EDITOR=…`), so `q` blanks only
# when every command in the call is one of these, bare: no `VAR=` prefix, no
# git, nothing that takes a command as an option value (reviews r5 H2, r6 H2).
_READ_ONLY = {"grep", "egrep", "fgrep", "rg", "echo", "printf", "head", "tail",
              "wc", "uniq", "cut", "tr", "true", "false"}
# Options of the commands above that run a program (rg --pre; `sort` left the
# list over --compress-program, review r8 H2). Read with the quote characters
# stripped: the shell drops them, so `'--pre=sh'` is still --pre (r8 H1).
_RUNS_CODE = re.compile(r"(?:^|\s)--pre(?:=|\s|$)|(?:^|\s)--pre-glob")


def _quotes_are_data(text):
    """True when blanking quoted strings cannot hide a command: no exotic
    syntax, and every command in the call is a bare, known read-only one."""
    if _EXOTIC.search(text):
        return False
    for seg in _SEGMENT.finditer(blank_quotes(text)):
        raw = text[seg.start():seg.end()]
        if not raw.strip():
            continue
        words, rwords = seg.group(0).split(), raw.split()
        # The command word must read the same raw and blanked: `"eval" echo …`
        # and an all-quoted `'sh' '-c' '…'` run code (review r7 H1).
        if (not words or words[0] != rwords[0] or words[0] not in _READ_ONLY
                or _RUNS_CODE.search(re.sub(r"['\"]", "", raw))):
            return False
    return True


def _regex(rule):
    opts = str(rule.get("flags", ""))
    return re.compile(rule["pattern"], (re.I if "i" in opts else 0) | re.M)


def _inspectable(rule, text):
    """`text` with quoted strings blanked when flag q applies (length-preserving)."""
    if "q" in str(rule.get("flags", "")) and _quotes_are_data(text):
        return blank_quotes(text)
    return text


def matches(rule, text):
    return _regex(rule).search(_inspectable(rule, text)) is not None


# The template grammar: `\N` and `\g<name>` copy a group, `\\` is one backslash;
# every other character, backslash included, is literal (not re.sub's escapes).
_TEMPLATE = re.compile(r"\\(\d+)|\\g<(\w+)>|\\\\")


def template_groups(template):
    """The group numbers/names a template copies."""
    out = []
    for t in _TEMPLATE.finditer(template):
        g = t.group(1) or t.group(2)
        if g is not None:
            out.append(int(g) if g.isdigit() else g)
    return out


def _expand(template, m, original):
    """`template` with `\\N` / `\\g<name>` filled from `original` at the match's
    group spans — the match was made on blanked text, the groups come from the
    real command."""
    def repl(t):
        if t.group(0) == "\\\\":
            return "\\"
        g = t.group(1) or t.group(2)
        g = int(g) if g.isdigit() else g
        start, end = m.span(g)
        return original[start:end] if start != -1 else ""

    return _TEMPLATE.sub(repl, template)


def _protected(cmd):
    """Byte positions of `cmd` the shell treats as text, not command words:
    data heredoc bodies, every quoted string (a `$(…)` inside double quotes
    too — a rewrite must not break the quoting around it), comments and
    escape pairs."""
    mask = [False] * len(cmd)
    blanked = blank_heredocs(cmd)
    for i, (a, b) in enumerate(zip(cmd, blanked)):
        if a != b:
            mask[i] = True
    for m in _QUOTED.finditer(blanked):
        for i in range(m.start(), m.end()):
            mask[i] = True
    return mask


_NESTED = re.compile(r"\$\(|`|\$\{")


def _lexable(cmd):
    """False when the flat quote lexer cannot be trusted: a quoted span that
    carries a substitution (`"$(echo "a")"` nests quotes the lexer ends at
    the first inner `"`), or a `$'…'` string. Such a call is never rewritten."""
    if "$'" in cmd:
        return False
    for m in _QUOTED.finditer(blank_heredocs(cmd)):
        if m.group(0)[0] == '"' and _NESTED.search(m.group(0)):
            return False
    return True


def rewrite(rule, value):
    """`(new_value, unsafe)`: `value` with every safe match replaced (None
    when nothing changes), and the number of matches that were left alone
    because the rewrite would have landed inside protected text — those
    calls block, as a block rule would. A call the flat quote lexer cannot
    read (`_lexable`) blocks on any match. Data heredoc bodies and (flag q)
    quoted strings are matched as blanks of the same length, so the groups
    copied back come from the real command. A match is safe when no part
    of its span outside a copied group is protected; a match that lies
    wholly inside protected text is data and skipped silently when every
    command in the call is read-only (the `q` rule), else unsafe."""
    command = rule["field"] == "command"
    text = blank_heredocs(value) if command else value
    text = _inspectable(rule, text)
    found = list(_regex(rule).finditer(text))
    if command and found and not _lexable(value):
        return None, len(found)
    mask = _protected(value) if command else [False] * len(value)
    copied = template_groups(rule["replace"])
    data_ok = command and _quotes_are_data(value)
    out, pos, unsafe = [], 0, 0
    for m in found:
        span = range(m.start(), m.end())
        hit = [i for i in span if mask[i]]
        if hit:
            if len(hit) == len(span) and len(span):
                if not data_ok:
                    unsafe += 1
                continue
            kept = set()
            for g in copied:
                s, e = m.span(g)
                kept.update(range(s, e))
            if any(i not in kept for i in hit):
                unsafe += 1
                continue
        out.append(value[pos:m.start()])
        out.append(_expand(rule["replace"], m, value))
        pos = m.end()
    out.append(value[pos:])
    new = "".join(out)
    return (new if new != value else None), unsafe


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
        if rule["action"] == "rewrite" and fired:
            new, unsafe = rewrite(rule, t["input"])
            # rewrite: the exact output and nothing unsafe; block: an unsafe
            # match (the call is refused); pass: every match was data.
            ok = {"rewrite": new == t.get("output") and not unsafe,
                  "block": unsafe > 0,
                  "pass": not unsafe and new is None}[t["expect"]]
        elif t["expect"] == "rewrite":
            ok = False
        else:
            ok = fired == (t["expect"] == "block")
        out.append((t, ok))
    return out
