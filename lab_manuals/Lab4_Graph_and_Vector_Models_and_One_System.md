# Lab 4 — Graph and Vector Models, and One System

**Course:** Non-Relational Data Models (Module 4) · **Scenario:** the Pesa Platform
**Time:** about 5 hours in two sittings (Parts A to F: about 2.5 hours; Part G, the capstone: about 2.5 hours)
**Memory needed:** Parts A to F about 2.5 GB (PostgreSQL with pgvector, Neo4j, the workbench); Part G about 6 GB (five data stores together)
**Written work to hand in:** `my_work/Lab4_answers.md` and `my_work/Lab4_design_memo.md` (**assessed**)

---

## 0. What you will learn

1. Model relationships as first-class data in a **property graph**, and write path queries in **Cypher**.
2. Compare a graph query with the equivalent recursive SQL honestly: where the graph model reads better, where PostgreSQL is perfectly adequate, and where each would break as data grows.
3. Explain what an **embedding** is, run similarity search with **pgvector**, and measure the trade-off between speed and **recall** in approximate indexes.
4. Recognise the **filtered vector search** trap.
5. Make **five data stores work as one system**: a ledger that decides, an outbox that remembers, a stream that distributes, idempotent consumers that apply, and a rebuild path that repairs.
6. Show, by breaking it, why **writing to several stores from one request** (dual write) fails, and why the **outbox** pattern does not.

## 1. Conventions

Same as the previous labs. **Q** questions go in `my_work/Lab4_answers.md`; **Predict** means write before you run.

## Part A — Start the stack and build the graph (20 minutes)

```bash
docker compose --profile lab4 up -d --build        # PostgreSQL (with pgvector) and Neo4j; Neo4j needs about a minute
docker compose exec workbench python app/lab4_load_neo4j.py
```

**You should see:** `loaded 1162 nodes and 12435 relationships (3186 SENT, 8415 PAID, 400 OWNS, 434 USED)`.

Open **Neo4j Browser** at <http://localhost:7474>. Connect URL `bolt://localhost:7687`, user `neo4j`, password `pesa-lab-password`.
You will paste queries from `cypher/lab4_queries.cypher` one at a time (select one, press Ctrl+Enter). If you prefer the terminal:

```bash
docker compose exec neo4j cypher-shell -u neo4j -p pesa-lab-password
```

**The model.** Read the docstring at the top of `app/lab4_load_neo4j.py`, then look at it in the Browser:

```
(:Customer)-[:OWNS]->(:Account)-[:USED]->(:Device)
(:Account)-[:SENT {txn_id, amount, ts, channel}]->(:Account)
(:Account)-[:PAID {txn_id, amount, ts, channel}]->(:Merchant)
```

> **Q4.1.** In this model a **Device is a node**, not a property of an account. (a) Which fraud question becomes natural because of
> that choice, and why would it be awkward if each account simply had a `device_id` property (or a list of them)? (b) Every payment is
> its own relationship, so two accounts that pay each other twenty times have twenty edges. Name one thing you gain and one thing you
> pay for that choice, compared with a single edge carrying a running total.

## Part B — First graph queries (15 minutes)

Run queries **0, 1, 2 and 2b** of `cypher/lab4_queries.cypher`. Query 0 confirms the counts. Query 1 lists the devices shared by three or
more accounts.

**You should see:** `D401` (5 accounts), `D033` (3), `D183` (3). In the Browser, 2b draws the five accounts around `D401`.

Look at `D010` too: two accounts (`A0010`, `A0011`) share it. They belong to the same household. A shared device is **evidence, not proof**.

## Part C — Traversals, and the same question in SQL (45 minutes)

The question: *"How many distinct accounts can money from account X reach in 1, 2, 3, 4 or 5 payments?"* This is a **reachability**
question. A related question counts every distinct **trail**: a route that never reuses the same payment.

**C1. SQL first.** Open the PostgreSQL shell and switch on timing:

