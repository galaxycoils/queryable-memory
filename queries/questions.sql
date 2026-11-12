-- v1 convention: every open question is awaiting Darius.
SELECT id, title, detail, created_at, confidence, source
FROM items
WHERE kind = 'question' AND status = 'open'
ORDER BY created_at, id;
