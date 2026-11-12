# Design notes

The database implements the supplied build spec: `items` and `links`, kept beside
existing Markdown memory. Direct SQLite access is the primary interface. Python
is a dependency-free maintenance tool, not an application service or query layer.

## History invariants

Item identity and fact content are immutable after insertion. `open` and `done`
are lifecycle states of a current fact; `superseded` means a different row replaced
its content. A superseded row must reference an existing current row when it is
retired. That replacement can itself be superseded later, giving a forward chain.

A replacement cannot point to itself or to an already historical row. Historical
rows cannot be updated or deleted. These rules make a replacement cycle impossible
under ordinary writes. `INSERT OR REPLACE` is explicitly rejected for existing
IDs/import sources; SQLite otherwise deletes the conflicting row internally.

Use `updated_at = date('now')` on lifecycle changes, including raw supersession.
The convenience touch trigger fills the current UTC date for ordinary status
changes where appropriate; callers must still set it explicitly when retiring a
row. Calendar dates match the spec; there is no claim of event ordering within a day.

The supersession helper takes an immediate write lock, inserts the replacement,
retires the old fact, and optionally copies links, then commits once. A failure at
any stage rolls back all steps. Old links stay attached to old facts, so historical
relationships remain browsable. Current queries exclude historical endpoints.
Link carry-forward is opt-in because a changed fact can invalidate a relationship.

## SQL connections and concurrency

Foreign-key enforcement is per connection in SQLite. Always enable it for raw
SQL; the Python utility does so automatically. The utility waits up to five seconds
for locks. SQLite's default rollback journal is sufficient for this small database;
no WAL configuration or daemon is required. Concurrent writers serialize. A lock
error should be retried after the other transaction completes, not by disabling
constraints. Prefer read-only connections for exploration when practical.

Date checks enforce canonical, valid `YYYY-MM-DD` values. Amounts use the spec's
numeric major units; choose one currency and do not treat floating point sums as
an accounting ledger. There is no automatic conversion or currency inference.

## Import provenance without a third table

The JSONL contract is one object per line: `key`, `approved` (boolean), and `item`.
Item fields match the writable columns in the spec. Initial creation/update dates
record the import date, not a guessed historical date. Preserve original dates in
the detail/source if relevant. New imported rows may be open or done, not superseded.

The source is stored as `import:KEY ORIGINAL_SOURCE`. A partial unique index on
these sources makes an exact retry idempotent. Content conflicts fail atomically;
status differences are ignored on retry so completed or retired records are not
resurrected. No third metadata table is required. This is not semantic deduplication.

The extractor hashes the original absolute path, line number, and line content
into a stable candidate key. A moved or edited source therefore requires review
again. Unapproved rows are never inserted. Preview uses a read-only connection;
apply uses one immediate transaction for the entire approved batch.

## Export and backup

Export reads one consistent database snapshot. It uses ID-based note names and
JSON-quoted YAML scalars in frontmatter to preserve arbitrary punctuation. Files
are replaced atomically, individually; the whole folder is not an atomic snapshot
if export is interrupted. Rerunning export completes it. It never deletes unrelated
files. A marker binds an export folder to an absolute database path; moving the
database requires a fresh output folder (or deliberate marker maintenance).

Backup uses SQLite's online backup API, not a live filesystem copy. It validates
the snapshot and refuses an existing destination. There is no built-in scheduled
upload or retention policy. Backups and exports contain private memory and belong
outside the public repository.

## Scope

This schema versions facts, not every graph mutation. Links intentionally have only
`from_id`, `to_id`, and `relation`; they may be corrected with SQL. Neither titles
nor relation words are globally standardized. Resolve an entity to its ID before
querying. Keep open questions awaiting Darius as the v1 convention; introduce
explicit person links if the real memory needs multiple answerers.

Schema changes require explicit migrations. The initializer verifies an existing
v1 database rather than rerunning schema DDL over it. Do not rerun `schema.sql` on
a newer schema: it is a bootstrap file, not a migration engine. Keep extensions
driven by real questions and retain the existing memory jobs.