```bash
docker compose exec postgres psql -U pesa -d pesa
```

```sql
\timing on
\i /queries/lab4_graph_in_sql.sql
```

The file contains four queries (shared devices, reachability with `UNION`, trails with `UNION ALL`, and the ring). Read the comments in
it. Note the time of each. Leave with `\q`.

**C2. Cypher.** Run queries **3, 4 and 5** of `cypher/lab4_queries.cypher`. Browser shows the elapsed time under each result.

**You should see:**

| Question | Result |
|---|---|
| distinct accounts reachable from `A0001` within 1 to 5 payments | 9, 31, 111, 275, 380 (the SQL and the Cypher agree) |
| trails from the busiest account `A0007`, lengths 1 to 4 | 481, 3,284, 16,962, 114,334 |
| distinct accounts reachable from `A0007` within 1 to 5 payments | 6, 33, 112, 276, 379 |

> **Q4.2 — Predict.** Before you run query 4: for `A0007`, the number of distinct accounts reachable within 4 payments is 276. Will the
> number of **trails** of length 4 be (i) about 276, (ii) a few thousand, or (iii) over a hundred thousand? Say why in terms of how
> the graph is connected. Then run it. What does the result tell you about asking "show me every path" as opposed to "show me every
> reachable account", and what are two ways to keep a traversal from exploding?

> **Q4.3.** Complete the comparison from **your own measurements**, then answer the question below the table.
>
> | | SQL (PostgreSQL) | Cypher (Neo4j) |
> |---|---|---|
> | time for reachability within 4 hops (A0001) | | |
> | time for 4-hop trails (A0007) | | |
> | lines of query text for the ring query (SQL file, query 4, compared with Cypher query 5) | | |
>
> At 12,000 payments, is PostgreSQL slow? Be honest. Then say what you expect to change at 1,000 times the data, and name **one cost
> of adding Neo4j** to the system that has nothing to do with query speed. (Think about the module's thread: where does the graph's
> data come from, and who keeps it correct?)

## Part D — Finding the fraud ring (30 minutes)

Run queries **5, 5b, 6, 7 and 8**. Use the Browser's graph view for 5b.

**You should see:**

| Query | Result |
|---|---|
| 5 | one ring: `A0316, A0317, A0318, A0319, A0316`, 4 hops |
| 6 | `A0320`, linked to the ring through device `D401` |
| 7 | `A0320` paid merchant `M039` the amount `46000` at `2026-09-14T09:20:00Z` |
| 8 | 43 two-hop loops over 17 pairs of accounts |

The ring moved KES 48,500 around four accounts in under six hours, and a **fifth** account that never received a shilling from the ring
(`A0320`) used the same phone and cashed out KES 46,000.

> **Q4.4.** (a) Query 8 shows 43 loops of length two that are **not** fraud (for example two friends settling a bill, `A0020` and
> `A0021`). Name three features, visible in this data, that separate the ring from those harmless loops. (b) A rule that looked only at
> **money flow** misses one member of the ring and a rule that looked only at **shared devices** raises false alarms. Explain which
> member is missed and which household would raise a false alarm. (c) The graph answers questions *after* the data is loaded. Name two
> things that must be true for it to help *during* a payment (hint: freshness and latency), and say which of Lab 4's later
> components provides each.

## Part E — Vector search with pgvector (35 minutes)

A **vector embedding** turns a piece of text into a list of numbers so that texts with similar **meaning** end up close together. Search then
becomes "find the stored vectors nearest to the query vector".

**Honest note.** A real embedding model is a neural network trained on enormous amounts of text. This lab runs on a laptop without
downloading one, so it uses a small **stand-in** (`app/pesa/embed.py`) that groups a few dozen payment-related words into concepts
and adds a weak random signal for other words. It illustrates the mechanics faithfully (vectors, distance, nearest-neighbour search,
indexes). It does **not** understand language. Part E3 shows exactly where it breaks.

**E1. Embed the disputes** (60 customer complaints) and search:

