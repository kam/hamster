#!/usr/bin/env python3
"""PreToolUse guard for the decision log (`docs/decisions.md`, `docs/decisions/archive.md`).

Blocks (exit 2) a Write/Edit/MultiEdit whose resulting table would break:
  1. The header is exactly: ID | Date | Decision | Why | Rejected | Decided by | Channel | Source | Status
  2. Every row has nine cells, a unique `DEC-<n>` ID, a YYYY-MM-DD date and a Status of
     `proposed`, `decided` or `superseded by DEC-<n>`.
  3. A `decided` row names a person in `Decided by` — not empty, not a placeholder, not an
     agent, model or "the client" — and a known Channel.
  4. `superseded by DEC-<n>` points at another row that exists in the log or the archive.
Blocks, best effort, a Bash command that writes either file (redirect, tee, sed/perl -i,
cp, mv, rm, git checkout/restore): use Edit, so this guard sees the result. Quoted text and
heredoc bodies are ignored; an interpreter writing the file (`python -c`) is not caught.

Opt-in by header: a `docs/decisions.md` without the skill's header row (an ADR index,
prose) is never checked, and a Write that removes the header from a log is.

Shape, not truth: the guard cannot prove the named person decided. The record is
honest when a `decided` row is written from that person's own message, email or
AskUserQuestion answer — never from the session's own inference (that is `proposed`).

For an Edit the guard rebuilds the file from disk plus the replacement. If `old_string`
no longer matches, the call is allowed and Edit reports the mismatch. Once the target is
known to be the log, an internal error blocks (fail closed); an unreadable payload passes.
HAMSTER_DECISION_GUARD=off disables.
"""

import json
import os
import re
import sys
from pathlib import Path

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import redact
    from _decisions import ARCHIVE, COLUMNS, ID_RE, LOG, STATUS_RE, is_hamster_log, read, rows
except Exception:
    sys.exit(0)

TARGET_RE = re.compile(r"(?:^|/)docs/decisions(?:\.md|/archive\.md)$")
LOG_PATH = r"[^\s;&|<>'\"]*docs/decisions(?:\.md|/archive\.md)"
LOG_PATH_RE = re.compile(LOG_PATH)
CMD = r"(?:^|[;&|(]\s*|\b(?:sudo|xargs|env)\s+)"
# Best effort, run on the command with quoted text and heredoc bodies blanked.
BASH_WRITE_RE = re.compile(
    rf"(>>?\s*{LOG_PATH}"
    rf"|{CMD}(?:tee|truncate|rm|shred|dd)\b[^;&|]*{LOG_PATH}"
    rf"|{CMD}(?:sed|perl|ruby)\s+(?:-\S*\s+)*?-[A-Za-z]*i[^;&|]*{LOG_PATH}"
    rf"|{CMD}sed\b[^;&|]*--in-place[^;&|]*{LOG_PATH}"
    rf"|{CMD}(?:cp|mv|rsync|install|ln)\b[^;&|]*{LOG_PATH}\s*(?:$|[;&|)])"
    rf"|{CMD}git\s+(?:checkout|restore)\b[^;&|]*{LOG_PATH})"
)
QUOTED_RE = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\1\b", re.S)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CHANNELS = {
    "chat", "askuserquestion", "email", "meeting", "call", "slack", "teams", "sms",
    "whatsapp", "signed", "workshop", "ticket", "pr review",
}
PLACEHOLDER_RE = re.compile(
    r"^\s*(\[.*\]|<.*>|tbd|todo|n/?a|name|who|pending|unknown|-+|\?+)\s*$", re.I
)
NOT_A_PERSON = {
    "claude", "claude code", "assistant", "the assistant", "session", "the session", "agent",
    "subagent", "ai", "the ai", "llm", "bot", "model", "system", "opus", "sonnet", "fable",
    "haiku", "gpt", "codex", "hamster", "me", "user", "the user", "client", "the client",
    "team", "the team", "we", "us", "everyone", "stakeholders",
}
AGENT_SUBSTR_RE = re.compile(
    r"claude|chatgpt|codex|subagent|\b(llm|gpt|opus|sonnet|haiku|agent|bot|assistant|model)\b",
    re.I,
)


def block(msg):
    sys.stderr.write(
        "hamster decision-guard: BLOCKED\n" + msg + "\n\nFormat: the `decisions` skill. "
        "A `decided` row names the person who decided; what the session infers is `proposed`. "
        "(HAMSTER_DECISION_GUARD=off disables.)\n"
    )
    sys.exit(2)


def is_person(who):
    w = who.strip().strip("*_ ")
    if not w or PLACEHOLDER_RE.match(w) or w.lower() in NOT_A_PERSON:
        return False
    return not AGENT_SUBSTR_RE.search(w)


