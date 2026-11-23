# Lab 2: The Wide-Column Model (Apache Cassandra)

**Course:** Non-Relational Data Models (Module 4) · **Scenario:** the Pesa Platform
**Time:** about 3 hours · **Memory needed:** about 6 GB (three Cassandra nodes of roughly 1.5 GB each, plus the workbench)
**Written work to hand in:** `my_work/Lab2_answers.md` and `my_work/Lab2_design_memo.md`

> **Memory warning.** Cassandra is a Java program and is the heaviest system in this module. Set Docker's memory limit to at least
> **10 GB** (Docker Desktop, Settings, Resources). If you cannot, tell me (your lecturer): Parts A to D can be completed with fewer
> nodes, and Lab 3 offers a simulator track that needs no Cassandra at all.

---

## 0. What you will learn

1. Explain how a Cassandra cluster decides **where a row lives** (partition key, hash, token ring, virtual nodes, replicas).
2. Design tables **from the queries backwards**, using partition keys, clustering columns and time buckets.
3. Predict which CQL queries Cassandra will accept, and say why it refuses the others.
4. Predict and demonstrate what each **consistency level** does when nodes are down, and use `R + W > RF` correctly.
5. Observe **hinted handoff** and **repair**, the two mechanisms that bring a lagging replica back in step.
6. Explain why `INSERT ... IF NOT EXISTS` costs far more than Redis's `SET ... NX`.

Throughout, remember the module's thread: Cassandra here holds the **account statement**, a copy of ledger data shaped for the query
"show this account's payments for a month". It is not the system of record.

## 1. How to work through this lab

Same conventions as Lab 1: commands in grey boxes, **You should see** for expected output, **Predict** questions answered *before* you
run, answers in `my_work/Lab2_answers.md`.

## Part A: Start the cluster and read the ring (25 minutes)

```bash
docker compose --profile lab2 up -d --build
```

**What is happening:** three Cassandra containers start **one after another** (`cass1`, then `cass2`, then `cass3`). Cassandra requires
that, because nodes joining at the same moment can claim the same token ranges. Expect 4 to 8 minutes. Watch progress with
`docker compose ps`; wait until all three say `healthy`.

```bash
docker compose exec cass1 nodetool status
```

**You should see** three lines starting `UN` (**U**p, **N**ormal), data centre `dc1`, rack `rack1`, and `Tokens` equal to **16** on each.
Each node owns 16 positions ("virtual nodes") on the hash ring instead of a single large range. That spreads data and recovery work more
evenly, and it is why adding a node takes a little from many nodes instead of half from one.

> **Q2.1: Predict.** The cluster will soon have a keyspace with replication factor 3 (RF = 3). With three nodes, what **Owns (effective)**
> percentage will `nodetool status pesa` show for each node? What would you expect for RF = 1? Write both predictions, then check
> the first one after Part B.

## Part B: Create the tables and load the data (45 minutes)

**B1. Load.** The script creates the keyspace and four tables and writes the payment history. Read the `DDL` list at the top of
`app/lab2_load_cassandra.py` first; every comment there is part of the lesson.

```bash
docker compose exec workbench python app/lab2_load_cassandra.py
docker compose exec cass1 nodetool status pesa          # now with a keyspace: check Q2.1
```

**You should see:** `keyspace and tables created`, then `transactions_by_account  15294 rows written, 0 failed`,
`transactions_by_merchant_day  8706 rows written, 0 failed`, `transactions_by_account_nobucket  2500 rows written, 0 failed`.
(15,294 = 12,000 payer rows plus 3,294 payee rows: the same payment is written **twice** for account-to-account transfers,
once for each side, because each side has its own query.)

**B2. Query it.**

```bash
docker compose exec cass1 cqlsh
```

```sql
DESCRIBE KEYSPACE pesa;                         -- read the primary keys carefully
CONSISTENCY QUORUM;                             -- cqlsh setting: a majority of replicas must answer

-- "Show account A0001's payments for September", newest first:
SELECT txn_time, direction, counterparty, amount_kes, status
  FROM pesa.transactions_by_account
 WHERE account_id = 'A0001' AND month = '2026-09'
 LIMIT 5;
```

**You should see** up to five rows, the newest first. The order comes from `CLUSTERING ORDER BY (txn_time DESC ...)`: the rows are
**stored** in that order inside the partition, so no sort happens at read time.

