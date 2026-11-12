# Muse handoff

This repository implements the Queryable Memory build spec as a working starter.
The code is public; your real memory and credentials must stay out of the repository.

## What is ready

- `schema.sql`: exactly two tables, indexes, constraints, and history protection.
- `queries/`: due commitments, open questions, direct people connections, recursive
  graph traversal, and supersession history. Plain SQL with bound parameters.
- `memory.py`: initialization, import candidate extraction, reviewed import,
  atomic supersession, consistent backup, and one-way Obsidian export.
- `examples/`: synthetic data only; never load it into the real memory database.
- `tests/` and GitHub Actions: regression checks with no pip dependencies.

## First run on your VM

1. Clone this repository and read the README. Confirm Python 3.10+ and `sqlite3`
   are installed. Run `python3 -m unittest discover -s tests -v`.
2. Run `python3 memory.py init`. The default path is `~/memory/memory.db`.
   Home is the persistent storage boundary; nothing belongs in `/etc`.
3. Locate the real `MEMORY.md` and dated Markdown notes. Do not assume this checkout
   contains them. Do not change the jobs that own `MEMORY.md` or `~/memory/bank/`.
4. Generate an import preview using explicit file paths. Review debt amounts,
   due dates, people, open questions, and goals. The candidate extractor handles
   only explicit bullets; read unrecognized prose yourself and add reviewed rows.
5. Remove secrets and duplicates, split compound facts, and approve accepted rows.
   Run a dry import, then apply. The original Markdown files are never modified.
6. Add graph edges between the imported IDs. Agree on relation direction:
   debt → person (`owes_to`), person → dispute (`involved_in`), question → goal
   (`asked_about`), commitment → goal (`part_of`). Query both directions when exploring.
7. Run the three example questions and compare them against your actual notes.
   Use the correct current year/date for live deadlines. The spec's November 20,
   2026 date is a test example, not an automatically maintained cutoff.
8. Make a snapshot. Set up a backup schedule only in your VM's normal operational
   workflow. If wanted, export into a dedicated Obsidian subfolder.

## Day-to-day contract

- Continue existing Markdown memory writes. Add a row to the database at the same
  point you learn a structured fact. This project does not auto-sync Markdown.
- Use `PRAGMA foreign_keys=ON` and a busy timeout on every SQL connection.
- Store one fact per row. Record uncertainty using `confidence`; unknown values
  are `NULL`, not guesses. Include source location/message reference when useful.
- Current means `status != 'superseded'`. Open work means `status = 'open'`.
- All open questions initially mean “waiting for Darius.” If that changes, add
  an `awaiting_answer_from` link to a person and filter accordingly.
- Changing fact content means a new row and supersession, in one transaction.
  Review relationships before carrying them forward. Use current IDs, not titles.
- Mark completed work `done`, and set `updated_at = date('now')` explicitly.
- Database owners can alter schema/drop triggers: protection enforces normal use,
  not adversarial tamper resistance. Do not disable it to make an update pass.
- Never put passwords, keys, codes, card/account numbers, database snapshots,
  imports, or vault exports in this public Git repository.

## Known limits and next steps

- Real memory has not been imported or validated: it was not available in the
  build environment. The test data is synthetic.
- Import extraction is conservative; there is no general natural-language parser,
  automatic entity resolution, or semantic deduplication. Review before applying.
- Import retries are identified by key plus source. Moving/editing the original
  note can produce a new candidate. Reuse the reviewed import file for retries.
- Relationship corrections can use explicit SQL in a transaction. Links have no
  independent timestamps/status/history in this two-table schema. Do not treat
  this as a fully versioned graph.
- The initial schema is `PRAGMA user_version=1`. `init` will not migrate an existing
  database. Before extending it: take a snapshot, write a transactional migration,
  increment the version, and test with a copy of real memory.
- Add fields only for a demonstrated query. Do not add embeddings, servers,
  background watchers, or another source of truth as a prerequisite to using v1.

The acceptance test is straightforward: your current open debts/questions/goals
are represented accurately, the three queries return the right answers, and a
replaced fact remains visible only as history.
