-- Schema v1. Exactly two tables; no server or extension required.
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('fact', 'commitment', 'question', 'person', 'goal')),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    detail TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'superseded')),
    due_date TEXT CHECK (due_date IS NULL OR (
        due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
        AND date(due_date, '+0 days') IS NOT NULL
        AND date(due_date, '+0 days') = due_date)),
    -- Major currency units; one currency per database. Not an accounting ledger.
    amount NUMERIC CHECK (amount IS NULL OR typeof(amount) IN ('integer', 'real')),
    confidence TEXT NOT NULL DEFAULT 'reported'
        CHECK (confidence IN ('confirmed', 'reported', 'estimate')),
    -- Short source label or a provenance string. import: is reserved for the importer.
    source TEXT NOT NULL CHECK (length(trim(source)) > 0),
    superseded_by INTEGER REFERENCES items(id),
    created_at TEXT NOT NULL DEFAULT (date('now')) CHECK (
        created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
        AND date(created_at, '+0 days') IS NOT NULL
        AND date(created_at, '+0 days') = created_at),
    updated_at TEXT NOT NULL DEFAULT (date('now')) CHECK (
        updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
        AND date(updated_at, '+0 days') IS NOT NULL
        AND date(updated_at, '+0 days') = updated_at
        AND updated_at >= created_at),
    CHECK ((status = 'superseded' AND superseded_by IS NOT NULL)
        OR (status != 'superseded' AND superseded_by IS NULL)),
    CHECK (superseded_by IS NULL OR superseded_by != id)
);

CREATE TABLE IF NOT EXISTS links (
    from_id INTEGER NOT NULL REFERENCES items(id),
    to_id INTEGER NOT NULL REFERENCES items(id),
    relation TEXT NOT NULL CHECK (length(trim(relation)) > 0),
    PRIMARY KEY (from_id, to_id, relation),
    CHECK (from_id != to_id)
);

CREATE INDEX IF NOT EXISTS items_open_due ON items(due_date)
    WHERE kind = 'commitment' AND status = 'open';
CREATE INDEX IF NOT EXISTS items_kind_status ON items(kind, status);
CREATE INDEX IF NOT EXISTS links_to ON links(to_id);
CREATE UNIQUE INDEX IF NOT EXISTS items_import_source ON items(source)
    WHERE source LIKE 'import:%';

CREATE TRIGGER IF NOT EXISTS items_no_delete BEFORE DELETE ON items
BEGIN
    SELECT RAISE(ABORT, 'Memory items cannot be deleted; supersede them');
END;

-- Block INSERT OR REPLACE from silently destroying an existing item's history,
-- even on connections that do not enable recursive_triggers.
CREATE TRIGGER IF NOT EXISTS items_no_replace BEFORE INSERT ON items
WHEN EXISTS (SELECT 1 FROM items WHERE id = NEW.id)
    OR (NEW.source LIKE 'import:%' AND EXISTS (SELECT 1 FROM items WHERE source = NEW.source))
BEGIN
    SELECT RAISE(ABORT, 'Existing memory cannot be replaced; supersede it');
END;

CREATE TRIGGER IF NOT EXISTS items_content_immutable BEFORE UPDATE ON items
WHEN NEW.id IS NOT OLD.id OR NEW.kind IS NOT OLD.kind OR NEW.title IS NOT OLD.title
    OR NEW.detail IS NOT OLD.detail OR NEW.due_date IS NOT OLD.due_date
    OR NEW.amount IS NOT OLD.amount OR NEW.confidence IS NOT OLD.confidence
    OR NEW.source IS NOT OLD.source OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'Fact content is immutable; insert a replacement and supersede');
END;

CREATE TRIGGER IF NOT EXISTS items_history_immutable BEFORE UPDATE ON items
WHEN OLD.status = 'superseded'
BEGIN
    SELECT RAISE(ABORT, 'Superseded history is immutable');
END;

CREATE TRIGGER IF NOT EXISTS items_replacement_current BEFORE UPDATE OF superseded_by ON items
WHEN NEW.superseded_by IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM items WHERE id = NEW.superseded_by AND status != 'superseded')
BEGIN
    SELECT RAISE(ABORT, 'Replacement must exist and be current');
END;

-- History is created by UPDATE only, after the replacement exists.
CREATE TRIGGER IF NOT EXISTS items_insert_current BEFORE INSERT ON items
WHEN NEW.status = 'superseded'
BEGIN
    SELECT RAISE(ABORT, 'Insert a current item, then supersede it in a transaction');
END;

CREATE TRIGGER IF NOT EXISTS items_touch AFTER UPDATE OF status ON items
WHEN NEW.updated_at = OLD.updated_at AND NEW.updated_at < date('now')
    AND NEW.status != 'superseded'
BEGIN
    UPDATE items SET updated_at = date('now') WHERE id = NEW.id;
END;

PRAGMA user_version = 1;
COMMIT;
