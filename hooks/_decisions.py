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
import subprocess
import time
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
# The closing tag repeats the id, so nested or adjacent pastes pair correctly.
PASTE_RE = re.compile(
    r"<pasted_content(\s[^>]*)?>\n?(.*?)\n?</pasted_content\1>", re.S | re.I
)
HEADER_RE = re.compile(r"^\s*>?\s*(from|to|cc|subject|sent|date):\s+\S", re.I | re.M)
# A line that reads as a log, stack trace or code rather than prose.
NOISE_LINE_RE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2}[T ]\d|\[?\d{2}:\d{2}:\d{2}|at \S+\(|File \"|[#$>] |commit [0-9a-f]{7,}"
    r"|[{}()\[\];]|.*[{};]\s*$|.*\s(=|==|=>|->)\s)"
)
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
    found = [m.group(2) for m in PASTE_RE.finditer(prompt or "")]
    if found:
        return [p for p in found if p.strip()]
    return [prompt] if prompt and is_email(prompt) else []


def is_email(text):
    """Two distinct header names, one of them From or Subject (a `git log`
    paste repeats Date: only), or a reply / forward marker."""
    names = {h.lower() for h in HEADER_RE.findall(text or "")}
    if len(names) >= 2 and names & {"from", "subject"}:
        return True
    return bool(EMAIL_MARK_RE.search(text or ""))


def prose_lines(text):
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return [ln for ln in lines if not NOISE_LINE_RE.match(ln) and len(ln.split()) >= 4], len(lines)


def kind_of(paste):
    """'email', 'notes' (long paste carrying a decision cue) or None."""
    if is_email(paste):
        return "email"
    if len(paste) < PASTE_MIN:
        return None
    prose, total = prose_lines(paste)
    # Notes are mostly prose and carry the cue in a prose line; a CI log or
    # `gh pr view` saying "APPROVED" is mostly noise lines.
    if total and len(prose) * 2 >= total and any(CUE_RE.search(ln) for ln in prose):
        return "notes"
    return None


def outside_pastes(prompt):
    return PASTE_RE.sub(" ", prompt or "")


# --- sources -----------------------------------------------------------------
def excluded(top, rel=SOURCES + "/x.txt"):
    """True when git really ignores the sources dir (a `.gitignore` negation
    outranks info/exclude)."""
    try:
        return subprocess.run(
            ["git", "check-ignore", "-q", "--", rel], cwd=top, capture_output=True, timeout=5
        ).returncode == 0
    except Exception:
        return False


def prune_state(days=30):
    cutoff = time.time() - days * 86400
    for p in state_dir("decisions").glob("*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


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
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")


def split_row(line):
    """Cells of a table line; `\\|` is a literal pipe inside a cell."""
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|") and not s.endswith("\\|")):
        return None
    return [c.strip() for c in CELL_SPLIT_RE.split(s[1:-1])]


def is_hamster_log(text):
    """True when the file carries this skill's header row. A repo's own
    `docs/decisions.md` (an ADR index, prose) is never touched."""
    return rows(text or "")[1]


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
