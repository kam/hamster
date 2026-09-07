#!/usr/bin/env python3
"""PreCompact hook: write a deterministic auto-snapshot before compaction.

Safety net for the `handoff` skill. PreCompact stdout is not added to
context, so this hook only writes to disk; handoff-load.py re-injects the
file on the SessionStart(compact) that follows.

Guarantees. Writes only inside a git work tree that is not $HOME, and only
after `.claude/handoffs/` is confirmed present in <git-common-dir>/info/exclude
(worktrees and submodules included). If exclusion cannot be confirmed,
nothing is written. Skipped when a manual `active` handoff for this branch
has `updated:` within HANDOFF_FRESH_MINUTES (default 30). Every field is
redacted with the shared secret filter. Verbatim prompts can be turned off
with HANDOFF_SNAPSHOT_PROMPTS=0. Files are timestamped to the minute (a
same-minute collision gets a `.2` suffix) and pruned to HANDOFF_KEEP_SNAPSHOTS per branch (default 5). Fails open.
"""

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import (
        HANDOFF_DIR,
        clip,
        ensure_excluded,
        env_int,
        git,
        parse_stamp,
        read_handoffs,
        repo_context,
        slug,
    )
    from _lm import SESSION_INSTRUCTIONS, ask
except Exception:  # a broken helper must never block a session or a compaction
    sys.exit(0)

MAX_PROMPTS = 10
PROMPT_LEN = 400
ASSISTANT_LEN = 800
MAX_FILES = 25
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
WRAPPERS = (
    "<command-name>",
    "<command-message>",
    "<local-command",
    "<system-reminder>",
    "<user-prompt-submit-hook>",
    "<task-notification",
)


def text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(
        b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"
    )


def is_tool_result(content):
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def edited_paths(content):
    """File paths touched by Edit/Write tool_use blocks in an assistant turn."""
    for block in content if isinstance(content, list) else []:
        if not (isinstance(block, dict) and block.get("type") == "tool_use"):
            continue
        if block.get("name") not in EDIT_TOOLS:
            continue
        inp = block.get("input") or {}
        fp = inp.get("file_path") or inp.get("notebook_path")
        if fp:
            yield fp


