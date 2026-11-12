-- Bind :through as YYYY-MM-DD. Inclusive; use < for strictly before.
SELECT id, title, detail, amount, due_date, confidence, source
FROM items
WHERE kind = 'commitment' AND status = 'open' AND due_date <= :through
ORDER BY due_date, id;
