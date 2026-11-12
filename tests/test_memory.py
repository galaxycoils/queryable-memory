import contextlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import memory


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "memory.db"
        memory.initialize(self.path)
        self.db = memory.connect(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def item(self, **changes):
        data = dict(kind="fact", title="Example", detail="Synthetic", source="test")
        data.update(changes)
        return memory.normalize(data)

    def add(self, **changes):
        with self.db:
            return memory.insert_item(self.db, self.item(**changes))

    def query(self, name, **bindings):
        return self.db.execute((memory.ROOT / "queries" / f"{name}.sql").read_text(), bindings).fetchall()

    def demo(self):
        self.db.executescript((memory.ROOT / "examples/demo.sql").read_text())

    def test_only_two_tables_and_initialization_preserves_data(self):
        self.add()
        memory.initialize(self.path)
        tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        self.assertEqual([r[0] for r in tables], ["items", "links"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM items").fetchone()[0], 1)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_init_refuses_unknown_database(self):
        other = self.root / "unknown.db"
        with sqlite3.connect(other) as db:
            db.execute("CREATE TABLE unrelated (id INTEGER)")
        with self.assertRaises(ValueError):
            memory.initialize(other)

    def test_missing_database_is_not_silently_created(self):
        with self.assertRaises(sqlite3.OperationalError):
            memory.connect(self.root / "missing.db")

    def test_required_example_queries(self):
        self.demo()
        self.assertEqual([r["id"] for r in self.query("due", through="2026-11-20")], [3, 5])
        self.assertEqual([r["id"] for r in self.query("people", item_id=1)], [2])
        self.assertEqual([r["id"] for r in self.query("questions")], [4])
        # The literal queries from the PDF work too, on the synthetic fixture.
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM items WHERE kind='commitment' AND status='open' AND due_date <= '2026-11-20'"
        ).fetchone()[0], 2)
        self.assertEqual(self.db.execute(
            "SELECT i.title, l.relation FROM items i JOIN links l ON l.to_id=i.id "
            "WHERE l.from_id=(SELECT id FROM items WHERE title='Radar dispute')"
        ).fetchall()[0][0], "Example person")

    def test_invalid_values_rejected_by_raw_sql(self):
        for field, value in [("kind", "unknown"), ("confidence", "certain"), ("status", "active"),
                             ("due_date", "2026-02-30"), ("due_date", "tomorrow"),
                             ("due_date", "2026-11-31"), ("amount", "thirty")]:
            with self.subTest(field=field, value=value), self.assertRaises(sqlite3.IntegrityError), self.db:
                self.db.execute(f"INSERT INTO items (kind,title,source,{field}) VALUES ('fact','x','test',?)"
                                if field != "kind" else "INSERT INTO items (title,source,kind) VALUES ('x','test',?)", (value,))

    def test_leap_day_valid(self):
        self.add(due_date="2028-02-29")
        with self.assertRaises(ValueError):
            self.item(due_date="2026-02-29")

    def test_deletion_and_content_edit_rejected(self):
        old = self.add()
        for sql in ["DELETE FROM items WHERE id=?", "UPDATE items SET detail='Changed' WHERE id=?"]:
            with self.assertRaises(sqlite3.IntegrityError), self.db:
                self.db.execute(sql, (old,))

    def test_replace_rejected_even_without_recursive_triggers(self):
        old = self.add()
        self.db.execute("PRAGMA recursive_triggers=OFF")
        with self.assertRaises(sqlite3.IntegrityError), self.db:
            self.db.execute("INSERT OR REPLACE INTO items(id,kind,title,source) VALUES (?,'fact','changed','test')", (old,))
        self.assertEqual(self.db.execute("SELECT title FROM items WHERE id=?", (old,)).fetchone()[0], "Example")

    def test_status_can_be_completed_and_reopened(self):
        old = self.add(kind="question")
        with self.db:
            self.db.execute("UPDATE items SET status='done', updated_at=date('now') WHERE id=?", (old,))
        self.assertFalse(self.query("questions"))
        with self.db:
            self.db.execute("UPDATE items SET status='open', updated_at=date('now') WHERE id=?", (old,))
        self.assertEqual(len(self.query("questions")), 1)

    def test_supersession_retains_history_and_copies_both_directions(self):
        old = self.add()
        person = self.add(kind="person")
        goal = self.add(kind="goal")
        with self.db:
            self.db.executemany("INSERT INTO links VALUES (?,?,?)", [(old, person, "related_to"), (goal, old, "part_of")])
        new = memory.supersede(self.db, old, self.item(title="Updated"), carry_links=True)
        self.assertEqual(self.db.execute("SELECT superseded_by FROM items WHERE id=?", (old,)).fetchone()[0], new)
        self.assertEqual(self.db.execute("SELECT count(*) FROM links").fetchone()[0], 4)
        self.assertEqual([r["id"] for r in self.query("people", item_id=new)], [person])
        self.assertFalse(self.query("people", item_id=old))
        self.assertEqual([r["id"] for r in self.query("history", item_id=old)], [old, new])
        with self.assertRaises(ValueError):
            memory.supersede(self.db, old, self.item())

    def test_supersession_link_carry_is_opt_in(self):
        old, person = self.add(), self.add(kind="person")
        with self.db:
            self.db.execute("INSERT INTO links VALUES (?,?,'related_to')", (old, person))
        new = memory.supersede(self.db, old, self.item())
        self.assertFalse(self.query("people", item_id=new))
        self.assertEqual(self.db.execute("SELECT count(*) FROM links").fetchone()[0], 1)

    def test_failed_supersession_rolls_back_insert(self):
        old = self.add()
        self.db.executescript("CREATE TRIGGER fail_update BEFORE UPDATE ON items BEGIN SELECT RAISE(ABORT,'test failure'); END;")
        with self.assertRaises(sqlite3.IntegrityError):
            memory.supersede(self.db, old, self.item())
        self.assertEqual(self.db.execute("SELECT count(*) FROM items").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT status FROM items").fetchone()[0], "open")

    def test_supersession_cannot_cycle_or_rewrite_history(self):
        old = self.add()
        new = memory.supersede(self.db, old, self.item())
        for sql, params in [
            ("UPDATE items SET status='superseded',superseded_by=? WHERE id=?", (old, new)),
            ("UPDATE items SET status='open',superseded_by=NULL WHERE id=?", (old,)),
            ("UPDATE items SET status='superseded',superseded_by=? WHERE id=?", (new, new)),
            ("UPDATE items SET status='superseded',superseded_by=999 WHERE id=?", (new,)),
        ]:
            with self.assertRaises(sqlite3.IntegrityError), self.db:
                self.db.execute(sql, params)

    def test_links_reject_duplicates_and_dangling_references(self):
        a, b = self.add(), self.add()
        with self.db:
            self.db.execute("INSERT INTO links VALUES (?,?,'related_to')", (a, b))
        for pair in [(a, b), (a, 999), (a, a)]:
            with self.assertRaises(sqlite3.IntegrityError), self.db:
                self.db.execute("INSERT INTO links VALUES (?,?,'related_to')", pair)

    def test_graph_handles_incoming_edges_cycles_and_history(self):
        self.demo()
        with self.db:
            self.db.execute("INSERT INTO links VALUES (2,4,'related_to')")
        self.assertEqual({r["id"] for r in self.query("connected", item_id=1)}, {2, 3, 4})
        new = memory.supersede(self.db, 2, self.item(kind="person", title="Updated person"), True)
        self.assertEqual({r["id"] for r in self.query("connected", item_id=1)}, {new, 3, 4})
        self.assertEqual([r["direction"] for r in self.query("people", item_id=4)], ["incoming"])

    def test_prepare_is_conservative_and_does_not_change_source(self):
        source = self.root / "notes.md"
        content = "# Notes\n- debt: Example due 2026-11-20 $30\n- [x] Done thing\n- person: Example person\n- Prose stays here\n- fact: password = secret\n```\n- question: Code block\n```\n"
        source.write_text(content)
        rows, skipped = memory.prepare_import([source, source])
        self.assertEqual(len(rows), 3)
        self.assertEqual(skipped, 1)
        self.assertFalse(any(r["approved"] for r in rows))
        self.assertEqual(rows[0]["item"]["due_date"], "2026-11-20")
        self.assertIsNone(rows[0]["item"]["amount"])
        self.assertEqual(rows[1]["item"]["status"], "done")
        self.assertEqual(source.read_text(), content)

    def records(self):
        return memory.read_import(memory.ROOT / "examples/reviewed.jsonl")

    def test_import_preview_approval_and_idempotency(self):
        records = self.records()
        records.append((False, self.item()))
        result = memory.import_records(self.db, records)
        self.assertEqual(result, dict(inserted=1, existing=0, unapproved=1))
        self.assertEqual(self.db.execute("SELECT count(*) FROM items").fetchone()[0], 0)
        memory.import_records(self.db, records, apply=True)
        result = memory.import_records(self.db, records, apply=True)
        self.assertEqual(result, dict(inserted=0, existing=1, unapproved=1))

    def test_import_retry_does_not_resurrect_superseded_item(self):
        records = self.records()
        memory.import_records(self.db, records, True)
        memory.supersede(self.db, 1, self.item())
        self.assertEqual(memory.import_records(self.db, records, True)["existing"], 1)
        self.assertEqual(self.db.execute("SELECT status FROM items WHERE id=1").fetchone()[0], "superseded")

    def test_import_conflict_rolls_back_whole_batch(self):
        records = self.records()
        memory.import_records(self.db, records, True)
        changed = dict(records[0][1], title="Conflicting edit")
        with self.assertRaises(ValueError):
            memory.import_records(self.db, [(True, self.item(source="import:new test")), (True, changed)], True)
        self.assertEqual(self.db.execute("SELECT count(*) FROM items").fetchone()[0], 1)

    def test_import_duplicate_in_batch(self):
        records = self.records() * 2
        self.assertEqual(memory.import_records(self.db, records)["existing"], 1)
        self.assertEqual(memory.import_records(self.db, records, True)["existing"], 1)

    def test_export_stable_notes_history_and_links(self):
        self.demo()
        folder = self.root / "vault" / "Queryable Memory"
        self.assertEqual(memory.export_obsidian(self.db, folder), 9)
        self.assertIn("[[item-2]]", (folder / "item-1.md").read_text())
        self.assertIn("SUPERSEDED", (folder / "item-9.md").read_text())
        self.assertIn("[[item-3]]", (folder / "item-9.md").read_text())
        (folder / "item-1.md").write_text("Local edit")
        memory.export_obsidian(self.db, folder)
        self.assertIn("Radar dispute", (folder / "item-1.md").read_text())
        self.assertEqual(len(list(folder.glob("*.md"))), 9)

    def test_export_refuses_existing_vault_and_other_database(self):
        folder = self.root / "vault"
        folder.mkdir()
        (folder / "personal.md").write_text("Keep this")
        with self.assertRaises(ValueError):
            memory.export_obsidian(self.db, folder)
        generated = self.root / "generated"
        memory.export_obsidian(self.db, generated)
        (generated / ".queryable-memory-export").write_text("/another/database.db")
        with self.assertRaises(ValueError):
            memory.export_obsidian(self.db, generated)

    def test_backup_restores_and_never_overwrites(self):
        self.demo()
        path = self.root / "backup.db"
        memory.backup(self.db, path)
        with contextlib.closing(memory.connect(path)) as restored:
            self.assertEqual(restored.execute("SELECT count(*) FROM items").fetchone()[0], 9)
            self.assertEqual(restored.execute("PRAGMA foreign_key_check").fetchall(), [])
        with self.assertRaises(FileExistsError):
            memory.backup(self.db, path)
        with self.assertRaises(FileExistsError):
            memory.backup(self.db, self.path)

    def test_cli_end_to_end(self):
        def run(*args):
            result = subprocess.run([sys.executable, str(memory.ROOT / "memory.py"), "--db", str(self.path), *args], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        run("init")
        self.assertIn('"mode": "preview"', run("import", str(memory.ROOT / "examples/reviewed.jsonl")))
        run("import", str(memory.ROOT / "examples/reviewed.jsonl"), "--apply")
        new = run("supersede", "1", str(memory.ROOT / "examples/replacement.json"))
        self.assertEqual(new.strip(), "2")
        run("export", str(self.root / "export"))
        run("backup", str(self.root / "snapshot.db"))

    @unittest.skipUnless(shutil.which("sqlite3"), "SQLite shell is not installed")
    def test_raw_sqlite_shell_bootstrap_and_parameterized_queries(self):
        raw_path = self.root / "raw.db"
        bootstrap = subprocess.run(
            ["sqlite3", "-bail", str(raw_path)],
            input=(memory.ROOT / "schema.sql").read_text() + (memory.ROOT / "examples/demo.sql").read_text(),
            text=True, capture_output=True,
        )
        self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
        for name, parameter, expected in [
            ("due", '.parameter set :through "\'2026-11-20\'"', [3, 5]),
            ("questions", "", [4]),
            ("people", ".parameter set :item_id 1", [2]),
        ]:
            result = subprocess.run(
                ["sqlite3", "-bail", "-json", str(raw_path)], cwd=memory.ROOT,
                input=f".parameter init\n{parameter}\n.read queries/{name}.sql\n",
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual([r["id"] for r in json.loads(result.stdout)], expected)


if __name__ == "__main__":
    unittest.main()
