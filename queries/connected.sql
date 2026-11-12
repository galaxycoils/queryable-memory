-- Optional multi-hop traversal, both directions, excluding historical nodes.
-- UNION (not UNION ALL) makes cycles terminate. Done items are still current.
WITH RECURSIVE connected(id) AS (
    SELECT id FROM items WHERE id = :item_id AND status != 'superseded'
    UNION
    SELECT i.id FROM connected c
    JOIN links l ON l.from_id = c.id OR l.to_id = c.id
    JOIN items i ON i.id = CASE WHEN l.from_id = c.id THEN l.to_id ELSE l.from_id END
    WHERE i.status != 'superseded'
)
SELECT i.* FROM items i JOIN connected c ON i.id = c.id
WHERE i.id != :item_id ORDER BY i.kind, i.title, i.id;
