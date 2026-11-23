# Lab 1: Key-Value and Document Models (Redis and MongoDB)

**Course:** Non-Relational Data Models (Module 4) · **Scenario:** the Pesa Platform, a mobile-payments service
**Time:** about 3.5 hours · **Memory needed:** about 2.5 GB (PostgreSQL, Redis, MongoDB and the workbench)
**Written work to hand in:** `my_work/Lab1_answers.md` and `my_work/Lab1_design_memo.md`

---

## 0. What you will learn

By the end of this lab you will be able to:

1. Choose between the Redis data structures (string, hash, set, sorted set, HyperLogLog) by the **question** being asked, not by habit.
2. Explain why `SET key value NX EX` is safe where "read, then write" is not, and use it to make a payment **idempotent**.
3. Build a **cache-aside** read path, measure when it helps, and explain the one bug every cache has.
4. State exactly what Redis persistence and eviction settings promise, and what they do not.
5. Design a MongoDB **aggregate document** around one screen of the application, and say what must stay out of it.
6. Use a schema validator, an index and `explain()` in MongoDB, and describe the cost of **denormalized** data.
7. Decide when the single-document atomicity of MongoDB is enough and when a multi-document transaction is needed.

The thread that runs through the whole module: **the ledger stays in PostgreSQL**. Redis and MongoDB hold copies shaped
for one job each. You will keep asking: *if this store lost everything, what would I lose, and how would I rebuild it?*

## 1. How to work through this lab

* Commands are shown in grey boxes. Run them exactly as written, from the lab folder, in a terminal.
* Text marked **You should see** tells you what correct output looks like. If yours differs, stop and read the output before continuing.
* Questions are marked **Q1.1, Q1.2 ...**. The ones marked **Predict** ask you to write your prediction **before** you run the command. A wrong prediction is useful; a prediction written after the result teaches you nothing. Write your answers in `my_work/Lab1_answers.md` (1 to 4 sentences each).
* Comments inside code and command boxes (lines beginning with `#` or `//` or `--`) are part of the teaching. Read them.
* Data is synthetic. Merchant names, people and phone numbers are invented.

## Part A: Start the stack and meet the ledger (15 minutes)

**A1. Check your computer** (first lab only):

```bash
bash scripts/check_prereqs.sh
```

**A2. Start Lab 1's services.** The first run downloads images and builds the workbench, therefore, it takes several minutes.

```bash
docker compose --profile lab1 up -d --build
docker compose ps          # postgres, redis and mongo should say "healthy" after a minute
```

**What is happening:** a *profile* is a named group of services. `--profile lab1` starts PostgreSQL, Redis and MongoDB, plus the
always-on `workbench` container that holds Python and all database drivers. On its first start PostgreSQL runs the files in
`sql/` once, which creates the ledger schema and loads 12,000 payments. MongoDB's start-up script makes it a one-member
*replica set*; you will see why in Part H.

**A3. Look at the ledger.** Open the PostgreSQL shell:

```bash
docker compose exec postgres psql -U pesa -d pesa
```

```sql
-- how big is the data set?
SELECT count(*) AS payments, min(ts)::date AS first_day, max(ts)::date AS last_day FROM transactions;
-- who is the busiest payer? (a "hot" account you will meet again in Lab 2)
SELECT from_account, count(*) FROM transactions GROUP BY 1 ORDER BY 2 DESC LIMIT 3;
-- leave the shell
\q
```

**You should see:** 12,000 payments from 2026-07-01 to 2026-09-30; account `A0007` first, with 2,500 payments.

Keep this picture in mind: `customers`, `accounts`, `merchants`, `devices`, `transactions`, `disputes`. This is the **system of record**.
Everything you build next is a *derived copy*.

## Part B: Redis data structures (45 minutes)

Open the Redis shell. It is a **Read-Eval-Print Loop (REPL)**:
A REPL is an interactive environment that lets you enter and execute commands
one at a time and immediately see the results.

```bash
docker compose exec redis redis-cli
```

### B1. Strings and time-to-live

```text
# A login session for customer account A0001, valid for 60 seconds
SET session:abc123 "A0001" EX 60
TTL session:abc123
GET session:abc123
```