> **Q2.2: Predict.** For each query below, write **accepted** or **rejected**, and in one phrase say why. Then run them all in `cqlsh`.
> (The word *rejected* means Cassandra refuses the query and asks for `ALLOW FILTERING`.)
>
> ```sql
> -- (a)
> SELECT * FROM pesa.transactions_by_account WHERE account_id = 'A0001' AND month = '2026-09';
> -- (b)
> SELECT * FROM pesa.transactions_by_account WHERE account_id = 'A0001';
> -- (c)
> SELECT * FROM pesa.transactions_by_account WHERE account_id = 'A0001' AND month = '2026-09'
>    AND txn_time >= '2026-09-14 00:00:00+0000' AND txn_time < '2026-09-15 00:00:00+0000';
> -- (d)
> SELECT * FROM pesa.transactions_by_account WHERE account_id = 'A0001' AND month = '2026-09' AND amount_kes > 10000;
> -- (e)
> SELECT * FROM pesa.transactions_by_account WHERE counterparty = 'M001';
> ```
>
> State the rule that explains your five answers.

**B3. A new query, a new table.** Fraud analysts ask: *"Which payments used device D401 on 14 September 2026?"* The
ledger rows carry a `device_id`. Write the `CREATE TABLE` for a table `pesa.payments_by_device_day` that answers this with **one
partition read**: choose the partition key and clustering columns, and justify the choice in a comment. Then insert two rows by hand and
query them:

```sql
-- your CREATE TABLE here (columns: device_id, day, txn_time, txn_id, account_id, amount_kes)
-- INSERT two rows for device 'D401' on day '2026-09-14'
-- SELECT ... WHERE device_id = 'D401' AND day = '2026-09-14';
```

Leave `cqlsh` with `exit`. (Your table is not loaded with all the data; the point is the **design**. In production, the application or
an event consumer would write each payment to this table too, which is exactly what the Lab 4 capstone does for its own table.)

## Part C: Partitions: how big, how hot (30 minutes)

Cassandra is happy with many **small and medium** partitions and unhappy with a few huge ones, because a partition is the unit of
distribution *and* of reading. Compare the two designs for the busy account `A0007`.

```bash
docker compose exec cass1 nodetool flush pesa            # write memtables to disk so the statistics are complete
docker compose exec cass1 nodetool tablestats pesa.transactions_by_account_nobucket | grep -E "Number of partitions|Compacted partition (maximum|mean) bytes"
docker compose exec cass1 nodetool tablestats pesa.transactions_by_account          | grep -E "Number of partitions|Compacted partition (maximum|mean) bytes"
```

`transactions_by_account_nobucket` holds **only A0007**, with one partition per account and no time bucket. The other table
partitions by `(account_id, month)`. (The statistics are histogram-based estimates, so compare orders of magnitude, not exact bytes.)

For the **hot partition** question, ask the ledger how the load is spread. In a second terminal:

```bash
docker compose --profile lab1 up -d postgres          # the ledger is needed only for this query
docker compose exec postgres psql -U pesa -d pesa -c "
  SELECT to_id, count(*) AS payments, count(DISTINCT (ts AT TIME ZONE 'UTC')::date) AS days,
         max(per_day) AS busiest_day
    FROM (SELECT to_id, ts, count(*) OVER (PARTITION BY to_id, (ts AT TIME ZONE 'UTC')::date) AS per_day
            FROM transactions WHERE to_kind = 'MERCHANT') x
   GROUP BY to_id ORDER BY payments DESC LIMIT 3;"
```

**You should see** `M001` first: **2,362 payments over 92 days, busiest day 40**.

> **Q2.3.** (a) `A0007` makes about 27 payments a day. If one payment row is about 100 bytes, how many rows and how many megabytes will
> its **unbucketed** partition hold after 5 years? (b) The usual guidance is to keep a partition under roughly 100 MB. Is `A0007` in
> danger? Be honest: if the answer is "not yet", say what kind of account **would** be, with numbers (for example an aggregator
> account with 50,000 payments a day). (c) `transactions_by_merchant_day` uses the partition key `(merchant_id, day)`. What would happen
> to merchant `M001` if the key were `merchant_id` alone? What does the day bucket cost the **reader**?

## Part D: Replicas, consistency levels and outages (40 minutes)

**D1. Where are the replicas?** Write one row and ask which nodes hold it:

