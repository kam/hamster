"""Lesson store with two backends: Navigator (when the `navigator` CLI is on
PATH) and Claude Code auto-memory (always). Hooks only *read* here — writes
are done by the model through the commands, so a hook never mutates the vault.
Every call fails soft to an empty result.
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import frontmatter, has_navigator, memory_dir  # noqa: E402

MAX_EXISTING = 15


def _nav(args, timeout=8):
    try:
        out = subprocess.run(
            ["navigator", *args], capture_output=True, text=True, errors="replace", timeout=timeout
        )
    except Exception:
        return None
    return out.stdout if out.returncode == 0 else None


def navigator_search(query, node_type="solutions", limit=5, source_project=None):
    """[(slug, title)] or [] — never raises."""
    if not has_navigator():
        return []
    args = ["search"]
    if query:
        args.append(query)
    args += ["--type", node_type, "--limit", str(limit), "--json"]
    if source_project:
        args += ["--source-project", source_project]
    raw = _nav(args)
    if not raw:
        return []
    try:
        hits = json.loads(raw)
    except ValueError:
        return []
    out = []
    for h in hits if isinstance(hits, list) else []:
        slug = h.get("slug") or h.get("id")
        title = h.get("title") or ""
        if slug:
            out.append((slug, title))
    return out


def navigator_get(slug):
    """Node record dict or None."""
    if not has_navigator():
        return None
    raw = _nav(["get", slug, "--json"])
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def memory_lessons(cwd, types=("feedback", "project"), limit=MAX_EXISTING):
    """[(name, description)] for auto-memory files of the given types, newest first."""
    mem = memory_dir(cwd)
    out = []
    if not mem.is_dir():
        return out
    files = sorted(mem.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files:
        if p.name == "MEMORY.md":
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:1200]
        except OSError:
            continue
        fm = frontmatter(head)
        if fm.get("type") and fm["type"] not in types:
            continue
        name = fm.get("name") or p.stem
        desc = fm.get("description", "")[:110]
        out.append((name, desc))
        if len(out) >= limit:
            break
    return out


def existing_lessons(cwd, query=None, project=None):
    """Merged view for the retro: Navigator solutions hits first, then auto-memory.
    Returns [(label, description)]; label is `solutions/<slug>` or the memory name."""
    out = [(slug, title) for slug, title in navigator_search(query, limit=5)] if query else []
    if project:
        for slug, title in navigator_search(None, limit=3, source_project=project):
            if all(slug != s for s, _ in out):
                out.append((slug, title))
    out += memory_lessons(cwd)
    return out


def memory_path_for(cwd, name):
    """Path of the auto-memory file whose `name:` or stem equals `name`, or None."""
    mem = memory_dir(cwd)
    if not mem.is_dir():
        return None
    direct = mem / f"{name}.md"
    if direct.exists():
        return direct
    for p in mem.glob("*.md"):
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:400]
        except OSError:
            continue
        if frontmatter(head).get("name") == name:
            return p
    return None


__all__ = [
    "existing_lessons",
    "memory_lessons",
    "memory_path_for",
    "navigator_get",
    "navigator_search",
]