def records(transcript):
    """Parsed JSONL records from the transcript; bad lines and missing files yield nothing."""
    if not transcript or not os.path.exists(transcript):
        return
    with open(transcript, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except Exception:
                continue


def user_prompt(rec, content):
    """The prompt text of a real user turn, else None (meta, tool_result, wrappers)."""
    if rec.get("isMeta") or is_tool_result(content):
        return None
    t = text_of(content).strip()
    return t if t and not t.startswith(WRAPPERS) else None


def scan(transcript):
    prompts, files, last_assistant, turn = [], [], ("", 0), 0
    for rec in records(transcript):
        content = (rec.get("message") or {}).get("content")
        if rec.get("type") == "user":
            t = user_prompt(rec, content)
            if t:
                turn += 1
                prompts.append(t)
        elif rec.get("type") == "assistant":
            t = text_of(content).strip()
            if t:
                last_assistant = (t, turn)
            for fp in edited_paths(content):
                if fp not in files:
                    files.append(fp)
    return prompts, files, last_assistant


def fresh_manual_exists(hdir, branch, minutes):
    cutoff = dt.datetime.now() - dt.timedelta(minutes=minutes)
    for _p, _text, fm in read_handoffs(hdir):
        if fm["status"] == "active" and fm["branch"] == branch:
            stamp = parse_stamp(fm.get("updated"))
            if stamp and stamp >= cutoff:
                return True
    return False


def snapshot_path(hdir, now, branch_slug):
    """Minute-stamped name; a second write in the same minute gets `.2`, `.3`…
    rather than overwriting the first."""
    stem = f"{now:%Y-%m-%d-%H%M}"
    path = hdir / f"{stem}-{branch_slug}-auto-snapshot.md"
    n = 1
    while path.exists():
        n += 1
        path = hdir / f"{stem}.{n}-{branch_slug}-auto-snapshot.md"
    return path


def prune(hdir, branch_slug, keep):
    # Anchored match: `demo` must not claim `feature-demo`'s snapshots.
    own = re.compile(
        r"^\d{4}-\d{2}-\d{2}-\d{4}(?:\.\d+)?-" + re.escape(branch_slug) + r"-auto-snapshot\.md$"
    )
    snaps = sorted(
        (p for p in hdir.glob("*-auto-snapshot.md") if own.match(p.name)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in snaps[keep:]:
        try:
            old.unlink()
        except Exception:
            pass


def render(cwd, top, branch, now, trigger, prompts, files, last_text, last_turn):
    """Markdown lines for the snapshot. Pure apart from three read-only git calls."""
    want_prompts = os.environ.get("HANDOFF_SNAPSHOT_PROMPTS", "1") != "0"
    status = clip(git_or(["status", "--short"], cwd, "(clean)"), 1500)
    log = clip(git_or(["log", "--oneline", "-5"], cwd, "(no commits)"), 800)
    ahead = git_or(["rev-list", "--count", "@{upstream}..HEAD"], cwd, None)

    def relpath(f):
        f = os.path.relpath(f, top) if f.startswith(top) else f
        return clip(f, 200)

    lines = [
        "---",
        "status: auto-snapshot",
        f"branch: {branch}",
        f"project: {os.path.basename(top)}",
        f"created: {now:%Y-%m-%dT%H:%M}",
        f"updated: {now:%Y-%m-%dT%H:%M}",
        "next_action: Read this snapshot, then run /handoff to write a reviewed handoff",
        f"trigger: {trigger}",
        "---",
        "",
        f"# Auto-snapshot before compaction — {branch}",
        "",
        "Hook-written from the transcript and git. No reasoning was captured; "
        "decisions and rejected options must be reconstructed from the prompts "
        "below and the code. Prefer `/handoff` before the next compaction.",
        "",
        "## Current state",
        "",
        f"- Branch `{branch}`"
        + (f", {ahead} commit(s) ahead of upstream" if ahead and ahead != "0" else ""),
        "- `git status --short`:",
        "",
        "```",
        status,
        "```",
        "",
        "- Recent commits:",
        "",
        "```",
        log,
        "```",
        "",
        "## Files edited this session",
        "",
    ]
    lines += [f"- `{relpath(f)}`" for f in files[-MAX_FILES:]] or ["- (none recorded)"]
    if want_prompts:
        shown = prompts[-MAX_PROMPTS:]
        lines += [
            "",
            f"## Last {len(shown)} of {len(prompts)} user prompts (verbatim, clipped, redacted)",
            "",
        ]
        lines += [f"{i}. {clip(p, PROMPT_LEN)}" for i, p in enumerate(shown, 1)] or ["(none)"]
    else:
        lines += ["", "## User prompts", "", "(capture disabled: HANDOFF_SNAPSHOT_PROMPTS=0)"]
    if os.environ.get("HANDOFF_SNAPSHOT_LM", "1") != "0":
        src = "\n".join(f"User: {clip(p, 600)}" for p in prompts[-MAX_PROMPTS:])
        src += "\n\nAssistant (last): " + clip(last_text, 3000)
        summary = ask(src, SESSION_INSTRUCTIONS, 700, tier="quality")
        if summary:
            lines += ["", "## Local summary (local model, unverified)", "", summary]
    lines += [
        "",
        f"## Last text-bearing assistant message (after user prompt {last_turn} of {len(prompts)}; clipped)",
        "",
        clip(last_text, ASSISTANT_LEN) or "(none)",
        "",
        "## Audit log",
        "",
        f"- {now:%Y-%m-%d %H:%M} auto-snapshot written by handoff-precompact.py (trigger: {trigger})",
        "",
    ]
    return lines


def main():
    data = json.load(sys.stdin)
    cwd = data.get("cwd") or os.getcwd()
    top, branch, common = repo_context(cwd)
    if not top:
        return
    hdir = Path(top) / HANDOFF_DIR
    fresh_min = env_int("HANDOFF_FRESH_MINUTES", 30)
    if hdir.is_dir() and fresh_manual_exists(hdir, branch, fresh_min):
        return
    if not ensure_excluded(common):
        return  # never write unexcluded state into a repo

    prompts, files, (last_text, last_turn) = scan(data.get("transcript_path"))
    now = dt.datetime.now()
    bslug = slug(branch)
    hdir.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(hdir, now, bslug)
    trigger = data.get("trigger", "unknown")

    lines = render(cwd, top, branch, now, trigger, prompts, files, last_text, last_turn)
    path.write_text("\n".join(lines), encoding="utf-8")
    prune(hdir, bslug, env_int("HANDOFF_KEEP_SNAPSHOTS", 5))


def git_or(args, cwd, default):
    out = git(args, cwd)
    return out or default


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