```bash
docker compose exec cass1 cqlsh -e "CONSISTENCY QUORUM; INSERT INTO pesa.idempotency_keys (idem_key, txn_id, created_at) VALUES ('order-1001', 'P0001', toTimestamp(now()));"
docker compose exec cass1 nodetool getendpoints pesa idempotency_keys order-1001
```

**You should see** three addresses. With 3 nodes and RF = 3, **every** node holds a copy of **every** row. So the question is no longer
"where is it" but "how many copies must answer before I trust the result?" That number is the **consistency level (CL)**.

| CL | Replicas that must respond (RF = 3) |
|---|---|
| `ONE` | 1 |
| `QUORUM` | 2 (a majority: floor(RF / 2) + 1) |
| `ALL` | 3 |

**D2. Break the cluster, one node at a time.** Open `cqlsh` and set up a repeatable read:

```bash
docker compose exec cass1 cqlsh
```

```sql
CONSISTENCY ONE;
SELECT * FROM pesa.idempotency_keys WHERE idem_key = 'order-1001';
CONSISTENCY QUORUM;
SELECT * FROM pesa.idempotency_keys WHERE idem_key = 'order-1001';
CONSISTENCY ALL;
SELECT * FROM pesa.idempotency_keys WHERE idem_key = 'order-1001';
```

All three succeed. Now, **in another terminal**, stop one node, and wait until `nodetool status` shows `DN` for it (about 10 to 30 seconds):

```bash
docker compose stop cass3
docker compose exec cass1 nodetool status
```

> **Q2.4: Predict.** Complete the table with **ok** or **fail** for a *read* at each CL, before you try. Then run the three
> `SELECT` statements again for each situation. (A failure looks like `Unavailable ... Cannot achieve consistency level QUORUM`.)
>
> | Consistency level | all 3 nodes up | `cass3` stopped | `cass2` and `cass3` stopped |
> |---|---|---|---|
> | `ONE` | ok | | |
> | `QUORUM` | ok | | |
> | `ALL` | ok | | |
>
> Now stop `cass2` as well (`docker compose stop cass2`) and test the third column. Finally answer: (b) with RF = 3, which
> combinations of write level W and read level R guarantee that a read sees the latest write (`R + W > RF`), and which do not?
> (c) Which level would you choose for the *write* of a payment's status, and which for a *dashboard read* that can be a few seconds
> out of date? Justify each in a sentence.

**Restore the cluster** before Part E (start the nodes in order):

```bash
docker compose start cass2
docker compose exec cass1 nodetool status      # wait for UN
docker compose start cass3
docker compose exec cass1 nodetool status      # wait until all three are UN
```

## Part E: A replica falls behind: hints and repair (35 minutes)

A node that is down misses writes. Cassandra has two mechanisms to catch it up. You will watch both.

**E1. Hinted handoff** (automatic, short-term). Create a small table and take `cass3` offline:

```bash
docker compose exec workbench python app/lab2_hint_demo.py create
docker compose stop cass3
docker compose exec workbench python app/lab2_hint_demo.py write --n 500 --cl QUORUM
bash scripts/node_counts.sh pesa.hint_demo
```

**You should see** `wrote rows 1..500 at consistency QUORUM: 500 succeeded, 0 failed` (two of three replicas are enough), and
`cass1` and `cass2` each holding about 500 partitions (`cass3` is not listed because it is down).

Now bring the node back and watch it catch up. Run the second command several times over the next minute:

```bash
docker compose start cass3
bash scripts/node_counts.sh pesa.hint_demo
```

**What is happening:** while `cass3` was down, the coordinators saved a *hint* (a note "deliver this write to cass3 later") for
each missed write. When `cass3` returns, the hints are replayed and its count climbs to about 500. Hints are kept only for a limited
time (three hours by default) because storing them for a long outage would be a heavy load. A node that has been down longer than
that has **permanently** missed those writes unless something else repairs it.

**E2. Anti-entropy repair** (manual, thorough). Now repeat the experiment **without hints**, as if the outage had been too long:

```bash
docker compose exec cass1 nodetool disablehandoff        # stop storing hints on the two nodes that stay up
docker compose exec cass2 nodetool disablehandoff
docker compose stop cass3
docker compose exec workbench python app/lab2_hint_demo.py write --n 500 --start 501 --cl QUORUM
docker compose start cass3
# wait until all three nodes are UN, then compare:
bash scripts/node_counts.sh pesa.hint_demo
```

**You should see** `cass1` and `cass2` at about 1,000 partitions while `cass3` stays at about 500: it never received rows 501 to 1000.

