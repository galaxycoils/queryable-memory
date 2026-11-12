# Queryable Memory

A small SQLite database beside Muse's existing Markdown memory. Ask questions
with SQL, follow relationships, and keep replaced facts as explicit history.

**Two tables. One database file. No server, API, background process, or Python dependencies.**
The repository contains only code and synthetic examples. Real memory belongs
on the VM at `~/memory/memory.db`, never in this public repository.

## Start on the Muse VM

Requirements: Python 3.10+ (with its standard `sqlite3` module), Git, and the
`sqlite3` command-line program for direct SQL. On Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y git python3 sqlite3
git clone https://github.com/galaxycoils/queryable-memory.git
cd queryable-memory
python3 -m unittest discover -s tests -v
python3 memory.py init
```

`init` creates an **empty** database with mode `0600`. It does not import demo
data, alter `MEMORY.md`, edit `~/memory/bank/`, or change existing memory jobs.
Running it again leaves a valid v1 database unchanged. Nothing installs in `/etc`.

Muse: read **[MUSE_HANDOFF.md](MUSE_HANDOFF.md)** next. It explains what is ready,
how to import local memory, and how to extend this starter safely.

## Use SQL directly

Open the database with foreign keys enabled **on every connection**:

```bash
sqlite3 -bail -header -column \
  -cmd 'PRAGMA foreign_keys=ON;' \
  -cmd '.timeout 5000' ~/memory/memory.db
```

In that session:

```sql
-- Everything still open, due on or before November 20, 2026.
SELECT id, title, detail, amount, due_date, confidence, source
FROM items
WHERE kind = 'commitment' AND status = 'open'
  AND due_date <= '2026-11-20'
ORDER BY due_date, id;

-- All questions awaiting Darius (the v1 convention).
SELECT id, title, detail, created_at FROM items
WHERE kind = 'question' AND status = 'open'
ORDER BY created_at, id;

-- Find the current dispute ID first; titles are intentionally not unique.
SELECT id, title FROM items
WHERE title = 'Radar dispute' AND status != 'superseded';
```

For saved queries, run from the repository directory. These are SQLite shell
commands (dot commands are not SQL):

```sql
.parameter init
.parameter set :through "'2026-11-20'"
.read queries/due.sql
.read queries/questions.sql
.parameter set :item_id 1
.read queries/people.sql
.read queries/connected.sql
.read queries/history.sql
```

Replace `1` with the real item ID. `people.sql` checks both link directions and
returns current people directly connected to that item, including the stored
relation and direction. `connected.sql` traverses any number of hops, safely
handling cycles. Done items remain current; superseded items do not.

Unknown dates are `NULL` and excluded from date comparisons. Use `<` instead of
`<=` for strictly *before* a date. To find undated commitments:

```sql
SELECT id, title, detail FROM items
WHERE kind = 'commitment' AND status = 'open' AND due_date IS NULL;
```

## Write and connect memories

```sql
INSERT INTO items (kind, title, detail, confidence, source)
VALUES ('question', 'Example question', 'Synthetic example only.', 'reported', 'darius')
RETURNING id;

-- Substitute real IDs. Relation direction is meaningful; choose it consistently.
-- Example: a debt --owes_to--> a person.
INSERT INTO links (from_id, to_id, relation) VALUES (3, 2, 'owes_to');

