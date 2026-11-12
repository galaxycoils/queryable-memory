-- SYNTHETIC DATA ONLY. Run against a separate, empty demo database.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;
INSERT INTO items (id, kind, title, detail, due_date, amount, confidence, source) VALUES
    (1, 'goal', 'Radar dispute', 'Synthetic dispute used to demonstrate graph queries.', NULL, NULL, 'confirmed', 'demo'),
    (2, 'person', 'Example person', 'Synthetic person, not a real contact.', NULL, NULL, 'confirmed', 'demo'),
    (3, 'commitment', 'Example payment', 'Synthetic payment due before the cutoff.', '2026-11-19', 30, 'reported', 'demo'),
    (4, 'question', 'Example unanswered question', 'Which synthetic payment date should we use?', NULL, NULL, 'reported', 'demo'),
    (5, 'commitment', 'Example boundary payment', 'Included by on or before November 20.', '2026-11-20', 15, 'estimate', 'demo'),
    (6, 'commitment', 'Example later payment', 'Excluded by the November 20 cutoff.', '2026-11-21', 25, 'reported', 'demo'),
    (7, 'commitment', 'Example unknown date', 'Unknown due date is NULL, never guessed.', NULL, 5, 'estimate', 'demo'),
    (8, 'commitment', 'Example completed payment', 'Already completed.', '2026-11-18', 10, 'confirmed', 'demo'),
    (9, 'fact', 'Example old estimate', 'Historical estimate, replaced by item 3.', NULL, 40, 'estimate', 'demo');
UPDATE items SET status = 'done', updated_at = date('now') WHERE id = 8;
UPDATE items SET status = 'superseded', superseded_by = 3, updated_at = date('now') WHERE id = 9;
INSERT INTO links VALUES
    (1, 2, 'involved_in'),
    (3, 2, 'owes_to'),
    (4, 1, 'asked_about'),
    (3, 1, 'part_of');
COMMIT;