`EX 60` sets an expiry; `TTL` reports the seconds left (-1 means "no expiry", -2 means "key does not exist").

> **Q1.1 Predict.** You now run `SET session:abc123 "A0002"` (a plain `SET`, nothing else) and then `TTL session:abc123`.
> What number do you expect, and what would that mean for a real login system? Write your prediction, then run it.
> How would you change the command so the session still expires?

### B2. Counters (a rate limiter in two lines)

```bash
# "At most N requests per minute": one counter per account per minute window
INCR rl:A0001:window1
INCR rl:A0001:window1
EXPIRE rl:A0001:window1 70 NX
TTL rl:A0001:window1
```

`INCR` is atomic: two clients incrementing at once never lose a count. `EXPIRE ... NX` sets the expiry only if none exists yet,
so the window does not slide forward on every request. (In the capstone these two commands run together inside `MULTI`/`EXEC`.)

### B3. Hashes (an object with fields)

```bash
HSET cust:C0001 name "Nyambura Mbugua" county "Uasin Gishu" points 359
HGET cust:C0001 county
HINCRBY cust:C0001 points 5
HGETALL cust:C0001
```

A hash is like one row, but each field can be read or changed alone.

### B4. Sets (membership, no duplicates, set algebra)

```bash
SADD device:D010:accounts A0010 A0011
SADD device:D033:accounts A0033 A0045 A0185
SMEMBERS device:D010:accounts
SINTER device:D010:accounts device:D033:accounts      # accounts that used BOTH devices (none here)
```

### B5. Sorted sets (a leaderboard)

First load the real data. In a second terminal (the workbench container runs the lab scripts):

```bash
docker compose exec workbench python app/lab1_load_redis.py
```

**You should see:** `sorted set lb:merchant:2026-09 -> 40 merchants` and `HyperLogLogs uniq:dev:<date> -> 92 days`.

Back in `redis-cli`:

```
ZREVRANGE lb:merchant:2026-09 0 4 WITHSCORES      # the five merchants with the highest September takings
ZSCORE lb:merchant:2026-09 M003
ZREVRANK lb:merchant:2026-09 M003                 # position, counting from 0 at the top
ZINCRBY lb:merchant:2026-09 500 M003              # a new payment of KES 500 arrives
ZREVRANK lb:merchant:2026-09 M003
```

**You should see** `M001` first with `835300`, then `M002` `327330`, `M003` `247900`, `M004` `189630`, `M005` `131750`.

**What is happening:** a sorted set keeps members ordered by score, so "top 5" is a lookup, not a sort over 8,706 payments.
This is a **derived view**: the loader computed it from the ledger. If Redis lost it, you would recompute it.

### B6. HyperLogLog (counting distinct things in a few hundred bytes)

```
PFCOUNT uniq:dev:2026-09-14                  # estimated distinct devices that paid on 14 September
MEMORY USAGE uniq:dev:2026-09-14             # bytes used
PFCOUNT uniq:dev:2026-09-14 uniq:dev:2026-09-15   # distinct devices over BOTH days (a union, not a sum)
```

> **Q1.2 — Predict, then measure.** (a) The HyperLogLog is an *estimate*. Before you check, say how large an error you expect on a
> day with about 70 devices. (b) Now ask PostgreSQL for the exact answer:
>
> ```sql
> SELECT count(DISTINCT device_id) FROM transactions
>  WHERE (ts AT TIME ZONE 'UTC')::date = '2026-09-14' AND status = 'SETTLED' AND device_id IS NOT NULL;
> ```
>
> Compare. (c) Name one question about devices that a HyperLogLog **cannot** answer, and one reason you would not use it for money.

Leave `redis-cli` with `exit`.

## Part C: Atomicity and idempotency (25 minutes)

**Scenario.** A mobile app retries a payment because the network was slow. The same request, with the same *idempotency key*,
reaches the server 50 times at the same instant. **Exactly one** of them may move money.

```bash
docker compose exec workbench python app/lab1_race.py
```

Open `app/lab1_race.py` and read the two functions `naive_claim` and `atomic_claim` before you look at the output.

