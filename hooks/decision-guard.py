#!/usr/bin/env python3
"""PreToolUse guard for the decision log (`docs/decisions.md`, `docs/decisions/archive.md`).

Blocks (exit 2) a Write/Edit/MultiEdit whose resulting table would break:
  1. The header is exactly: ID | Date | Decision | Why | Rejected | Decided by | Channel | Source | Status
  2. Every row has nine cells, a unique `DEC-<n>` ID, a YYYY-MM-DD date and a Status of
     `proposed`, `decided` or `superseded by DEC-<n>`.
  3. A `decided` row names a person in `Decided by` — not empty, not a placeholder, not an
     agent, model or "the client" — and a known Channel.
  4. `superseded by DEC-<n>` points at another row that exists in the log or the archive.
Blocks a Bash command that writes either file (redirect, tee, sed -i, cp, mv): use Edit,
so this guard sees the result.

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
    from _decisions import ARCHIVE, COLUMNS, ID_RE, LOG, STATUS_RE, read, rows
except Exception:
    sys.exit(0)

TARGET_RE = re.compile(r"(?:^|/)docs/decisions(?:\.md|/archive\.md)$")
BASH_WRITE_RE = re.compile(
    r"(>\s*['\"]?[^\s;&|]*docs/decisions"
    r"|\btee\b[^;&|]*docs/decisions"
    r"|\bsed\s+-[A-Za-z]*i[^;&|]*docs/decisions"
    r"|\b(?:cp|mv|rsync|install)\b[^;&|]*docs/decisions(?:\.md|/archive\.md)\s*(?:$|[;&|]))"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CHANNELS = {
    "chat", "askuserquestion", "email", "meeting", "call", "slack", "teams", "sms",
    "whatsapp", "signed", "workshop", "ticket", "pr review",
}
PLACEHOLDER_RE = re.compile(r"^\s*(\[|<|tbd|todo|n/?a\b|name\b|who\b|pending|-+$|\?)", re.I)
NOT_A_PERSON = {
    "claude", "claude code", "assistant", "the assistant", "session", "the session", "agent",
    "subagent", "ai", "the ai", "llm", "bot", "model", "system", "opus", "sonnet", "fable",
    "haiku", "gpt", "codex", "hamster", "me", "user", "the user", "client", "the client",
    "team", "the team", "we", "us", "everyone", "stakeholders",
}
AGENT_SUBSTR_RE = re.compile(
    r"claude|chatgpt|codex|subagent|\b(llm|ai|gpt|opus|sonnet|haiku|fable|agent|bot|assistant|model)\b",
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


def check(text, other_ids):
    table, header = rows(text)
    if not header:
        return "no table header row: | " + " | ".join(COLUMNS) + " |"
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
        seen.add(rid)
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
        if "docs/decisions" in cmd and BASH_WRITE_RE.search(cmd):
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
        is_log = path.name == "decisions.md"
        root = path.parents[1] if is_log else path.parents[2]  # the repo top
        sibling = root / (ARCHIVE if is_log else LOG)
        other, _ = rows(read(sibling) or "")
        problem = check(text, {r.get("ID", "") for r in other})
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
