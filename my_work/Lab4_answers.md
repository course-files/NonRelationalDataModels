# Lab 4 — Graph, Vector and One System: my answers

> Name: ____________    Student number: ____________    Date: ____________
> Write your own answer under each question (1 to 4 sentences unless the question asks for more).
> For **Predict** questions write your prediction BEFORE you run the command, and add what actually happened.
> Lines that start with ">" or "#" are instructions and are not counted as your writing.

## Q4.1
> **Q4.1.** In this model a **Device is a node**, not a property of an account. (a) Which fraud question becomes natural because of
> that choice, and why would it be awkward if each account simply had a `device_id` property (or a list of them)? (b) Every payment is
> its own relationship, so two accounts that pay each other twenty times have twenty edges. Name one thing you gain and one thing you
> pay for that choice, compared with a single edge carrying a running total.

<!-- write your answer below this line -->

## Q4.2
> **Q4.2 — Predict.** Before you run query 4: for `A0007`, the number of distinct accounts reachable within 4 payments is 276. Will the
> number of **trails** of length 4 be (i) about 276, (ii) a few thousand, or (iii) over a hundred thousand? Say why in terms of how
> the graph is connected. Then run it. What does the result tell you about asking "show me every path" as opposed to "show me every
> reachable account", and what are two ways to keep a traversal from exploding?

<!-- write your answer below this line -->

## Q4.3
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

<!-- write your answer below this line -->

## Q4.4
> **Q4.4.** (a) Query 8 shows 43 loops of length two that are **not** fraud (for example two friends settling a bill, `A0020` and
> `A0021`). Name three features, visible in this data, that separate the ring from those harmless loops. (b) A rule that looked only at
> **money flow** misses one member of the ring and a rule that looked only at **shared devices** raises false alarms. Explain which
> member is missed and which household would raise a false alarm. (c) The graph answers questions *after* the data is loaded. Name two
> things that must be true for it to help *during* a payment (hint: freshness and latency), and say which of Lab 4's later
> components provides each.

<!-- write your answer below this line -->

## Q4.5
> **Q4.5.** (a) The ranking is identical under the three metrics. Why, for these particular vectors? (When would they differ?)
> (b) `"someone broke into my wallet"` finds the unauthorised-transaction disputes, but `"I was scammed"` returns a `not_received`
> dispute. Look at the **distance** of the top result for each. What do you notice, and how would you use that number in a real
> application? (c) A trained model would probably handle "scammed". Why does the stand-in not, and what does that tell you about where a
> vector search gets its quality from?

<!-- write your answer below this line -->

## Q4.6
> **Q4.6 — Predict.** The HNSW index has a setting `ef_search` (how many candidates the search keeps while it walks the graph); the
> default is 40. Predict the recall at `ef_search` = 10 and 40, and say whether you expect latency to grow or shrink as `ef_search` grows.
> Then compare with the output. In the output, compare the **exact** search time with the approximate ones: given that exact search
> takes only a few milliseconds here, at what scale would you start to need the index, and why is "approximate" an acceptable word
> for search but not for a ledger?

<!-- write your answer below this line -->

## Q4.7
> **Q4.7.** (a) With the default `ef_search` = 40, how many rows did the query return per query, out of 10 requested? Explain, using the
> numbers 40 and 1 per cent, why. (b) Setting `ef_search` = 1000 returned only about 8 to 9 rows. Why still fewer than 10? (c) Name two
> designs that avoid the trap (for example one in the database that is not an index setting, and one that changes the data layout).

<!-- write your answer below this line -->

## Q4.8(a)
> **Q4.8(a) — Predict.** Run `docker compose exec workbench python app/capstone/verify_consistency.py` now, **after predicting** what the
> columns `cassandra`, `mongo` and `neo4j` will say for this payment. State the consistency model of the system at this moment, in
> two words.

<!-- write your answer below this line -->

## Q4.8(b)
> **Q4.8(b) — Predict.** The stream held 1 event before this drill. Predict `XLEN` after the crash and the number of unpublished
> outbox rows. Then run the relay again (`relay.py --once`), predict `XLEN` once more, run `consumers.py --group all --once` and
> `verify_consistency.py`. How can the stream hold more events than there are payments, and why does the loyalty-points total in
> MongoDB stay correct?

<!-- write your answer below this line -->

## Q4.9
> **Q4.9.** (a) During the outage, which store was wrong (as opposed to merely *behind*)? (b) What exactly did Redis remember, and what
> would have happened to the Neo4j update if the consumer had acknowledged the message *before* writing to Neo4j? (c) A customer pays
> and immediately opens their statement; the Cassandra row is not there yet. Name this anomaly, say how long the window is in this design,
> and give two ways an application can hide it from the customer.

<!-- write your answer below this line -->

## Q4.10
> **Q4.10.** (a) Why does nothing repair the second payment, whereas Drill 2 and Drill 3 repaired themselves? What does the outbox row
> provide that the dual write lacks? (b) Retrying the dual-write request does not work either. Say why, using what you learned about
> idempotency in Lab 1. (c) The outbox is not free. State **three costs** of the pattern (think latency, moving parts, ordering).

<!-- write your answer below this line -->

