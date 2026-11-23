-- =====================================================================
-- lab4_graph_in_sql.sql -- the SAME graph questions asked of the relational ledger
--
-- Run each statement separately in psql:
--   docker compose exec postgres psql -U pesa -d pesa
--   pesa=# \timing on
--   pesa=# \i /queries/lab4_graph_in_sql.sql      (runs everything, or paste one query at a time)
--
-- Purpose: you will run the Cypher version of each question in Neo4j and compare
-- (1) how the query reads, (2) how long it takes, (3) what the answer is.
-- Be honest in the comparison: at 12,000 transactions PostgreSQL is fast.
-- The question is how the QUERY GROWS as the question gets more graph-like.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Q1. Which devices are shared by 3 or more accounts?
-- One join-free GROUP BY. A relational database is perfectly good at this:
-- it is a one-hop question.   Expected: D401 (5), D033 (3), D183 (3)
-- ---------------------------------------------------------------------
SELECT device_id, count(*) AS accounts
FROM   account_devices
GROUP  BY device_id
HAVING count(*) >= 3
ORDER  BY accounts DESC, device_id;

-- ---------------------------------------------------------------------
-- Q2. How many DISTINCT accounts can money from A0001 reach in 1, 2, 3, 4, 5 hops?
-- A recursive common table expression (CTE). UNION (not UNION ALL) removes
-- duplicate (account, depth) pairs at every step, which stops the working table
-- from exploding.   Expected: 9, 31, 111, 275, 380
-- ---------------------------------------------------------------------
WITH RECURSIVE reach(acct, depth) AS (
    SELECT 'A0001'::text, 0
  UNION
    SELECT t.to_id, r.depth + 1
    FROM   reach r
    JOIN   transactions t ON t.from_account = r.acct
    WHERE  t.to_kind = 'ACCOUNT' AND t.status = 'SETTLED' AND r.depth < 5
)
SELECT k AS max_hops,
       (SELECT count(DISTINCT acct) FROM reach
         WHERE depth BETWEEN 1 AND k AND acct <> 'A0001') AS distinct_accounts_reached
FROM   generate_series(1, 5) AS k;

-- ---------------------------------------------------------------------
-- Q3. The same traversal WITHOUT de-duplication: count every distinct TRAIL
-- (a path that never reuses the same payment). This is what Cypher's
-- variable-length pattern  (a)-[:SENT*1..4]->(b)  enumerates by default.
-- Start from A0007, the busiest account.
-- Expected rows per depth: 481, 3 284, 16 962, 114 334   (depth 4 takes ~0.5 s here)
-- Change "r.depth < 4" to "r.depth < 5" to reach 742 440 trails at depth 5 (a few seconds).
-- ---------------------------------------------------------------------
WITH RECURSIVE trails(acct, depth, used) AS (
    SELECT 'A0007'::text, 0, ARRAY[]::text[]
  UNION ALL
    SELECT t.to_id, r.depth + 1, r.used || t.txn_id
    FROM   trails r
    JOIN   transactions t ON t.from_account = r.acct
    WHERE  t.to_kind = 'ACCOUNT' AND t.status = 'SETTLED'
      AND  r.depth < 4
      AND  NOT (t.txn_id = ANY (r.used))      -- "never reuse a payment" = trail semantics
)
SELECT depth, count(*) AS trails
FROM   trails
WHERE  depth > 0
GROUP  BY depth
ORDER  BY depth;

-- ---------------------------------------------------------------------
-- Q4. Find a money-circulation ring: 3 to 5 large transfers (>= KES 40,000)
-- that return to the account they started from, each one later than the last.
-- Expected: exactly one ring  {A0316,A0317,A0318,A0319,A0316}, 4 hops.
--
-- Read this query slowly. Every idea that Cypher states in one line --
-- "a path that comes back to its start" -- here needs an array of visited
-- nodes, a start column, a time check, a loop guard and a de-duplication
-- filter so the same ring is not reported once per member.
-- ---------------------------------------------------------------------
WITH RECURSIVE ring(start_acct, acct, depth, path, last_ts) AS (
    SELECT t.from_account, t.to_id, 1, ARRAY[t.from_account, t.to_id], t.ts
    FROM   transactions t
    WHERE  t.to_kind = 'ACCOUNT' AND t.status = 'SETTLED' AND t.amount_kes >= 40000
  UNION ALL
    SELECT r.start_acct, t.to_id, r.depth + 1, r.path || t.to_id, t.ts
    FROM   ring r
    JOIN   transactions t ON t.from_account = r.acct
    WHERE  t.to_kind = 'ACCOUNT' AND t.status = 'SETTLED' AND t.amount_kes >= 40000
      AND  r.depth < 5
      AND  t.ts > r.last_ts                                     -- each hop later than the previous
      AND  (t.to_id = r.start_acct OR NOT t.to_id = ANY (r.path)) -- no revisiting, except to close the ring
      AND  r.acct <> r.start_acct                               -- stop extending once the ring is closed
)
SELECT path, depth AS hops
FROM   ring
WHERE  acct = start_acct AND depth >= 3
  AND  start_acct = (SELECT min(x) FROM unnest(path[1:array_length(path, 1) - 1]) AS x);  -- report each ring once
