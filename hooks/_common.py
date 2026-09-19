"""Shared helpers for every hamster hook. Kept dependency-free (stdlib only).

Hooks import this file by path (sys.path insert of their own dir).
Every helper fails soft: bad input yields None / defaults, never an exception
the caller has to handle.
"""

import datetime as dt
import os
import re
import subprocess
from pathlib import Path

HANDOFF_DIR = ".claude/handoffs"
EXCLUDE_LINE = ".claude/handoffs/"

# --- secrets -----------------------------------------------------------------
# Shape list first (cheap, precise), then key=value, then a generic
# high-entropy catch-all. Every snapshot field passes through redact().
_SHAPES = [
    r"sk-[A-Za-z0-9_-]{16,}",  # OpenAI / Anthropic (sk-ant-, sk-proj-)
    r"sk_(?:live|test)_[A-Za-z0-9]{16,}",  # Stripe
    r"rk_(?:live|test)_[A-Za-z0-9]{16,}",
    r"AKIA[A-Z0-9]{16}",  # AWS access key id
    r"AIza[0-9A-Za-z_-]{35}",  # Google API key
    r"ya29\.[0-9A-Za-z_-]{20,}",  # Google OAuth
    r"gh[pousr]_[A-Za-z0-9]{20,}",  # GitHub tokens
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"glpat-[A-Za-z0-9_-]{20,}",  # GitLab
    r"xox[abposr]-[A-Za-z0-9-]{10,}",  # Slack
    r"xapp-[A-Za-z0-9-]{10,}",
    r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",  # JWT
    r"-----BEGIN[^-]{0,40}-----",  # PEM headers (any kind)
    r"PuTTY-User-Key-File-\d",
    r"[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@",  # scheme://user:pass@
    r"(?i:bearer)\s+[A-Za-z0-9._~+/=-]{16,}",
    r"(?i:api[_-]?key|secret|token|passw(?:or)?d|pwd|auth)"  # key: value / key=value
    r"[A-Za-z0-9_-]*\s*[:=]\s*[\"']?[^\s\"',;]{6,}",
    r"\b[A-Za-z0-9+/]{40,}={0,2}\b",  # long base64-ish blobs
    r"\b[0-9a-f]{48,}\b",  # long hex (private keys, hashes)
]
SECRET = re.compile("|".join(f"(?:{s})" for s in _SHAPES))


def redact(text):
    return SECRET.sub("<redacted>", text or "")


def clip(text, n):
    text = redact((text or "").replace("\r", ""))
    return text if len(text) <= n else text[:n] + " …"


# --- env ---------------------------------------------------------------------
def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- git ---------------------------------------------------------------------
def git(args, cwd):
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace", timeout=5
        )
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def repo_context(cwd):
    """(toplevel, branch_key, git_common_dir). toplevel is None outside a
    work tree or when it resolves to $HOME. branch_key is the branch name, or
    `detached@<sha7>` — the same string in both hooks, so a snapshot written
    on a detached HEAD reloads on that HEAD."""
    top = git(["rev-parse", "--show-toplevel"], cwd)
    if not top or os.path.realpath(top) == os.path.realpath(str(Path.home())):
        return None, None, None
    branch = git(["branch", "--show-current"], cwd)
    if not branch:
        sha = git(["rev-parse", "--short=7", "HEAD"], cwd) or "unknown"
        branch = f"detached@{sha}"
    common = git(["rev-parse", "--git-common-dir"], cwd)
    if common and not os.path.isabs(common):
        common = os.path.join(cwd, common)
    return top, branch, common


def is_tracked(path, cwd):
    """True when git knows the file (index or HEAD). Tracked handoffs came
    from someone else's commit and are never loaded."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", str(path)],
            cwd=cwd,
            capture_output=True,
            timeout=5,
        )
        return out.returncode == 0
    except Exception:
        return True  # unknown → treat as untrusted


def ensure_excluded(common_dir):
    """Append the exclude line to <git-common-dir>/info/exclude. Returns True
    only when the line is present afterwards. Worktrees and submodules share
    a common dir, so this works where `.git` is a file."""
    if not common_dir:
        return False
    try:
        exclude = Path(common_dir) / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8", errors="replace") if exclude.exists() else ""
        if EXCLUDE_LINE in existing.splitlines():
            return True
        with open(exclude, "a", encoding="utf-8") as fh:
            fh.write(
                ("" if existing.endswith("\n") or not existing else "\n") + EXCLUDE_LINE + "\n"
            )
        return True
    except Exception:
        return False


# --- frontmatter -------------------------------------------------------------
def frontmatter(text):
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fm


def read_handoffs(hdir):
    """Yield (path, text, frontmatter) for every *.md in hdir that has a
    `status:` and `branch:`. Unreadable files are skipped. Both hooks select
    candidates through this one function so they agree on what counts."""
    for p in sorted(hdir.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
        except Exception:
            continue
        fm = frontmatter(text)
        if fm.get("status") and fm.get("branch"):
            yield p, text, fm


def parse_stamp(value):
    """ISO date or date-time → naive local datetime, or None. Offset-aware
    stamps are converted to local time first. Future stamps are rejected so
    `updated: 9999-…` cannot win the sort."""
    if not value:
        return None
    try:
        stamp = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo:
        stamp = stamp.astimezone().replace(tzinfo=None)  # local wall-clock
    if stamp > dt.datetime.now() + dt.timedelta(minutes=5):
        return None
    return stamp


def file_stamp(path, fm):
    """Best timestamp for ordering: parsed `updated:`/`created:`, else mtime."""
    return (
        parse_stamp(fm.get("updated"))
        or parse_stamp(fm.get("created"))
        or dt.datetime.fromtimestamp(path.stat().st_mtime)
    )


def slug(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:80] or "x"


# --- hamster state -----------------------------------------------------------
def claude_home():
    return Path(os.environ.get("CLAUDE_HOME") or (Path.home() / ".claude"))


def state_dir(*parts):
    """~/.claude/hamster/<parts...>, created on demand. HAMSTER_STATE overrides."""
    base = Path(os.environ.get("HAMSTER_STATE") or (claude_home() / "hamster"))
    p = base.joinpath(*parts) if parts else base
    try:
        (p if not parts or not p.suffix else p.parent).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def memory_dir(cwd):
    """Claude Code auto-memory directory for a project cwd."""
    return claude_home() / "projects" / re.sub(r"[/.]", "-", cwd) / "memory"


def has_navigator():
    import shutil

    return shutil.which("navigator") is not None
