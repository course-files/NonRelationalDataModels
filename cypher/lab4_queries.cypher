// =====================================================================
// lab4_queries.cypher -- graph queries for the Pesa fraud graph
//
// How to run: open http://localhost:7474 (Neo4j Browser), log in as
//   user  : neo4j
//   password : pesa-lab-password
// then paste ONE query at a time into the editor and press Ctrl+Enter.
// (Or run them from the shell:
//   docker compose exec neo4j cypher-shell -u neo4j -p pesa-lab-password -f /cypher/lab4_queries.cypher )
//
// Each query is separated by a semicolon. Lines starting with // are comments.
// Graph model:
//   (:Customer)-[:OWNS]->(:Account)-[:USED]->(:Device)
//   (:Account)-[:SENT   {txn_id, amount, ts, channel}]->(:Account)
//   (:Account)-[:PAID   {txn_id, amount, ts, channel}]->(:Merchant)
// =====================================================================

// ---------------------------------------------------------------------
// 0. Orientation: what is in the graph?
// Expected nodes: Account 400, Device 402, Customer 320, Merchant 40  (1,162 in total)
// Expected edges: PAID 8,415, USED 434, SENT 3,186, OWNS 400         (12,435 in total)
// ---------------------------------------------------------------------
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS nodes ORDER BY nodes DESC;

MATCH ()-[r]->() RETURN type(r) AS relationship, count(*) AS edges ORDER BY edges DESC;

// ---------------------------------------------------------------------
// 1. Devices shared by 3 or more accounts.   Expected: D401 (5), D033 (3), D183 (3)
// Pattern reading: an Account that USED a Device, and another Account that USED the same Device.
// ---------------------------------------------------------------------
MATCH (d:Device)<-[:USED]-(a:Account)
WITH d, collect(a.id) AS accounts
WHERE size(accounts) >= 3
RETURN d.id AS device, size(accounts) AS n_accounts, accounts
ORDER BY n_accounts DESC, device;

// ---------------------------------------------------------------------
// 2. Who shares a device with A0316?  (one hop through a Device node)
// A device is shared by a family (D010 has two accounts of one household) as
// well as by a fraud ring. The device alone does not tell you which.
// ---------------------------------------------------------------------
MATCH (a:Account {id: 'A0316'})-[:USED]->(d:Device)<-[:USED]-(other:Account)
RETURN d.id AS device, collect(DISTINCT other.id) AS also_used_by;

// 2b. The same device, drawn as a graph. Use Neo4j Browser: the "Graph" view button appears on the result frame.
MATCH (a:Account)-[u:USED]->(d:Device {id: 'D401'}) RETURN a, u, d;

// ---------------------------------------------------------------------
// 3. Distinct accounts reachable from A0001 within 1..5 payments.
// Compare with the SQL recursive CTE.  Expected: 9, 31, 111, 275, 380
// NOTE: the upper bound of a variable-length pattern is part of the query text,
// it cannot be a $parameter. That is why there are five similar statements here.
// ---------------------------------------------------------------------
MATCH (a:Account {id: 'A0001'})-[:SENT*1..1]->(b:Account) WHERE b <> a RETURN 1 AS max_hops, count(DISTINCT b) AS reached;
MATCH (a:Account {id: 'A0001'})-[:SENT*1..2]->(b:Account) WHERE b <> a RETURN 2 AS max_hops, count(DISTINCT b) AS reached;
MATCH (a:Account {id: 'A0001'})-[:SENT*1..3]->(b:Account) WHERE b <> a RETURN 3 AS max_hops, count(DISTINCT b) AS reached;
MATCH (a:Account {id: 'A0001'})-[:SENT*1..4]->(b:Account) WHERE b <> a RETURN 4 AS max_hops, count(DISTINCT b) AS reached;
MATCH (a:Account {id: 'A0001'})-[:SENT*1..5]->(b:Account) WHERE b <> a RETURN 5 AS max_hops, count(DISTINCT b) AS reached;

// ---------------------------------------------------------------------
// 4. Count TRAILS from the busiest account, A0007 (every path that never reuses a payment).
// Expected: 481, 3284, 16962, 114334 for lengths 1..4.
// Run the *1..4 version first. Try *1..5 only if you are curious (742,440 trails at length 5).
// The point: the number of PATHS explodes long before the number of distinct
// ACCOUNTS (6, 33, 112, 276, 379) grows. Asking for distinct endpoints is the cure.
// ---------------------------------------------------------------------
MATCH p = (a:Account {id: 'A0007'})-[:SENT*1..4]->(b:Account)
RETURN length(p) AS hops, count(*) AS trails
ORDER BY hops;