UPDATE items SET status = 'done', updated_at = date('now') WHERE id = 4;
```

Use bound parameters when constructing SQL from input. A source can be a short
label (`darius`, `gmail`, `portal`, `comment`, `search`) or a precise provenance
string. Do not use the reserved `import:` prefix for ordinary writes.

Fact content cannot be edited in place or deleted: insert a replacement and mark
the original superseded. Status can move between `open` and `done`. Superseded
rows are immutable. Schema constraints reject self-replacement, missing or
historical replacements, and replacement cycles.

For an atomic correction, create a JSON file with the new item's fields, following
[examples/replacement.json](examples/replacement.json), then run:

```bash
python3 memory.py supersede OLD_ID /path/to/replacement.json --carry-links
```

Use `--carry-links` **only when the existing relationships still apply**. It copies
incoming and outgoing links to current neighbors while retaining historical links.
Omit it to add the correct new links yourself. The insert, supersession, and optional
copies commit together or roll back together. The command prints the new ID.

Plain SQL works too: within one `BEGIN IMMEDIATE` transaction, insert the new item,
capture its ID, and update the old row's `status`, `superseded_by`, and `updated_at`.
Do not use `INSERT OR REPLACE` to update memory. See [docs/design.md](docs/design.md).

## Import existing Markdown

The importer is deliberately conservative. It extracts explicit `fact:`, `debt:`,
`commitment:`, `question:`, `person:`, and `goal:` bullets, plus Markdown checkboxes.
It does **not** infer arbitrary prose. Every candidate starts unapproved. Muse can
read the remaining notes and add reviewed JSONL rows manually.

```bash
mkdir -p local
chmod 700 local
umask 077
python3 memory.py prepare-import /actual/path/to/MEMORY.md ~/memory/*.md \
  > local/memory.import.jsonl
```

Pass actual existing paths; if no `*.md` files exist, omit that glob. Review the JSONL:

- Verify each kind, title, status, source, and date; fill in amounts and confidence.
- The parser only recognizes explicit `due YYYY-MM-DD` dates and leaves amounts
  unset. It does not resolve ambiguous dates, currencies, or obligations.
- Split compound bullets into separate items with distinct keys. Remove duplicates.
- Never import passwords, keys, codes, card numbers, or account numbers. A basic
  sensitive-line filter helps but is not a guarantee; review all proposed content.
- Change `"approved": false` to `true` only for accepted rows. Preserve keys and source
  locations on retries. Do not commit this file.

Then preview, apply, and verify:

```bash
python3 memory.py import local/memory.import.jsonl
python3 memory.py import local/memory.import.jsonl --apply
```

No `--apply` means no database writes. Applied rows include the import key and
original provenance in `source`; repeat imports skip them, even after completion
or supersession. Reusing a source/key with different fact content fails the whole
batch. This prevents duplicate **retries**, not semantic duplicates across different
files or changed source locations. Add relationships using SQL after importing.

## Try a separate demo

```bash
python3 memory.py --db local/demo.db init
sqlite3 -bail local/demo.db < examples/demo.sql
sqlite3 -bail -header -column local/demo.db <<'SQL'
.parameter init
.parameter set :through "'2026-11-20'"
.read queries/due.sql
.read queries/questions.sql
.parameter set :item_id 1
.read queries/people.sql
SQL
```

Expected: two due commitments (IDs **3, 5**), one question (**4**), and one connected
person (**2**). The fixture includes a completed item, an unknown date, a later
deadline, and a superseded fact. It is not idempotent: load it once into a fresh demo
database. Never load it into real memory.

## Optional Obsidian mirror

```bash
python3 memory.py export '/path/to/vault/Queryable Memory'
```

Use an initially empty, dedicated folder inside the vault. Each row becomes
`item-ID.md` with frontmatter, incoming/outgoing wikilinks, and a conspicuous
replacement link for superseded rows. Repeated exports refresh the same files.
The exporter refuses a nonempty unmarked folder or a folder owned by another
database path. Edits to generated notes are overwritten on the next export;
unrelated files are not deleted. SQLite is always the source of truth.

## Backup and restore

```bash
python3 memory.py backup ~/memory/backups/memory-2026-11-12.db
```

Choose a new filename per snapshot. Backups use SQLite's online backup API and
run `integrity_check`; existing destinations are never overwritten. Copy the
completed snapshot to your chosen private backup destination. No scheduler or
cloud upload is installed by this project.

To restore, pause all database writers, retain the current file as a separate
backup, and use a validated snapshot at a **new path** first:

```bash
sqlite3 -readonly ~/memory/backups/memory-2026-11-12.db \
  'PRAGMA integrity_check; PRAGMA foreign_key_check;'
python3 memory.py --db ~/memory/backups/memory-2026-11-12.db export /tmp/restored-memory-preview
```

`integrity_check` should return `ok`; `foreign_key_check` should return no rows.
Verify the important queries before switching the agent's database path. Avoid
overwriting a live database, particularly one with WAL sidecar files.

## Development

```bash
python3 -m unittest discover -s tests -v
```

The suite covers the three example questions, schema integrity, replacement
history, transaction rollback, graph cycles, import retries, export ownership,
backup restoration, and command-line workflows. GitHub Actions runs it on Python
3.10, 3.12, and 3.14.

Amounts are numeric **major units in one agreed currency per database**. SQLite
NUMERIC can use floating point; this is memory, not exact financial accounting.
Dates are calendar dates, with UTC dates used for creation/update defaults.
No currency or timezone field is added until a real query needs it.

See [docs/design.md](docs/design.md) for invariants and extension boundaries.