```bash
docker compose exec workbench python app/lab4_embed_disputes.py
docker compose exec workbench python app/lab4_search.py "charged twice for the same payment" --keyword
docker compose exec workbench python app/lab4_search.py "the shop says it sent it but nothing arrived"
docker compose exec workbench python app/lab4_search.py "my money was taken but the app said it failed"
```

**You should see** the top results come from the right category (`double_charge`, `not_received`, `failed_but_debited`) with distances
below 0.1, even though few of the query's words appear in the matching complaints. The `--keyword` option runs a plain
`LIKE`-style search for comparison: it matches words, in no useful order, and includes disputes of the wrong category.

Read the SQL inside `app/lab4_search.py`. The core is:

```sql
SELECT ... FROM dispute_vectors v JOIN disputes d USING (dispute_id)
ORDER BY v.embedding <=> '[0.12, -0.03, ...]'::vector   -- <=> is the COSINE DISTANCE operator
LIMIT 5;
```

The vector search is an ordinary SQL query, joined to an ordinary table. That is the main argument for pgvector over a separate vector
database.

**E2. Metrics.** Run the same query three ways (the inner-product operator returns the **negative** of the similarity, so that
"smaller is closer" holds for all three; its numbers therefore look negative):

```bash
docker compose exec workbench python app/lab4_search.py "charged twice for the same payment" --metric cosine
docker compose exec workbench python app/lab4_search.py "charged twice for the same payment" --metric l2
docker compose exec workbench python app/lab4_search.py "charged twice for the same payment" --metric ip
```

**E3. Make it fail.** Run `"I was scammed"` and `"someone broke into my wallet"`.

> **Q4.5.** (a) The ranking is identical under the three metrics. Why, for these particular vectors? (When would they differ?)
> (b) `"someone broke into my wallet"` finds the unauthorised-transaction disputes, but `"I was scammed"` returns a `not_received`
> dispute. Look at the **distance** of the top result for each. What do you notice, and how would you use that number in a real
> application? (c) A trained model would probably handle "scammed". Why does the stand-in not, and what does that tell you about where a
> vector search gets its quality from?

*(Optional)* To see a dedicated vector store do the same job, install Chroma and run the alternative script:
`docker compose exec workbench pip install "chromadb>=1.0,<2"` then `docker compose exec workbench python app/lab4_chroma.py`.
The top results are the same. What you gain is a purpose-built API; what you lose is the SQL join to the ledger.

## Part F — Approximate indexes: speed against recall (30 minutes)

At 60 rows nothing needs an index. This part generates **30,000** clustered 64-dimensional vectors, finds the true nearest
neighbours by brute force, and measures how well two kinds of approximate index recover them.

```bash
docker compose exec workbench python app/lab4_vector_bench.py          # under a minute
```

Read the script's docstring first. **Recall@10** means: of the true 10 nearest neighbours, what fraction did the index return?

> **Q4.6 — Predict.** The HNSW index has a setting `ef_search` (how many candidates the search keeps while it walks the graph); the
> default is 40. Predict the recall at `ef_search` = 10 and 40, and say whether you expect latency to grow or shrink as `ef_search` grows.
> Then compare with the output. In the output, compare the **exact** search time with the approximate ones: given that exact search
> takes only a few milliseconds here, at what scale would you start to need the index, and why is "approximate" an acceptable word
> for search but not for a ledger?

**You should see:** exact search about 5 ms at recall 1.000; HNSW with `ef_search` = 10 about 0.93 recall at about 0.3 ms, and recall
1.000 from `ef_search` = 40; IVFFlat with 1 probe about 0.96 and 1.000 from 5 probes.

**The trap.** Look at section C of the output: *the nearest 10 vectors where `tag = 7`*, a filter that 1 per cent of the rows satisfy.