**You should see** `naive: 50 of 50 requests believed they were first` and `atomic: 1 of 50`.
(The naive result is deterministic here because the script adds a short pause between the check and the write, which models
real application work. Without the pause, the race is still there; it is only harder to see.)

> **Q1.3.** (a) Explain in two sentences why 50 requests passed the naive check, and why exactly one passes `SET ... NX`.
> (b) The idempotency key is stored with `EX 60` (it expires). What goes wrong if there is **no** expiry, and what goes wrong if the
> expiry is **shorter than the longest time a client might retry**? Suggest a sensible expiry for a payments API and justify it.
> (c) Redis is fast but is not the ledger. If this key is lost (Redis restarts), can a payment be taken twice? What in the
> *capstone* design (Lab 4) prevents that?

## Part D: Cache-aside (40 minutes)

**The pattern.** *Read:* look in Redis; on a miss, read the source of truth and store a copy. *Write:* change the source of
truth, then make sure the old copy cannot be served. The source of truth here is the PostgreSQL ledger.

**D1. When does a cache help?**

```bash
docker compose exec workbench python app/lab1_cache_aside.py benchmark
```

**You should see** two lines, one for a *primary-key lookup* of a balance and one for a *monthly summary* (an aggregation over an
account's history). Typical figures: the key lookup is **no faster** with the cache (about 0.1 ms either way), while the summary
drops from about 0.6 ms to about 0.13 ms. Your numbers will differ; the *pattern* is what matters.

> **Q1.4(a).** Why does the cache help one read and not the other? What property of a read makes it a good cache candidate?
> (Think about what the database must do, and how often the answer changes.)

**D2. The classic bug.**

```bash
docker compose exec workbench python app/lab1_cache_aside.py stale
```

**You should see** the database showing the new balance while the cache still serves the old one, "stale for up to 30 s".

**D3. Your fix.** Open `app/lab1_cache_aside.py`, find `credit_safe()` (marked `TODO`). Implement it: credit the account in the
database, then make sure the cached copy cannot be served. Then:

```bash
docker compose exec workbench python app/lab1_cache_aside.py check
```

**You should see** `PASS`. If you see `NOT YET`, the TODO is still unfinished; if you see `FAIL`, read its message.

> **Q1.4(b) — Challenge.** Your fix deletes the cached key after the database write. Describe **one precise interleaving** of
> a reader and a writer in which a stale value can still end up in the cache. (Hint: the reader's miss, the reader's database
> read and the reader's `SET` are three separate steps.) What finally limits the damage?

## Part E : Persistence and eviction: what Redis promises (35 minutes)

Redis keeps its data in memory. Two settings decide what survives a restart and what happens when memory is full.

**E1. Persistence off (the lab default).**

```bash
docker compose exec redis redis-cli DBSIZE            # 93 keys loaded in Part B (the cache entries of Part D expire after 30 s: wait for that first)
docker compose exec redis redis-cli CONFIG GET appendonly
```

> **Q1.5(a) — Predict.** You run `docker compose restart redis` and then `DBSIZE` again. What number do you expect? Write it down.

```bash
docker compose restart redis
docker compose exec redis redis-cli DBSIZE
```

**E2. Persistence on (AOF).** AOF ("append-only file") logs every write; with `appendfsync everysec` the log is flushed to disk
once per second. Switch it on by editing `.env`:

```conf
REDIS_APPENDONLY=yes
```

```bash
docker compose --profile lab1 up -d redis              # recreates the container with the new setting
docker compose exec workbench python app/lab1_load_redis.py
docker compose exec redis redis-cli CONFIG GET appendonly
docker compose restart redis
docker compose exec redis redis-cli DBSIZE             # the 93 keys are back
docker compose exec redis redis-cli INFO persistence | grep -E "aof_enabled|aof_last_write_status"
```

**What is happening:** at start-up Redis replays the log. `everysec` means that after a **power
cut or operating-system crash** you can lose up to about one second of writes. A mere crash of the Redis *process* loses
almost nothing, because the operating system still holds the data it was given.

**E3. When memory is full.** The script gives Redis a small memory limit, writes 200 idempotency keys, then floods it with cache
entries, and reports what happened. Run it once per policy and compare:

```bash
docker compose exec workbench python app/lab1_eviction.py --policy noeviction
docker compose exec workbench python app/lab1_eviction.py --policy allkeys-lru
docker compose exec workbench python app/lab1_eviction.py --policy volatile-ttl
```

> **Q1.5(b).** Fill in what you observed: for each policy, were cache writes accepted or refused, and how many of the 200
> idempotency keys survived? Then answer: (i) which policy is right for a **pure cache**, (ii) which is right for the store that
> holds idempotency keys, and (iii) why `volatile-ttl` kept the idempotency keys here, and why you should not rely on that.

**Put the data back.** The `allkeys-lru` run is allowed to evict **any** key, and that includes the leaderboard and the HyperLogLogs
that you loaded in Part B: they were the least recently used keys in the database. (This is the lesson of the experiment, happening to
your own data.) Check, then restore, because `verify.sh` in Part H expects the Part B data to be present:

```bash
docker compose exec redis redis-cli DBSIZE                      # fewer than the 93 keys of Part B, or none of them
docker compose exec workbench python app/lab1_load_redis.py     # loads the leaderboard and the 92 HyperLogLogs again
```

## Part F: The document model: MongoDB (50 minutes)

**F1. Load the customer documents.**

```bash
docker compose exec workbench python app/lab1_load_mongo.py
docker compose exec mongo mongosh pesa
```

At the `mongosh` prompt:

```js
// One customer = ONE document holding everything the home screen needs
db.customers.findOne({_id: "C0007"})

// Some customers have no preferred language: the field is simply ABSENT, not NULL
db.customers.countDocuments({preferred_language: {$exists: false}})
db.customers.countDocuments({marketing_opt_in: {$exists: false}})
db.customers.countDocuments({})
```

**You should see** 320 documents, 132 without `preferred_language` and 204 without `marketing_opt_in`.

Read the document you printed. Notice what is **inside** (accounts, devices, the 5 most recent payments, loyalty points) and what is
**not** (account balances, the full payment history).

> **Q1.6.** Complete the table with **Embed** or **Reference (keep elsewhere)** and one reason each, using the two tests
> *"is it bounded?"* and *"does it change faster than the document is read?"*:
>
> | Data item | Embed in the customer document? | Reason |
> |---|---|---|
> | the customer's 1 to 3 accounts (id, type) | | |
> | the customer's account **balance** | | |
> | the customer's complete payment history (A0007 alone has 2,500 payments) | | |
> | the 5 most recent payments | | |
> | the merchant's **name** inside each recent payment | | |

**F2. Index and `explain()`.** Which customers in Nairobi have the highest verification level?

```js
// Without an index MongoDB must examine every document
db.customers.find({county: "Nairobi", kyc_level: 3}).explain("executionStats").executionStats
```

Look at three fields: `executionStages.stage` (or `winningPlan`), `totalDocsExamined` and `nReturned`.

> **Q1.7  Predict.** Before you create the index, write down `totalDocsExamined` (hint: how many documents are there?) and `nReturned`.
> Then create the index and run the same `explain()`:
>
> ```js
> db.customers.createIndex({county: 1, kyc_level: 1})
> db.customers.find({county: "Nairobi", kyc_level: 3}).explain("executionStats").executionStats
> ```
>
> What changed in `stage`, `totalDocsExamined` and `nReturned`? With 320 documents the time barely changes. State what you would
> expect at 50 million documents, and why a compound index on `{county, kyc_level}` also serves a query on `county` alone but not one on
> `kyc_level` alone.

**F3. An aggregation pipeline** (MongoDB's answer to `GROUP BY`):

```js
db.customers.aggregate([
  {$group: {_id: "$county", customers: {$sum: 1}, points: {$sum: "$loyalty_points"}}},
  {$sort: {points: -1}},
  {$limit: 3}
])
```

**You should see** Mombasa (37 customers, 49,090 points), Nairobi (106, 45,971), Kiambu (44, 19,437).

**F4. A schema validator.** "Schemaless" does not mean "no rules". Ask MongoDB to enforce rules where they matter:

```js
db.runCommand({
  collMod: "customers",
  validator: {$jsonSchema: {
    bsonType: "object",
    required: ["full_name", "phone", "kyc_level"],
    properties: {
      kyc_level: {bsonType: "number", minimum: 1, maximum: 3, description: "verification level 1 to 3"},
      phone:     {bsonType: "string"}
    }
  }},
  validationLevel: "moderate",     // existing documents are not re-checked until they change
  validationAction: "error"        // reject invalid writes (use "warn" to only log them)
})

// This write must now FAIL with "Document failed validation":
db.customers.insertOne({_id: "TEST1", full_name: "Test Person", phone: "+254700000000", kyc_level: 7})
// This one must succeed (and then we remove it):
db.customers.insertOne({_id: "TEST2", full_name: "Test Person", phone: "+254700000001", kyc_level: 2})
db.customers.deleteOne({_id: "TEST2"})
```

**F5. The price of copying data.** The merchant name was *copied* into every recent payment so the screen needs no second lookup.
Merchant `M003` changes its trading name:

```js
db.merchants.findOne({_id: "M003"})        // note the current name
db.merchants.updateOne({_id: "M003"}, {$set: {name: "Mto Wa Mawe Pharmacy and Clinic"}})

// How many customer documents still carry the OLD name?
db.customers.countDocuments({"recent_transactions.merchant_name": "Mto Wa Mawe Pharmacy"})
```

> **Q1.8.** (a) What number did you get, and what does it tell you about where the name now exists? (b) Fix it with this command, then
> re-run the count:
>
> ```js
> db.customers.updateMany(
>   {"recent_transactions.to_id": "M003"},
>   {$set: {"recent_transactions.$[t].merchant_name": "Mto Wa Mawe Pharmacy and Clinic"}},
>   {arrayFilters: [{"t.to_id": "M003"}]})
> ```
>
> (c) In one paragraph: when is this copy a good bargain, when is it a bad one, and what would you do if merchants changed names daily?

## Part G: Atomicity in a document store (20 minutes)

Moving loyalty points from one customer to another touches **two documents**. A failure between the two writes is dangerous.

```bash
docker compose exec workbench python app/lab1_mongo_txn.py plain --fail    # two separate updates, crash in the middle
docker compose exec workbench python app/lab1_mongo_txn.py txn   --fail    # one transaction, the same crash
docker compose exec workbench python app/lab1_mongo_txn.py txn             # one transaction, no crash
```

> **Q1.9.** (a) What happened to the 100 points in the first run? (b) What happened in the second, and why does the transaction need
> MongoDB to run as a replica set? (c) The document model gives you atomicity for free **inside one document**. Give one Pesa
> operation that needs no transaction because it touches one document, and one that does need one (or a different design).

## Part H: Check your work and write the design memo (30 minutes)

```bash
bash scripts/verify.sh 1
```

Every line should say `PASS` except possibly the two *written work* lines until you have written your answers.

**Design memo** (`my_work/Lab1_design_memo.md`, 150 to 250 words, marked). The Pesa Platform has five requirements:

1. login **session tokens** that expire after 15 minutes;
2. **idempotency keys** for payment requests;
3. the **merchant leaderboard** for the month;
4. the customer **profile** shown on the app's home screen;
5. the account **balance**.

For each one, name the store you would use (Redis, MongoDB or PostgreSQL), give the **access pattern** that justifies it in one
sentence, and state **what you lose and how you recover** if that store loses all of its data. Finish by stating which of the five
must **never** live only in a store that can evict or forget, and why.

## Shutting down

```bash
docker compose --profile lab1 down            # stops the containers, KEEPS the data
bash scripts/reset_lab.sh                     # only if you want to delete everything and start fresh
```

## Troubleshooting
| Symptom | Likely cause | Possible Solution |
|---|---|---|
| `docker compose` says a port is in use | another program uses 5440, 6390 or 27040 | stop it, or change the left-hand port number in `docker-compose.yml` |
| `mongo` never becomes healthy | the replica set is still initialising | wait one minute; then `docker compose logs mongo` |
| Python says `Name or service not known` | you ran the script on your computer instead of in the workbench | prefix the command with `docker compose exec workbench` |
| `credit_safe` check says `NOT YET` | the TODO has not been completed | finish the function, see Part D3 |
| Redis keys vanished | the Redis container restarted with persistence off | run `python app/lab1_load_redis.py` again |
