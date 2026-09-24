-- Normalize dictionary item ordering to a 1-based, per-dictionary unique sequence.
-- Uniqueness is scoped by type_id so each dictionary's ordering is isolated.

UPDATE dictionary_items di
JOIN (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY type_id ORDER BY sort_order, id) AS rn
    FROM dictionary_items
) ranked ON ranked.id = di.id
SET di.sort_order = ranked.rn;