> **Q4.7.** (a) With the default `ef_search` = 40, how many rows did the query return per query, out of 10 requested? Explain, using the
> numbers 40 and 1 per cent, why. (b) Setting `ef_search` = 1000 returned only about 8 to 9 rows. Why still fewer than 10? (c) Name two
> designs that avoid the trap (for example one in the database that is not an index setting, and one that changes the data layout).

**See the plan.** The benchmark leaves its table behind. Compare an exact scan with an index scan:

```bash
docker compose exec postgres psql -U pesa -d pesa
```

```sql
EXPLAIN ANALYZE SELECT id FROM bench_vectors
 ORDER BY embedding <=> (SELECT embedding FROM bench_vectors WHERE id = 1) LIMIT 10;      -- Seq Scan + Sort

CREATE INDEX ON bench_vectors USING hnsw (embedding vector_cosine_ops);

EXPLAIN ANALYZE SELECT id FROM bench_vectors
 ORDER BY embedding <=> (SELECT embedding FROM bench_vectors WHERE id = 1) LIMIT 10;      -- Index Scan using ...
\q
```

## Part G — The capstone: one payment through five stores (about 2.5 hours)

Everything so far taught one store at a time. Now they work together, as in the lecture's Pesa architecture.

```
client -> GATEWAY -> [Redis: rate limit, duplicate shortcut]
                 -> [PostgreSQL LEDGER: payment + balances + OUTBOX row, ONE transaction]
RELAY    : outbox (PostgreSQL) --> Redis Stream "pesa.events"   (at least once)
CONSUMERS: stream --> Cassandra (statement) | MongoDB (profile) | Neo4j (graph)   (each idempotent)
REPAIR   : any derived store can be rebuilt from the ledger
```

### G0. Start and reset (about 10 minutes)

```bash
docker compose --profile lab4 down                    # free the memory (data is kept)
docker compose --profile capstone up -d --build       # PostgreSQL, Redis, MongoDB, ONE Cassandra node, Neo4j
docker compose exec workbench python app/capstone/setup_capstone.py
```

**You should see**, one line per store: ledger reset, Redis reset, `cassandra: 15294 statement rows written from the ledger`, 320 customer
documents, and the graph loaded. The capstone uses a **single** Cassandra node (replication factor 1) in its own keyspace `pesa_one`:
the point now is the pipeline, not Cassandra's replication.

Read these four short files before you continue (they are only a few dozen lines each, and every comment is part of the lesson):
`app/capstone/gateway.py`, `relay.py`, `consumers.py`, `verify_consistency.py`.

### G1. One payment, step by step

**G1.1. The gateway.** Account `A0001` pays KES 500 to merchant `M003`:

```bash
docker compose exec workbench python app/capstone/gateway.py --from A0001 --to-kind MERCHANT --to M003 --amount 500 --key order-1001
```

**You should see:** `{"outcome": "SETTLED", "txn_id": "P0a128b653306"}`. Look at the ledger:

```bash
docker compose exec postgres psql -U pesa -d pesa -c "SELECT txn_id, from_account, to_id, amount_kes, status FROM transactions WHERE txn_id LIKE 'P%'" -c "SELECT id, aggregate_id, event_type, published_at FROM outbox"
```

The payment is in the ledger and **one outbox row exists with `published_at` empty**. Nothing else in the system knows yet.

> **Q4.8(a) — Predict.** Run `docker compose exec workbench python app/capstone/verify_consistency.py` now, **after predicting** what the
> columns `cassandra`, `mongo` and `neo4j` will say for this payment. State the consistency model of the system at this moment, in
> two words.

**G1.2. The relay.**

```bash
docker compose exec workbench python app/capstone/relay.py --once
docker compose exec redis redis-cli XRANGE pesa.events - +
```

You will see the event in the stream. **G1.3. The consumers:**

```bash
docker compose exec workbench python app/capstone/consumers.py --group all --once
docker compose exec workbench python app/capstone/verify_consistency.py
```

**You should see** `ok` in every column and `RESULT: all stores agree with the ledger`. Now look at the same payment in each store:

