# Lab 1 — Key-Value and Document Models: my answers

> Name: ____________    Student number: ____________    Date: ____________
> Write your own answer under each question (1 to 4 sentences unless the question asks for more).
> For **Predict** questions write your prediction BEFORE you run the command, and add what actually happened.
> Lines that start with ">" or "#" are instructions and are not counted as your writing.

## Q1.1
> **Q1.1 — Predict.** You now run `SET session:abc123 "A0002"` (a plain `SET`, nothing else) and then `TTL session:abc123`.
> What number do you expect, and what would that mean for a real login system? Write your prediction, then run it.
> How would you change the command so the session still expires?

<!-- write your answer below this line -->

## Q1.2
> **Q1.2 — Predict, then measure.** (a) The HyperLogLog is an *estimate*. Before you check, say how large an error you expect on a
> day with about 70 devices. (b) Now ask PostgreSQL for the exact answer:
>
> ```sql
> SELECT count(DISTINCT device_id) FROM transactions
>  WHERE (ts AT TIME ZONE 'UTC')::date = '2026-09-14' AND status = 'SETTLED' AND device_id IS NOT NULL;
> ```
>
> Compare. (c) Name one question about devices that a HyperLogLog **cannot** answer, and one reason you would not use it for money.

<!-- write your answer below this line -->

## Q1.3
> **Q1.3.** (a) Explain in two sentences why 50 requests passed the naive check, and why exactly one passes `SET ... NX`.
> (b) The idempotency key is stored with `EX 60` (it expires). What goes wrong if there is **no** expiry, and what goes wrong if the
> expiry is **shorter than the longest time a client might retry**? Suggest a sensible expiry for a payments API and justify it.
> (c) Redis is fast but is not the ledger. If this key is lost (Redis restarts), can a payment be taken twice? What in the
> *capstone* design (Lab 4) prevents that?

<!-- write your answer below this line -->

## Q1.4(a)
> **Q1.4(a).** Why does the cache help one read and not the other? What property of a read makes it a good cache candidate?
> (Think about what the database must do, and how often the answer changes.)

<!-- write your answer below this line -->

## Q1.4(b)
> **Q1.4(b) — Challenge.** Your fix deletes the cached key after the database write. Describe **one precise interleaving** of
> a reader and a writer in which a stale value can still end up in the cache. (Hint: the reader's miss, the reader's database
> read and the reader's `SET` are three separate steps.) What finally limits the damage?

<!-- write your answer below this line -->

## Q1.5(a)
> **Q1.5(a) — Predict.** You run `docker compose restart redis` and then `DBSIZE` again. What number do you expect? Write it down.

<!-- write your answer below this line -->

## Q1.5(b)
> **Q1.5(b).** Fill in what you observed: for each policy, were cache writes accepted or refused, and how many of the 200
> idempotency keys survived? Then answer: (i) which policy is right for a **pure cache**, (ii) which is right for the store that
> holds idempotency keys, and (iii) why `volatile-ttl` kept the idempotency keys here, and why you should not rely on that.

<!-- write your answer below this line -->

## Q1.6
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

<!-- write your answer below this line -->

## Q1.7
> **Q1.7 — Predict.** Before you create the index, write down `totalDocsExamined` (hint: how many documents are there?) and `nReturned`.
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

<!-- write your answer below this line -->

## Q1.8
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

<!-- write your answer below this line -->

## Q1.9
> **Q1.9.** (a) What happened to the 100 points in the first run? (b) What happened in the second, and why does the transaction need
> MongoDB to run as a replica set? (c) The document model gives you atomicity for free **inside one document**. Give one Pesa
> operation that needs no transaction because it touches one document, and one that does need one (or a different design).

<!-- write your answer below this line -->

