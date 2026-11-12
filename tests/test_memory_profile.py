import contextlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import memory


class MemoryProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "MEMORY.md"

    def tearDown(self):
        self.tmp.cleanup()

    def parse(self, text):
        self.path.write_text(text, encoding="utf-8")
        rows, skipped = memory.prepare_import([self.path], profile="memory-md")
        for row in rows:
            self.assertIs(row["approved"], False)
            self.assertEqual(row["item"]["confidence"], "reported")
            memory.normalize(row["item"])
        self.assertEqual(self.path.read_text(), text)
        return rows, skipped

    def items(self, text):
        return [r["item"] for r in self.parse(text)[0]]

    def test_representative_memory_format(self):
        rows, skipped = self.parse((memory.ROOT / "examples/memory-profile.md").read_text())
        self.assertEqual(len(rows), 11)
        self.assertEqual(skipped, 0)
        items = {r["item"]["title"]: r["item"] for r in rows}
        installment = items["Example installment"]
        self.assertEqual((installment["kind"], installment["status"], installment["amount"], installment["due_date"]),
                         ("commitment", "open", 276.07, "2026-11-19"))
        self.assertEqual(items["Example completed bill"]["status"], "done")
        self.assertEqual(items["Example disputed balance"]["status"], "open")
        self.assertIsNone(items["Example disputed balance"]["amount"])
        self.assertIn("CONFLICT marker", items["Example disputed balance"]["detail"])
        self.assertEqual(items["Example dated entry"]["due_date"], "2026-10-30")
        self.assertIn("not a note date", items["Example dated entry"]["detail"])
        self.assertEqual(items["Example repayment"]["amount"], 1200)
        self.assertEqual(items["Example repayment"]["due_date"], "2026-12-02")
        self.assertEqual(items["Example preference"]["kind"], "fact")
        self.assertEqual(items["Example person"]["kind"], "person")
        self.assertEqual(items["Example open decision"]["kind"], "question")
        self.assertEqual(items["Example choice"]["kind"], "question")
        self.assertEqual(items["Example old question"]["status"], "done")
        self.assertEqual(items["Example pending reply"]["kind"], "question")

    def test_section_scope_and_sibling_reset(self):
        items = self.items("# Memory\n## **Facts**\n- One\n### Subsection\n- Two\n"
                           "## Other\n- Skip\n### Subsection\n- Skip too\n"
                           "## People Index:\n- Three\n### Goals\n- Four\n"
                           "### Other\n- Five\n# Journal\n- Skip again\n")
        self.assertEqual([(i["title"], i["kind"]) for i in items],
                         [("One", "fact"), ("Two", "fact"), ("Three", "person"),
                          ("Four", "goal"), ("Five", "person")])

    def test_question_phrases_override_section_but_not_explicit_status(self):
        items = self.items("## Commitments\n- Still open: choose a time.\n"
                           "- Awaiting HIS answer.\n- Unanswered.\n- CLOSED — previously unanswered.\n"
                           "## Other\n- The shop is open.\n- Reopened yesterday.\n")
        self.assertEqual([i["kind"] for i in items], ["question"] * 4)
        self.assertEqual([i["status"] for i in items], ["open", "open", "open", "done"])

    def test_markers_and_checkboxes(self):
        lines = ["OPEN", "RESOLVED", "CLOSED", "CONFLICT", "OPEN then CLOSED", "closed in prose",
                 "[x] completed", "[x] OPEN", "[ ] RESOLVED", "CLOSED with CONFLICT"]
        items = self.items("## Facts\n" + "\n".join("- " + line for line in lines))
        self.assertEqual([i["status"] for i in items],
                         ["open", "done", "done", "open", "open", "open", "done", "open", "done", "open"])
        self.assertIn("Contradictory status", items[4]["detail"])
        self.assertIn("CONFLICT", items[-1]["detail"])

    def test_bold_labels_and_original_detail_preserved(self):
        content = "**Example vendor:** OPEN — $276.07 due Nov 19, 2026."
        items = self.items("## Commitments\n- " + content + "\n- **OPEN** — **Other label**: $5\n")
        self.assertEqual(items[0]["title"], "Example vendor")
        self.assertEqual(items[0]["detail"], content)
        self.assertEqual(items[1]["title"], "Other label")
        self.assertTrue(items[0]["source"].endswith("MEMORY.md:2"))

    def test_explicit_dates_and_parenthesized_fallback(self):
        cases = {
            "due Nov 19, 2026": "2026-11-19",
            "due November 19 2026": "2026-11-19",
            "due: Sept. 2, 2026": "2026-09-02",
            "DUE on **2028-02-29**": "2028-02-29",
            "(2026-10-30)": "2026-10-30",
            "(2026-10-30), due Nov 19, 2026": "2026-11-19",
            "due 2026-11-19, repeated due Nov 19, 2026": "2026-11-19",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.items("## Commitments\n- " + text)[0]["due_date"], expected)

    def test_invalid_missing_year_and_ambiguous_dates_stay_unset(self):
        for text in ["due Feb 29, 2026", "due 2026-13-01", "(2026-02-30)", "due Nov 19",
                     "due tomorrow (2026-10-30)", "due 2026-11-19 and due 2026-11-20",
                     "(2026-10-30) or (2026-10-31)", "due Nov 19, 2026 and due Nov 20"]:
            with self.subTest(text=text):
                item = self.items("## Commitments\n- " + text)[0]
                self.assertIsNone(item["due_date"])
                self.assertIn("Import review", item["detail"])

    def test_dates_without_due_label_or_parentheses_are_not_inferred(self):
        for text in ["Discussed Nov 19, 2026", "Created 2026-10-30", "Tomorrow", "11/19/26"]:
            with self.subTest(text=text):
                self.assertIsNone(self.items("## Facts\n- " + text)[0]["due_date"])

    def test_amounts_include_grouping_cents_and_explicit_negative(self):
        for text, expected in [("$276.07", 276.07), ("$1,200.50, pending", 1200.50),
                               ("$0", 0), ("-$30", -30), ("$-30", -30),
                               ("$30, reported again as $30.00", 30)]:
            with self.subTest(text=text):
                self.assertEqual(self.items("## Commitments\n- " + text)[0]["amount"], expected)

    def test_ambiguous_malformed_or_ranged_amounts_stay_unset(self):
        for text in ["$40 or $55", "$1,23", "$30k", "$1.234", "$30–40", "$30-$40",
                     "$10 plus $unknown", "-$-10"]:
            with self.subTest(text=text):
                item = self.items("## Commitments\n- " + text)[0]
                self.assertIsNone(item["amount"])
                self.assertIn("Import review", item["detail"])

    def test_fences_are_skipped_without_changing_section_scope(self):
        items = self.items("## Facts\n````markdown\n## Commitments\n- Hidden\n```\n"
                           "- Still hidden\n````\n- Visible\n~~~\n- Hidden too\n~~~\n")
        self.assertEqual([(i["title"], i["kind"]) for i in items], [("Visible", "fact")])

    def test_continuations_nested_bullets_and_sensitive_lines(self):
        rows, skipped = self.parse("## Commitments\n- **Safe** — $30\n  due Nov 19, 2026\n"
                                   "  - **Separate** — $20\n- **Sensitive**\n  password: example\n")
        self.assertEqual(skipped, 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["item"]["due_date"], "2026-11-19")
        self.assertEqual(rows[1]["item"]["amount"], 20)
        self.assertTrue(rows[1]["item"]["source"].endswith(":4"))

    def test_file_context_does_not_leak_and_duplicate_paths_are_ignored(self):
        self.path.write_text("## Facts\n- Example\n")
        other = self.root / "other.md"
        other.write_text("- Unclassified prose\n")
        rows, skipped = memory.prepare_import([self.path, self.path, other], profile="memory-md")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows, memory.prepare_import([self.path], profile="memory-md")[0])

    def test_tagged_default_remains_unchanged_and_profile_supports_tags(self):
        self.path.write_text("## Facts\n- Prose\n- debt: Example $30 due 2026-11-19\n")
        old, _ = memory.prepare_import([self.path])
        new, _ = memory.prepare_import([self.path], profile="memory-md")
        self.assertEqual(len(old), 1)
        self.assertIsNone(old[0]["item"]["amount"])
        self.assertEqual(len(new), 2)
        self.assertEqual(new[1]["item"]["kind"], "commitment")
        self.assertEqual(new[1]["item"]["amount"], 30)
        with self.assertRaises(ValueError):
            memory.prepare_import([self.path], profile="unknown")

    def test_cli_review_apply_and_retry(self):
        self.path.write_text("## Commitments\n- **Example** — OPEN — $276.07 due Nov 19, 2026\n")
        db_path = self.root / "memory.db"
        result = subprocess.run(
            [sys.executable, str(memory.ROOT / "memory.py"), "--db", str(db_path),
             "prepare-import", "--profile", "memory-md", str(self.path)],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(db_path.exists())
        row = json.loads(result.stdout)
        self.assertIs(row["approved"], False)
        preview = self.root / "review.jsonl"
        preview.write_text(result.stdout)
        memory.initialize(db_path)
        with contextlib.closing(memory.connect(db_path)) as db:
            self.assertEqual(memory.import_records(db, memory.read_import(preview), apply=True)["inserted"], 0)
            row["approved"] = True
            preview.write_text(json.dumps(row) + "\n")
            records = memory.read_import(preview)
            self.assertEqual(memory.import_records(db, records)["inserted"], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM items").fetchone()[0], 0)
            self.assertEqual(memory.import_records(db, records, apply=True)["inserted"], 1)
            self.assertEqual(memory.import_records(db, records, apply=True)["existing"], 1)
            due = db.execute((memory.ROOT / "queries/due.sql").read_text(), {"through": "2026-11-20"}).fetchone()
            self.assertEqual((due["title"], due["amount"], due["due_date"]), ("Example", 276.07, "2026-11-19"))


if __name__ == "__main__":
    unittest.main()