def strip_data(cmd):
    """Blank heredoc bodies and quoted strings, keeping a quoted string that is
    itself the log path (`tee "docs/decisions.md"`)."""
    cmd = HEREDOC_RE.sub(lambda m: m.group(0).split("\n", 1)[0], cmd)

    def keep_path(m):
        inner = m.group(0)[1:-1]
        return inner if LOG_PATH_RE.fullmatch(inner) else '""'

    return QUOTED_RE.sub(keep_path, cmd)


def bash_target_is_log(cmd, cwd):
    for p in LOG_PATH_RE.findall(cmd):
        p = os.path.expanduser(p)
        if is_hamster_log(read(p if os.path.isabs(p) else os.path.join(cwd, p))):
            return True
    return False


def check(text, other):
    table, header = rows(text)
    if not header:
        return "no table header row: | " + " | ".join(COLUMNS) + " |"
    other_ids = {r.get("ID", "") for r in other}
    other_by_id = {r.get("ID", ""): r for r in other}
    problems, seen = [], set()
    for r in table:
        where = f"line {r['_line']}"
        if r.get("_bad"):
            problems.append(f"{where}: {r['_bad']} (escape a literal pipe as \\|)")
            continue
        rid = r["ID"]
        if not ID_RE.match(rid):
            problems.append(f"{where}: ID `{rid}` is not DEC-<n>")
        elif rid in seen:
            problems.append(f"{where}: duplicate ID {rid}")
        elif rid in other_ids and other_by_id[rid] != {**r, "_line": other_by_id[rid]["_line"]}:
            # The same row in both files is an archive move in progress.
            problems.append(f"{where}: {rid} already used by a different row in the other file")
        seen.add(rid)
        secret = [c for c in COLUMNS if redact(r[c]) != r[c]]
        if secret:
            problems.append(f"{where}: {', '.join(secret)} looks like it holds a secret; redact it")
        if not DATE_RE.match(r["Date"]):
            problems.append(f"{where}: Date `{r['Date']}` is not YYYY-MM-DD")
        if not r["Decision"]:
            problems.append(f"{where}: empty Decision")
        m = STATUS_RE.match(r["Status"])
        if not m:
            problems.append(
                f"{where}: Status `{r['Status']}` — use proposed, decided or superseded by DEC-<n>"
            )
            continue
        st = m.group(1).lower()
        if st == "decided":
            if not is_person(r["Decided by"]):
                problems.append(
                    f"{where}: decided row needs a named person in Decided by, got "
                    f"`{r['Decided by']}`"
                )
            if r["Channel"].strip().lower() not in CHANNELS:
                problems.append(
                    f"{where}: Channel `{r['Channel']}` — one of {', '.join(sorted(CHANNELS))}"
                )
        elif st.startswith("superseded"):
            target = m.group(2).upper()
            if target == rid:
                problems.append(f"{where}: {rid} cannot supersede itself")
            elif target not in other_ids | {x.get("ID") for x in table}:
                problems.append(f"{where}: superseded by {target}, which no row has")
    return "\n".join(problems[:15]) or None


def resulting_text(tool, ti, path):
    if tool == "Write":
        return ti.get("content", "")
    current = read(path)
    if current is None:
        current = ""
    edits = ti.get("edits") if tool == "MultiEdit" else [ti]
    for e in edits or []:
        old, new = e.get("old_string", ""), e.get("new_string", "")
        if old not in current:
            return None
        current = current.replace(old, new) if e.get("replace_all") else current.replace(old, new, 1)
    return current


def main():
    if os.environ.get("HAMSTER_DECISION_GUARD", "on").lower() == "off":
        return
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    tool = data.get("tool_name")
    ti = data.get("tool_input") or {}
    if tool == "Bash":
        cmd = str(ti.get("command") or "")
        if "docs/decisions" not in cmd:
            return
        bare = strip_data(cmd)
        if BASH_WRITE_RE.search(bare) and bash_target_is_log(bare, data.get("cwd") or os.getcwd()):
            block("Bash writes to the decision log bypass this guard. Use Edit or Write.")
        return
    if tool not in ("Write", "Edit", "MultiEdit"):
        return
    raw = str(ti.get("file_path") or "")
    if not TARGET_RE.search(raw.replace("\\", "/")):
        return
    try:
        path = Path(raw if os.path.isabs(raw) else os.path.join(data.get("cwd") or os.getcwd(), raw))
        text = resulting_text(tool, ti, path)
        if text is None:
            return
        if not is_hamster_log(read(path)) and not is_hamster_log(text):
            return  # the repo's own docs/decisions.md, not this log
        is_log = path.name == "decisions.md"
        root = path.parents[1] if is_log else path.parents[2]  # the repo top
        sibling = root / (ARCHIVE if is_log else LOG)
        other, _ = rows(read(sibling) or "")
        problem = check(text, [r for r in other if not r.get("_bad")])
    except SystemExit:
        raise
    except Exception as exc:  # the target is the log: a broken guard is not an open gate
        block(f"internal error ({type(exc).__name__}: {exc}); fix the guard or set the override.")
    if problem:
        block(f"{raw}:\n{problem}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