```bash
# Cassandra (replace 2026-10 with the current year and month)
docker compose exec cass-solo cqlsh -e "SELECT account_id, month, txn_id, direction, counterparty, amount_kes FROM pesa_one.transactions_by_account WHERE account_id='A0001' AND month='2026-10' LIMIT 3"
# MongoDB
docker compose exec mongo mongosh pesa --quiet --eval 'printjson(db.customers.findOne({_id:"C0001"}, {loyalty_points:1, recent_transactions:{$slice:1}}))'
# Neo4j
docker compose exec neo4j cypher-shell -u neo4j -p pesa-lab-password "MATCH (a:Account {id:'A0001'})-[r:PAID {txn_id:'P0a128b653306'}]->(m) RETURN a.id, r.amount, m.name"
```

### G2. Break it five ways

Each drill is a real failure. After each, run `verify_consistency.py`.

**Drill 1 — the client retries.** Run the **identical** `gateway.py` command from G1.1 again, and check the balance:

```bash
docker compose exec workbench python app/capstone/gateway.py --from A0001 --to-kind MERCHANT --to M003 --amount 500 --key order-1001
docker compose exec redis redis-cli DEL idem:order-1001               # now pretend Redis forgot the key
docker compose exec workbench python app/capstone/gateway.py --from A0001 --to-kind MERCHANT --to M003 --amount 500 --key order-1001
docker compose exec postgres psql -U pesa -d pesa -c "SELECT balance_kes FROM accounts WHERE account_id='A0001'"
```

**You should see:** `DUPLICATE` with `"source": "redis"`, then `DUPLICATE` with `"source": "ledger"`, and the balance reduced by 500 **once**.

**Drill 2 — the relay dies between "publish" and "mark published".** Make three payments, then crash the relay on purpose:

```bash
for i in 2 3 4; do docker compose exec workbench python app/capstone/gateway.py --from A0001 --to-kind MERCHANT --to M003 --amount 100 --key order-100$i; done
docker compose exec workbench python app/capstone/relay.py --once --simulate-crash
docker compose exec redis redis-cli XLEN pesa.events
docker compose exec postgres psql -U pesa -d pesa -c "SELECT count(*) AS unpublished FROM outbox WHERE published_at IS NULL"
```

> **Q4.8(b) — Predict.** The stream held 1 event before this drill. Predict `XLEN` after the crash and the number of unpublished
> outbox rows. Then run the relay again (`relay.py --once`), predict `XLEN` once more, run `consumers.py --group all --once` and
> `verify_consistency.py`. How can the stream hold more events than there are payments, and why does the loyalty-points total in
> MongoDB stay correct?

**Drill 3 — a derived store is down.**

```bash
docker compose stop neo4j
docker compose exec workbench python app/capstone/gateway.py --from A0002 --to-kind ACCOUNT --to A0003 --amount 250 --key order-2001
docker compose exec workbench python app/capstone/relay.py --once
docker compose exec workbench python app/capstone/consumers.py --group all --once --timeout 20
docker compose exec workbench python app/capstone/verify_consistency.py
```

The consumer for Neo4j reports that it cannot apply the event (the command ends with exit status 1, which is expected), and the two
other stores are fine. Look at what Redis remembers:

```bash
docker compose exec redis redis-cli XPENDING pesa.events neo4j
docker compose start neo4j          # wait about a minute until it is healthy: docker compose ps
docker compose exec workbench python app/capstone/consumers.py --group neo4j --once
docker compose exec workbench python app/capstone/verify_consistency.py
```

> **Q4.9.** (a) During the outage, which store was wrong (as opposed to merely *behind*)? (b) What exactly did Redis remember, and what
> would have happened to the Neo4j update if the consumer had acknowledged the message *before* writing to Neo4j? (c) A customer pays
> and immediately opens their statement; the Cassandra row is not there yet. Name this anomaly, say how long the window is in this design,
> and give two ways an application can hide it from the customer.

