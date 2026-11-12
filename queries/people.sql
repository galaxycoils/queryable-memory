-- Bind :item_id to a current dispute/goal/etc. ID. Both edge directions.
SELECT p.id, p.title, l.relation,
       CASE WHEN l.from_id = root.id THEN 'outgoing' ELSE 'incoming' END AS direction
FROM items root
JOIN links l ON l.from_id = root.id OR l.to_id = root.id
JOIN items p ON p.id = CASE WHEN l.from_id = root.id THEN l.to_id ELSE l.from_id END
WHERE root.id = :item_id AND root.status != 'superseded'
  AND p.kind = 'person' AND p.status != 'superseded'
ORDER BY p.title, p.id, l.relation;
