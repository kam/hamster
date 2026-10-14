"""Shared helpers for the decision-log hooks. Stdlib only, fails soft.

The log is `<repo>/docs/decisions.md`: one markdown table, one row per
decision, committed. Superseded rows move to `docs/decisions/archive.md`,
which no hook ever loads. Raw pasted sources (client emails, meeting notes)
live in `<repo>/.claude/decisions/sources/`, git-excluded — the log carries a
short quote, the path and a sha, never the source text.
"""

import hashlib
import json
import re
from pathlib import Path

from _common import redact, state_dir

LOG = "docs/decisions.md"
ARCHIVE = "docs/decisions/archive.md"
SOURCES = ".claude/decisions/sources"
EXCLUDE = ".claude/decisions/"
COLUMNS = ["ID", "Date", "Decision", "Why", "Rejected", "Decided by", "Channel", "Source", "Status"]
SOURCE_MAX = 200_000

LOG_RE = re.compile(r"(?:^|/)docs/decisions\.md$")
ID_RE = re.compile(r"^DEC-\d+$")
STATUS_RE = re.compile(r"^(proposed|decided|superseded by (DEC-\d+))$", re.I)
SHA_RE = re.compile(r"sha:([0-9a-f]{12})")

# Claude Code wraps every paste in the prompt as
#   <pasted_content id="…"> … </pasted_content id="…">
PASTE_RE = re.compile(
    r"<pasted_content\b[^>]*>\n?(.*?)\n?</pasted_content\b[^>]*>", re.S | re.I
)
HEADER_RE = re.compile(r"^\s*>?\s*(from|to|cc|subject|sent|date):\s+\S", re.I | re.M)
EMAIL_MARK_RE = re.compile(
    r"^\s*>?\s*(on .{4,200} wrote:\s*$|-{2,}\s*original message\s*-{2,}"
    r"|begin forwarded message:|-{5,}\s*forwarded message\s*-{5,})",
    re.I | re.M,
)
CUE_RE = re.compile(
    r"\b(decided|agreed|approved|sign(?:ed)?[- ]off|go(?:ing)? with|"
    r"let'?s go with|we'll use|confirmed|lgtm|green[- ]?light)\b",
    re.I,
)
PASTE_MIN = 200  # a non-email paste needs a cue and this many chars to count


# --- detection ---------------------------------------------------------------
def pastes(prompt):
    """Paste bodies marked by Claude Code. With no markers, the whole prompt
    is a candidate only when it is email-shaped (a short paste may arrive
    unmarked)."""
    found = PASTE_RE.findall(prompt or "")
    if found:
        return [p for p in found if p.strip()]
    return [prompt] if prompt and is_email(prompt) else []


def is_email(text):
    return len(HEADER_RE.findall(text or "")) >= 2 or bool(EMAIL_MARK_RE.search(text or ""))


def kind_of(paste):
    """'email', 'notes' (long paste carrying a decision cue) or None."""
    if is_email(paste):
        return "email"
    if len(paste) >= PASTE_MIN and CUE_RE.search(paste):
        return "notes"
    return None


def outside_pastes(prompt):
    return PASTE_RE.sub(" ", prompt or "")


# --- sources -----------------------------------------------------------------
def save_source(top, text, kind, today):
    """Redact, cap, write once by content hash. Returns (relpath, sha12)."""
    body = redact(text.replace("\r", ""))
    if len(body) > SOURCE_MAX:
        body = body[:SOURCE_MAX] + "\n[… truncated by hamster]"
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    sdir = Path(top) / SOURCES
    sdir.mkdir(parents=True, exist_ok=True)
    existing = sorted(sdir.glob(f"*-{sha}.txt"))
    path = existing[0] if existing else sdir / f"{today}-{kind}-{sha}.txt"
    if not existing:
        path.write_text(body, encoding="utf-8")
    return str(path.relative_to(top)), sha


# --- the log -----------------------------------------------------------------
def split_row(line):
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return None
    return [c.strip() for c in s[1:-1].split("|")]


def rows(text):
    """Table rows as dicts keyed by COLUMNS. Header and separator skipped.
    A row with the wrong cell count comes back with `_bad` set."""
    out = []
    header_seen = False
    for n, line in enumerate((text or "").splitlines(), 1):
        cells = split_row(line)
        if cells is None:
            continue
        if not header_seen:
            if [c.lower() for c in cells] == [c.lower() for c in COLUMNS]:
                header_seen = True
            continue
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        row = {"_line": n}
        if len(cells) != len(COLUMNS):
            row["_bad"] = f"{len(cells)} cells, expected {len(COLUMNS)}"
            row["ID"] = cells[0] if cells else ""
        else:
            row.update(zip(COLUMNS, cells))
        out.append(row)
    return out, header_seen


def status(row):
    m = STATUS_RE.match(row.get("Status", "").strip())
    return m.group(1).lower().split(" ")[0] if m else None


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# --- per-session state -------------------------------------------------------
def state_path(session_id):
    sid = re.sub(r"[^A-Za-z0-9_-]", "", str(session_id or ""))[:64] or "nosession"
    return state_dir("decisions") / f"{sid}.json"


def load_state(session_id):
    try:
        return json.loads(state_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"sources": []}


def save_state(session_id, state):
    try:
        state_path(session_id).write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass
