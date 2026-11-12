#!/usr/bin/env python3
"""Maintenance for queryable memory. Normal reads/writes use plain SQL.

Python 3.10+, standard library only. No daemon and no external dependencies.
"""

import argparse
from contextlib import closing
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

import memory_profile

ROOT = Path(__file__).resolve().parent
FIELDS = ("kind", "title", "detail", "status", "due_date", "amount", "confidence", "source")
KINDS = {"fact", "commitment", "question", "person", "goal"}
SECRET = re.compile(
    r"password|passwd|api[_ -]?key|secret|token|one.time.code|"
    r"account\s*(?:number|no\.?|#)|card\s*(?:number|no\.?|#)|"
    r"\b(?:\d[ -]?){13,19}\b|-----BEGIN .*PRIVATE KEY", re.I
)


def connect(path, readonly=False):
    path = Path(path).expanduser().resolve()
    mode = "ro" if readonly else "rw"
    db = sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA recursive_triggers = ON")
    if db.execute("PRAGMA user_version").fetchone()[0] != 1:
        db.close()
        raise ValueError("Expected schema version 1; initialize or migrate explicitly")
    return db


def initialize(path):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # O_EXCL avoids clobbering existing databases and gives new files mode 0600.
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        with closing(connect(path, readonly=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Existing database failed integrity_check")
        return path
    os.close(fd)
    with closing(sqlite3.connect(path)) as db:
        db.executescript((ROOT / "schema.sql").read_text())
    return path


def normalize(record):
    unknown = set(record) - set(FIELDS)
    if unknown:
        raise ValueError(f"Unknown item fields: {', '.join(sorted(unknown))}")
    item = dict(detail="", status="open", due_date=None, amount=None, confidence="reported")
    item.update(record)
    for name in ("kind", "title", "source"):
        if not isinstance(item.get(name), str) or not item[name].strip():
            raise ValueError(f"{name} must be a nonempty string")
    if item["kind"] not in KINDS:
        raise ValueError("Invalid kind")
    if item["status"] not in {"open", "done"}:
        raise ValueError("New items must be open or done")
    if item["confidence"] not in {"confirmed", "reported", "estimate"}:
        raise ValueError("Invalid confidence")
    if not isinstance(item["detail"], str):
        raise ValueError("detail must be a string")
    if item["due_date"] is not None:
        value = item["due_date"]
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError("due_date must be YYYY-MM-DD or null")
    value = item["amount"]
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ValueError("amount must be a finite number or null")
    return item


def insert_item(db, item):
    return db.execute(
        f"INSERT INTO items ({', '.join(FIELDS)}) VALUES ({', '.join('?' for _ in FIELDS)})",
        [item[field] for field in FIELDS],
    ).lastrowid


def supersede(db, old_id, replacement, carry_links=False):
    item = normalize(replacement)
    if item["source"].startswith("import:"):
        raise ValueError("import: sources are reserved for the importer")
    with db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM items WHERE id = ?", (old_id,)).fetchone()
        if old is None or old["status"] == "superseded":
            raise ValueError("Old item must exist and be current")
        new_id = insert_item(db, item)
        db.execute(
            "UPDATE items SET status = 'superseded', superseded_by = ?, "
            "updated_at = date('now') WHERE id = ?", (new_id, old_id)
        )
        # Explicit opt-in: the agent must decide which old connections still apply.
        if carry_links:
            db.execute(
                "INSERT INTO links SELECT ?, l.to_id, l.relation FROM links l "
                "JOIN items i ON i.id = l.to_id "
                "WHERE l.from_id = ? AND i.status != 'superseded'", (new_id, old_id)
            )
            db.execute(
                "INSERT INTO links SELECT l.from_id, ?, l.relation FROM links l "
                "JOIN items i ON i.id = l.from_id "
                "WHERE l.to_id = ? AND i.status != 'superseded'", (new_id, old_id)
            )
    return new_id


def prepare_import(paths, profile="tagged"):
    """Conservative candidate extraction. Never writes to the database.

    The default accepts tagged bullets and checkboxes. The memory-md profile
    additionally recognizes section kinds, status markers, amounts, and dates.
    Unrecognized prose stays in the source files. All candidates need review.
    """
    if profile not in {"tagged", "memory-md"}:
        raise ValueError("Unknown import profile")
    candidates = []
    skipped = 0
    seen = set()
    for filename in paths:
        path = Path(filename).expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        if profile == "memory-md":
            for number, raw, item in memory_profile.extract(path.read_text(encoding="utf-8")):
                if SECRET.search(raw):
                    skipped += 1
                    continue
                key = hashlib.sha256(f"{path}:{number}\n{raw}".encode()).hexdigest()
                item["source"] = f"markdown:{path}:{number}"
                candidates.append({"key": key, "approved": False, "item": item})
            continue
        fenced = False
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith(("```", "~~~")):
                fenced = not fenced
                continue
            if fenced:
                continue
            match = re.match(r"^\s*[-*+]\s+(?:\[([ xX])\]\s+)?(.+)$", line)
            if not match:
                continue
            check, content = match.groups()
            explicit = re.match(r"(fact|commitment|question|person|goal|debt):\s*(.+)$", content, re.I)
            if explicit:
                kind, content = explicit.groups()
                kind = "commitment" if kind.lower() == "debt" else kind.lower()
            elif check is not None:
                kind = "commitment"
            else:
                continue
            if SECRET.search(line):
                skipped += 1
                continue
            due = None
            due_match = re.search(r"\bdue\s*[:=]?\s*(\d{4}-\d{2}-\d{2})\b", content, re.I)
            if due_match:
                try:
                    due = date.fromisoformat(due_match[1]).isoformat()
                except ValueError:
                    pass
            # Amounts are intentionally left for review: '$30' may be a payment,
            # a total, or a disputed estimate, and the currency may be ambiguous.
            key = hashlib.sha256(f"{path}:{number}\n{line}".encode()).hexdigest()
            candidates.append({
                "key": key, "approved": False,
                "item": dict(kind=kind, title=content[:120], detail=content,
                             status="done" if check in ("x", "X") else "open",
                             due_date=due, amount=None, confidence="reported",
                             source=f"markdown:{path}:{number}"),
            })
    return candidates, skipped


def read_import(path):
    records = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict) or set(record) != {"key", "approved", "item"}:
            raise ValueError(f"Line {line_number}: expected key, approved, item")
        if type(record["approved"]) is not bool:
            raise ValueError(f"Line {line_number}: approved must be true or false")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(record["key"])):
            raise ValueError(f"Line {line_number}: key must be 1–128 letters, digits, _ or -")
        item = normalize(record["item"])
        if item["source"].startswith("import:"):
            raise ValueError("Provide the original source; import: is reserved")
        # Keep the full source location; no third table or sidecar receipt needed.
        item["source"] = f"import:{record['key']} {item['source']}"
        records.append((record["approved"], item))
    return records


