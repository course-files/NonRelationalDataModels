# Lab 2 — Wide-Column (Cassandra): my answers

> Name: ____________    Student number: ____________    Date: ____________
> Write your own answer under each question (1 to 4 sentences unless the question asks for more).
> For **Predict** questions write your prediction BEFORE you run the command, and add what actually happened.
> Lines that start with ">" or "#" are instructions and are not counted as your writing.

## Q2.1
> **Q2.1 — Predict.** The cluster will soon have a keyspace with replication factor 3 (RF = 3). With three nodes, what **Owns (effective)**
> percentage will `nodetool status pesa` show for each node? What would you expect for RF = 1? Write both predictions, then check
> the first one after Part B.

<!-- write your answer below this line -->

## Q2.2
> **Q2.2 — Predict.** For each query below, write **accepted** or **rejected**, and in one phrase say why. Then run them all in `cqlsh`.
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

<!-- write your answer below this line -->

## Q2.3
> **Q2.3.** (a) `A0007` makes about 27 payments a day. If one payment row is about 100 bytes, how many rows and how many megabytes will
> its **unbucketed** partition hold after 5 years? (b) The usual guidance is to keep a partition under roughly 100 MB. Is `A0007` in
> danger? Be honest: if the answer is "not yet", say what kind of account **would** be, with numbers (for example an aggregator
> account with 50,000 payments a day). (c) `transactions_by_merchant_day` uses the partition key `(merchant_id, day)`. What would happen
> to merchant `M001` if the key were `merchant_id` alone? What does the day bucket cost the **reader**?

<!-- write your answer below this line -->

## Q2.4
> **Q2.4 — Predict.** Complete the table with **ok** or **fail** for a *read* at each CL, before you try. Then run the three
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

<!-- write your answer below this line -->

## Q2.5
> **Q2.5.** (a) Why did the write at `QUORUM` succeed while `cass3` was down, and what did the client *not* learn about `cass3`?
> (b) In one sentence each, what do hints do and what does repair do, and why can hints **not** replace repair? (c) Repair must also run
> regularly on a healthy cluster (at least once every `gc_grace_seconds`, ten days by default) for a reason connected to **deletes**.
> Explain in two or three sentences what could go wrong with a deleted row if repair is skipped. (Hint: a delete is a write too.)

<!-- write your answer below this line -->

## Q2.6
> **Q2.6.** (a) How many network round trips between replicas does the conditional insert need compared with the plain one, and
> what do you conclude about using LWT on a hot path? (b) Redis `NX` is a single atomic command on a single node. What did Cassandra
> have to add (hint: the replicas must *agree*) to give the same guarantee across three nodes? (c) In the Lab 4 capstone the idempotency
> decision is made in PostgreSQL. Give one reason that is better than either Redis or Cassandra for this job.

<!-- write your answer below this line -->

