-- Bind :item_id to any historical item to follow its replacement chain.
WITH RECURSIVE history(id) AS (
    SELECT id FROM items WHERE id = :item_id
    UNION
    SELECT i.superseded_by FROM items i JOIN history h ON i.id = h.id
    WHERE i.superseded_by IS NOT NULL
)
SELECT i.* FROM items i JOIN history h ON i.id = h.id ORDER BY i.id;
