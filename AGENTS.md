# Working on Queryable Memory

Read README.md, MUSE_HANDOFF.md, and docs/design.md before changing behavior.

- Keep SQLite as the source of truth and retain exactly two tables until a real
  query demonstrates a need for more structure.
- Preserve the raw SQL interface, historical facts, and existing Markdown jobs.
- Do not commit real memory, imports, database files, backups, exports, or secrets.
  Test fixtures must be clearly synthetic.
- Keep Python dependencies in the standard library; support Python 3.10+.
- Database changes need an explicit migration and a snapshot/restore test.
- Run `python3 -m unittest discover -s tests -v` and `git diff --check` before
  proposing changes. Validate any changed SQL against a fresh demo database.
