"""Explicit patterns for prose bullets in MEMORY.md; no inference or approval.

Keep these patterns small and documented in docs/memory-md-profile.md. This
module only produces candidates; memory.py handles provenance and secret checks.
"""

from datetime import date
from decimal import Decimal
import math
import re


SECTION_KINDS = {
    "commitment": "commitment", "commitments": "commitment",
    "debt": "commitment", "debts": "commitment",
    "fact": "fact", "facts": "fact",
    "people": "person", "people index": "person", "person": "person",
    "goal": "goal", "goals": "goal",
    "question": "question", "questions": "question", "open questions": "question",
}
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)(?:\s+#+)?\s*$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(?:\[([ xX])\]\s+)?(.+)$")
TAG = re.compile(r"^(fact|commitment|question|person|goal|debt):\s*(.+)$", re.I | re.S)
QUESTION = re.compile(r"\b(?:still\s+open|awaiting\s+his\s+answer|unanswered)\b", re.I)
STATUS = re.compile(r"\b(?:OPEN|RESOLVED|CLOSED|CONFLICT)\b")
MONTHS = {month: i for i, month in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
)}
MONTH_PATTERN = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
)
DUE_DATE = re.compile(
    rf"\bdue\s*[:=]?\s*(?:on\s+)?(\d{{4}}-\d{{2}}-\d{{2}}|"
    rf"{MONTH_PATTERN}\s+\d{{1,2}},?\s+\d{{4}})(?![\w/-])", re.I
)
PAREN_DATE = re.compile(r"\(\s*(\d{4}-\d{2}-\d{2})\s*\)")
DOLLAR = re.compile(r"(?<!\\)\$")
AMOUNT = re.compile(
    r"(?<![\w\\$])(?P<before>-?)\$\s*(?P<after>-?)"
    r"(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)(?!\w|\.\d|,\d)"
)


def plain(text):
    """Ignore emphasis delimiters for matching; preserve original text in detail."""
    return text.replace("**", "").replace("__", "")


def status_for(text, check, notes):
    markers = set(STATUS.findall(text))
    if "CONFLICT" in markers:
        notes.append("CONFLICT marker: kept open; resolve the conflicting information.")
        return "open"
    if "OPEN" in markers and markers & {"RESOLVED", "CLOSED"}:
        notes.append("Contradictory status markers: kept open for review.")
        return "open"
    if markers & {"RESOLVED", "CLOSED"}:
        return "done"
    if "OPEN" in markers:
        return "open"
    return "done" if check in ("x", "X") else "open"


def amount_for(text, notes):
    matches = list(AMOUNT.finditer(text))
    dollars = len(DOLLAR.findall(text))
    if not dollars:
        return None
    if len(matches) != dollars or any(
        (m["before"] and m["after"]) or re.match(r"\s*[-–—]\s*\$?\d", text[m.end():])
        for m in matches
    ):
        notes.append("Unrecognized or ranged dollar amount: amount left unset.")
        return None
    values = {Decimal((m["before"] or m["after"]) + m["number"].replace(",", "")) for m in matches}
    if len(values) != 1:
        notes.append("Multiple distinct dollar amounts: amount left unset; review or split the bullet.")
        return None
    value = float(values.pop())
    if not math.isfinite(value):
        notes.append("Dollar amount is outside the supported numeric range: amount left unset.")
        return None
    return value


def parse_date(value):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value).isoformat()
    month, day, year = value.replace(",", "").split()
    return date(int(year), MONTHS[month[:3].lower()], int(day)).isoformat()


def date_for(text, notes):
    matches = DUE_DATE.findall(text)
    due_labels = len(re.findall(r"\bdue\b", text, re.I))
    if due_labels != len(matches):
        # A recognized date must not hide a second, incomplete due-date phrase.
        notes.append("Due date not recognized with a full year: due_date left unset.")
        return None
    parenthesized = False
    if not matches:
        matches = PAREN_DATE.findall(text)
        parenthesized = bool(matches)
    if not matches:
        return None
    try:
        values = {parse_date(value) for value in matches}
    except ValueError:
        notes.append("Invalid calendar date: due_date left unset.")
        return None
    if len(values) != 1:
        notes.append("Multiple distinct dates: due_date left unset; review or split the bullet.")
        return None
    if parenthesized:
        notes.append("Parenthesized date proposed as due_date; verify it is a deadline, not a note date.")
    return values.pop()


def parse_bullet(content, check, section_kind):
    text = plain(content)
    tag = TAG.match(text)
    if QUESTION.search(text):
        kind = "question"
    elif tag:
        kind = "commitment" if tag[1].lower() == "debt" else tag[1].lower()
    elif section_kind:
        kind = section_kind
    elif check is not None:
        kind = "commitment"
    else:
        return None
    notes = []
    status = status_for(text, check, notes)
    amount = amount_for(text, notes)
    due = date_for(text, notes)
    # Use a leading bold label, optionally after a status marker, as the title.
    title_text = re.sub(
        r"^(?:(?:\*\*|__)?\[?(?:OPEN|RESOLVED|CLOSED|CONFLICT)\]?(?:\*\*|__)?[\s:—–-]+)+",
        "", content,
    )
    label = re.match(r"^(?:\*\*(.+?)\*\*|__(.+?)__)", title_text)
    label_text = (label[1] or label[2]).strip().rstrip(":") if label else ""
    if label_text and not STATUS.fullmatch(label_text):
        title = label_text
    else:
        title = (tag[2] if tag else text).splitlines()[0].strip()
    detail = content
    if notes:
        detail += "\n\n[Import review: " + " ".join(notes) + "]"
    return dict(kind=kind, title=title[:120], detail=detail, status=status,
                due_date=due, amount=amount, confidence="reported")


def extract(text):
    """Yield (line number, original bullet block, item) for recognized bullets.

    Unknown subsections inherit a known parent; sibling/parent headings reset
    context. Indented continuation lines belong to their bullet. Fenced code is
    skipped, and nested bullets remain separate candidates.
    """
    headings = []
    fence = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        opening = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if fence:
            if opening and opening[1][0] == fence[0] and len(opening[1]) >= fence[1] and not opening[2].strip():
                fence = None
            i += 1
            continue
        if opening:
            fence = (opening[1][0], len(opening[1]))
            i += 1
            continue
        heading = HEADING.match(line)
        if heading:
            level = len(heading[1])
            while headings and headings[-1][0] >= level:
                headings.pop()
            name = " ".join(plain(heading[2]).strip().rstrip(":").lower().split())
            headings.append((level, SECTION_KINDS.get(name)))
            i += 1
            continue
        bullet = BULLET.match(line)
        if not bullet:
            i += 1
            continue
        start = i
        indent, check, content = bullet.groups()
        i += 1
        while i < len(lines):
            continuation = lines[i]
            if (not continuation.strip() or BULLET.match(continuation) or HEADING.match(continuation)
                    or re.match(r"^\s*(?:`{3,}|~{3,})", continuation)
                    or len(continuation) - len(continuation.lstrip()) <= len(indent)):
                break
            content += "\n" + continuation.strip()
            i += 1
        section_kind = next((kind for _, kind in reversed(headings) if kind), None)
        item = parse_bullet(content, check, section_kind)
        if item:
            yield start + 1, "\n".join(lines[start:i]), item