```bash
docker compose exec cass3 nodetool repair pesa hint_demo
bash scripts/node_counts.sh pesa.hint_demo
docker compose exec cass1 nodetool enablehandoff         # put the setting back
docker compose exec cass2 nodetool enablehandoff
```

**You should see** `Repair completed successfully` and then all three nodes at about 1,000.

> **Q2.5.** (a) Why did the write at `QUORUM` succeed while `cass3` was down, and what did the client *not* learn about `cass3`?
> (b) In one sentence each, what do hints do and what does repair do, and why can hints **not** replace repair? (c) Repair must also run
> regularly on a healthy cluster (at least once every `gc_grace_seconds`, ten days by default) for a reason connected to **deletes**.
> Explain in two or three sentences what could go wrong with a deleted row if repair is skipped. (Hint: a delete is a write too.)

## Part F: Idempotency, the Cassandra way (20 minutes)

In Lab 1 you used Redis `SET key value NX EX 60` to accept only the first of 50 simultaneous requests. Cassandra offers a similar
guarantee, called a **lightweight transaction** (LWT):

```bash
docker compose exec cass1 cqlsh
```

```sql
CONSISTENCY QUORUM;
INSERT INTO pesa.idempotency_keys (idem_key, txn_id, created_at) VALUES ('order-2001', 'P0002', toTimestamp(now())) IF NOT EXISTS;
-- run the SAME statement again:
INSERT INTO pesa.idempotency_keys (idem_key, txn_id, created_at) VALUES ('order-2001', 'P0003', toTimestamp(now())) IF NOT EXISTS;
```

**You should see** `[applied] True` the first time, and `[applied] False` with the **existing** row the second time.

To see the price, switch tracing on and run a plain insert, then the conditional one:

```sql
TRACING ON;
INSERT INTO pesa.idempotency_keys (idem_key, txn_id, created_at) VALUES ('order-3001', 'P0004', toTimestamp(now()));
INSERT INTO pesa.idempotency_keys (idem_key, txn_id, created_at) VALUES ('order-3002', 'P0005', toTimestamp(now())) IF NOT EXISTS;
```

Compare the number of lines in the two traces and the `Total duration` they print.

> **Q2.6.** (a) How many network round trips between replicas does the conditional insert need compared with the plain one, and
> what do you conclude about using LWT on a hot path? (b) Redis `NX` is a single atomic command on a single node. What did Cassandra
> have to add (hint: the replicas must *agree*) to give the same guarantee across three nodes? (c) In the Lab 4 capstone the idempotency
> decision is made in PostgreSQL. Give one reason that is better than either Redis or Cassandra for this job.

## Part G: Check your work and write the design memo (25 minutes)

```bash
bash scripts/verify.sh 2
```

**Design memo** (`my_work/Lab2_design_memo.md`, 200 to 300 words, marked). Merchants want a **settlement dashboard** with two
screens: (1) *all payments received in the last 7 days, newest first*; (2) *total received per day for the last 30 days*.

Write the `CREATE TABLE` statements you would use (partition key, clustering columns, clustering order, and any time bucket), and say
for each: which screen it serves, how many partitions a read touches, and the largest partition you expect for a busy merchant such as
`M001`. Then state the consistency level for writes and reads, **what you duplicate** and **who keeps the duplicates in step with the
ledger**, and one thing that would force you to redesign the tables.

## Shutting down

```bash
docker compose --profile lab2 down              # stops the containers, KEEPS the data
bash scripts/reset_lab.sh                       # only if you want to delete everything
```

## If something goes wrong

| Symptom | Likely cause | What to do |
|---|---|---|
| `cass2` or `cass3` never becomes healthy | Docker has too little memory, or the previous node is still starting | `docker compose logs cass2`; raise Docker memory to 10 GB; `docker compose up -d` again |
| `NoHostAvailable` from a script | Cassandra is still starting | the scripts retry for 3 minutes; wait, or check `docker compose ps` |
| `nodetool` says `Connection refused` | JMX not ready yet | wait 30 seconds |
| `Unavailable` in Part B or C | a node from Part D is still stopped | `docker compose start cass2 cass3` and wait for `UN` |
| `nodetool status` shows `DN` for a running container | gossip has not caught up | wait a minute; if it persists, `docker compose restart <node>` |
| Counts in Part E do not change | `nodetool flush` ran before hints arrived | wait 30 seconds and run `bash scripts/node_counts.sh pesa.hint_demo` again |