def import_records(db, records, apply=False):
    result = dict(inserted=0, existing=0, unapproved=0)
    try:
        db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        seen = {}
        for approved, item in records:
            if not approved:
                result["unapproved"] += 1
                continue
            old = seen.get(item["source"])
            if old is None:
                old = db.execute("SELECT * FROM items WHERE source = ?", (item["source"],)).fetchone()
            if old is not None:
                # Lifecycle changes do not cause a retry to resurrect an old fact.
                if any(old[field] != item[field] for field in FIELDS if field != "status"):
                    raise ValueError("Import key/source already exists with different content; supersede it")
                result["existing"] += 1
                continue
            seen[item["source"]] = item
            if apply:
                insert_item(db, item)
            result["inserted"] += 1
        if apply:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    return result


def atomic_write(path, content):
    # Write in the destination directory, then rename; no half-written notes.
    fd, tmp = tempfile.mkstemp(prefix=".memory-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def export_obsidian(db, output):
    folder = Path(output).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = folder / ".queryable-memory-export"
    identity = str(Path(db.execute("PRAGMA database_list").fetchone()[2]).resolve())
    if not marker.exists():
        if any(folder.iterdir()):
            raise ValueError("Choose an empty dedicated export folder, not the vault root")
        atomic_write(marker, identity + "\n")
    elif marker.read_text().strip() != identity:
        raise ValueError("This export folder belongs to a different database path")
    # One consistent read snapshot, including the graph.
    with db:
        db.execute("BEGIN")
        rows = db.execute("SELECT * FROM items ORDER BY id").fetchall()
        links = db.execute("SELECT * FROM links ORDER BY from_id, to_id, relation").fetchall()
    outgoing, incoming = {}, {}
    for link in links:
        outgoing.setdefault(link["from_id"], []).append(link)
        incoming.setdefault(link["to_id"], []).append(link)
    for row in rows:
        note = ["---"]
        for key in row.keys():
            note.append(f"{key}: {json.dumps(row[key], ensure_ascii=False)}")
        note.extend(["---", "", f"# {row['title']}", "",
                     "> Generated mirror. Edit the SQLite database, not this note.", ""])
        if row["status"] == "superseded":
            note.extend([f"> SUPERSEDED — replaced by [[item-{row['superseded_by']}]].", ""])
        note.extend([row["detail"], "", "## Connections", ""])
        for link in outgoing.get(row["id"], []):
            note.append(f"- {link['relation']} → [[item-{link['to_id']}]]")
        for link in incoming.get(row["id"], []):
            note.append(f"- [[item-{link['from_id']}]] → {link['relation']}")
        target = folder / f"item-{row['id']}.md"
        if target.is_symlink():
            raise ValueError("Refusing to overwrite a symlink in the export folder")
        atomic_write(target, "\n".join(note) + "\n")
    return len(rows)


def backup(db, destination):
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(target)) as snapshot:
            db.backup(snapshot)
            if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup failed integrity_check")
    except Exception:
        target.unlink()
        raise
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="~/memory/memory.db", help="database path (default: ~/memory/memory.db)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create an empty database; never seed real memory")
    prepare = commands.add_parser("prepare-import", help="emit unapproved JSONL candidates from Markdown")
    prepare.add_argument("--profile", choices=("tagged", "memory-md"), default="tagged",
                         help="tagged bullets (default), or MEMORY.md section/prose patterns")
    prepare.add_argument("files", nargs="+")
    imp = commands.add_parser("import", help="preview or apply approved JSONL records")
    imp.add_argument("file")
    imp.add_argument("--apply", action="store_true", help="commit approved records; default is dry run")
    replace = commands.add_parser("supersede", help="atomically insert a replacement and retire the old fact")
    replace.add_argument("id", type=int)
    replace.add_argument("replacement", help="JSON file containing the new item")
    replace.add_argument("--carry-links", action="store_true", help="copy links to current neighbors after reviewing their meaning")
    export = commands.add_parser("export", help="export a one-way Obsidian mirror")
    export.add_argument("directory", help="dedicated, initially empty folder inside the vault")
    snap = commands.add_parser("backup", help="create a consistent SQLite snapshot")
    snap.add_argument("destination", help="new backup path; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            print(initialize(args.db))
        elif args.command == "prepare-import":
            rows, skipped = prepare_import(args.files, profile=args.profile)
            for row in rows:
                print(json.dumps(row, ensure_ascii=False))
            print(f"{len(rows)} unapproved candidates; {skipped} sensitive-looking lines skipped. "
                  "Review all content before approving. Unrecognized prose was not imported.", file=sys.stderr)
        else:
            readonly = args.command in {"export", "backup"} or (args.command == "import" and not args.apply)
            with closing(connect(args.db, readonly=readonly)) as db:
                if args.command == "import":
                    result = import_records(db, read_import(args.file), apply=args.apply)
                    print(json.dumps({"mode": "applied" if args.apply else "preview", **result}))
                elif args.command == "supersede":
                    item = json.loads(Path(args.replacement).read_text(encoding="utf-8"))
                    print(supersede(db, args.id, item, args.carry_links))
                elif args.command == "export":
                    print(f"Exported {export_obsidian(db, args.directory)} notes")
                elif args.command == "backup":
                    print(backup(db, args.destination))
    except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