**Drill 4 — the anti-pattern: writing to every store from the request.** `dualwrite_demo.py` does what many first designs do: ledger,
then Cassandra, then MongoDB, then Neo4j, directly. Make it die after the second write:

```bash
docker compose exec workbench python app/capstone/dualwrite_demo.py --from A0003 --to-kind ACCOUNT --to A0004 --amount 700 --key d-1
docker compose exec workbench python app/capstone/dualwrite_demo.py --from A0003 --to-kind ACCOUNT --to A0004 --amount 800 --key d-2 --crash-after cassandra
docker compose exec workbench python app/capstone/verify_consistency.py --prefix D
docker compose exec workbench python app/capstone/relay.py --once
docker compose exec workbench python app/capstone/consumers.py --group all --once
docker compose exec workbench python app/capstone/verify_consistency.py --prefix D
```

The second payment's `MISSING` entries **stay** after the relay and consumers have run.

> **Q4.10.** (a) Why does nothing repair the second payment, whereas Drill 2 and Drill 3 repaired themselves? What does the outbox row
> provide that the dual write lacks? (b) Retrying the dual-write request does not work either. Say why, using what you learned about
> idempotency in Lab 1. (c) The outbox is not free. State **three costs** of the pattern (think latency, moving parts, ordering).

**Drill 5 — rebuild from the ledger.** The payment `D…` is in the ledger but missing from two derived stores. Repair them without
replaying any event:

```bash
docker compose exec workbench python app/capstone/rebuild_from_ledger.py neo4j
docker compose exec workbench python app/capstone/rebuild_from_ledger.py mongo
docker compose exec workbench python app/capstone/verify_consistency.py
```

**You should see** `RESULT: all stores agree with the ledger`. This works because the ledger holds the complete truth. The reverse is
impossible: you could not rebuild the ledger from MongoDB's five-item lists or from the graph.

### G3. Check your work and write the design memo

```bash
bash scripts/verify.sh 4
bash scripts/verify.sh capstone
```

**Design memo** (`my_work/Lab4_design_memo.md`, 350 to 500 words, **assessed**). Write an *architecture decision record* for the Pesa
Platform. A table with one row for each of these eight needs, naming the store, whether it is **authoritative or derived**, how it is
**rebuilt**, and the **staleness** the business can tolerate:

1. the authoritative balance and payment record; 2. rate limiting; 3. the account statement ("my payments this month");
4. the app's home-screen profile; 5. fraud-ring detection; 6. similar-dispute search; 7. the merchant leaderboard; 8. login sessions.

Then, in prose: (a) the **one component** whose failure would stop *payments* (not merely make some view stale), and why you have
accepted that; (b) the single store you would **remove first** to cut cost and what risk you accept by doing so; (c) the one point of the
design you are **least confident about** and how you would test it.

## Shutting down

```bash
docker compose --profile capstone down            # stops the containers, KEEPS the data
bash scripts/reset_lab.sh                         # deletes everything
```

## If something goes wrong

| Symptom | Likely cause | What to do |
|---|---|---|
| `setup_capstone.py` hangs at Cassandra | `cass-solo` is still starting | wait; `docker compose ps` must show it healthy (1 to 3 minutes) |
| `neo4j` is unhealthy | it needs more time, or memory | `docker compose logs neo4j`; wait a minute; raise Docker memory |
| `verify_consistency.py` shows `MISSING` forever | a step was skipped | run `relay.py --once`, then `consumers.py --group all --once`; for the dual write use Drill 5 |
| Consumers print `could not be applied` | a store is down or the chaos key is set | `docker compose ps`; `redis-cli KEYS 'chaos:*'` and `DEL` any you find |
| `Name or service not known: cass-solo` | the capstone profile is not running | `docker compose --profile capstone up -d` |
| Vector benchmark: `type "vector" does not exist` | the extension is installed per database | run `python app/lab4_embed_disputes.py` first (it creates it) |
| Want to repeat the capstone from scratch | | `python app/capstone/setup_capstone.py` resets all five stores |