// ---------------------------------------------------------------------
// 5. The ring: 3 to 5 large transfers that return to their starting account.
// Compare with the 15-line recursive CTE in sql/lab4_graph_in_sql.sql (Q4).
// Expected: exactly one row, [A0316, A0317, A0318, A0319, A0316], 4 hops.
//
//  ALL(r IN relationships(p) WHERE r.amount >= 40000)  -> prune: only big payments
//  ALL(n IN nodes(p) WHERE n.id >= a.id)               -> report each ring once (from its smallest id)
// ---------------------------------------------------------------------
MATCH p = (a:Account)-[:SENT*3..5]->(a)
WHERE ALL(r IN relationships(p) WHERE r.amount >= 40000)
  AND ALL(n IN nodes(p) WHERE n.id >= a.id)
RETURN [n IN nodes(p) | n.id] AS ring, length(p) AS hops;

// 5b. The same ring, returned as a PATH so that Neo4j Browser can draw it
MATCH p = (a:Account)-[:SENT*3..5]->(a)
WHERE ALL(r IN relationships(p) WHERE r.amount >= 40000)
  AND ALL(n IN nodes(p) WHERE n.id >= a.id)
RETURN p;

// ---------------------------------------------------------------------
// 6. Combine the two signals. The ring members are linked by MONEY. Which OTHER
// accounts are linked to a ring member by a shared DEVICE?
// Expected: one row -- A0320 via device D401. A0320 never received money from
// the ring, but it used the same phone and cashed out KES 46,000 to merchant M039.
// A money-only query cannot see A0320, and a device-only query also flags innocent
// households. The graph lets you ask for the intersection.
// ---------------------------------------------------------------------
MATCH p = (a:Account)-[:SENT*3..5]->(a)
WHERE ALL(r IN relationships(p) WHERE r.amount >= 40000)
  AND ALL(n IN nodes(p) WHERE n.id >= a.id)
UNWIND nodes(p) AS member
WITH collect(DISTINCT member) AS ring
UNWIND ring AS m
MATCH (m)-[:USED]->(d:Device)<-[:USED]-(suspect:Account)
WHERE NOT suspect IN ring
RETURN DISTINCT suspect.id AS suspect, d.id AS shared_device
ORDER BY suspect;

// ---------------------------------------------------------------------
// 7. Where did the money go? Large payments from the suspect account to merchants.
// Expected: A0320 -> M039, KES 46,000, 2026-09-14T09:20:00Z
// ---------------------------------------------------------------------
MATCH (s:Account {id: 'A0320'})-[r:PAID]->(m:Merchant)
WHERE r.amount >= 40000
RETURN s.id AS account, m.id AS merchant, m.name AS merchant_name, r.amount AS amount, toString(r.ts) AS at;

// ---------------------------------------------------------------------
// 8. A cycle on its own is NOT evidence of fraud.
// Remove the amount filter and look for loops of length exactly 2.
// Expected: 43 trails over 17 different pairs of accounts (A0020 <-> A0021 is one
// of them: two payments of KES 1,200 within 25 minutes -- two friends settling a bill).
// ---------------------------------------------------------------------
MATCH p = (a:Account)-[:SENT*2..2]->(a)
WHERE ALL(n IN nodes(p) WHERE n.id >= a.id)
RETURN count(*) AS two_hop_loops, count(DISTINCT [n IN nodes(p) | n.id]) AS distinct_account_pairs;

// ---------------------------------------------------------------------
// 9. EXPLAIN / PROFILE. Prefix any query with PROFILE to see the plan and the
// number of "db hits" (units of storage work). Try it on query 5, then run it again
// after removing the ALL(r IN relationships ...) line and compare db hits.
// ---------------------------------------------------------------------
PROFILE
MATCH p = (a:Account)-[:SENT*3..5]->(a)
WHERE ALL(r IN relationships(p) WHERE r.amount >= 40000)
  AND ALL(n IN nodes(p) WHERE n.id >= a.id)
RETURN [n IN nodes(p) | n.id] AS ring, length(p) AS hops;
