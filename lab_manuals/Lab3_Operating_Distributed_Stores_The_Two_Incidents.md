# Lab 3: Operating Distributed Stores: The Two Incidents

**Course:** Non-Relational Data Models (Module 4) · **Scenario:** the Pesa Platform
**Time:** about 4.5 hours (live-cluster track); about 3 hours (simulator track)
**Memory needed:** Part A live track about 8 GB (up to five Cassandra nodes at once); Part B about 1.5 GB
**Written work to hand in:** `my_work/Lab3_answers.md`, `my_work/Lab3_runbook.md` (**assessed**), `my_work/Lab3_pipeline_design.md` (**assessed**)

> **Memory warning.** Part A on the live track runs up to five Cassandra nodes together. Set Docker's memory limit to **at least
> 11 GB**. If your computer cannot do this, use the **simulator track** (marked in each step). It teaches the same ideas, and it is a
> legitimate way to complete the lab. You will not lose marks for choosing it.

---

## 0. Why this lab exists

Labs 1 and 2 taught you how the systems **work**. Real organizations lose data and availability not because they misunderstood
CQL, but because of **operations**: adding capacity, absorbing a failure, protecting a shared path. This lab replays two real
incidents, each from a company that knew exactly what it was doing.

* **Incident A (Monzo, 2019):** during a scale-up of a Cassandra cluster, new nodes joined **without receiving any data**. Reads at
  `QUORUM` began returning "not found" for payments that existed.
* **Incident B (Stackdriver, 2013):** a failing database behind a shared message path filled a shared buffer, which blocked the
  gateway, which blinded alerting, so the monitoring service could not see the outage of its own storage.

By the end you will be able to:

1. Reproduce a **masked failure** and explain why the healthy-looking moment is the dangerous one.
2. Predict, with arithmetic, how many reads a given topology can lose, and explain why the prediction is an **upper bound**.
3. Recover from the Monzo failure, and state why recovery worked.
4. Write a **runbook** for adding a node that a tired engineer at 02:00 cannot get wrong.
5. Use queueing arithmetic (`buffer / (arrival rate - service rate)`) to predict when a buffer fills.
6. Compare three buffer designs on loss, availability and cost, and design a **failure-isolated** pipeline.

## 1. Conventions

Same as Labs 1 and 2. Each **Q** is answered in `my_work/Lab3_answers.md`; **Predict** means write before you run. The two assessed
documents have their own sections at the end of each part.

## Part A: The Monzo replay: nodes that own data they do not hold (about 2.5 hours)

### A0. The mechanism in four sentences

A Cassandra node chooses its place on the hash ring and then, by default, **streams** the data for that place from the nodes that
used to own it (this is called *bootstrap*). With the setting `auto_bootstrap: false` the node skips the streaming and **starts
serving reads at once, empty**. Seed nodes also skip bootstrap, which is why new nodes must never be seeds. At `QUORUM` with
RF = 3, a read needs two replicas to answer; if both happen to be empty nodes, the answer is a clean, successful "no such row".

> **Choose your track now.**
> **Live track:** follow every step with the commands marked **[live]**.
> **Simulator track:** skip the `docker compose` commands and use only the commands marked **[sim]**; they run the same
> arithmetic on a model ring that needs no Cassandra. Everywhere a step says "observe in the cluster", the simulator track instead
> reads the matching line of the simulator's report.

### A1. Start the cluster and load the data [live]

```bash
docker compose --profile lab3a up -d --build
docker compose exec workbench python app/lab3_wallets.py load
docker compose exec workbench python app/lab3_wallets.py check --cl QUORUM
```

**What is happening:** three nodes start (the same ones as Lab 2; if Lab 2 is still running, nothing restarts). The loader creates the
keyspace `monzo_lab` (RF = 3), a table `wallets`, and **3,000 wallets**, each written at consistency `ALL`, so all three nodes hold all
3,000. The balance of wallet *n* is a fixed function of *n*, so the checker can tell a **missing** row from a **wrong** row.

**You should see:** `wallets written at consistency ALL: 3000 ok, 0 failed` and `pass 1: CL=QUORUM  found=3000  NOT FOUND=0  wrong=0  errors=0`.

### A2. Predict before you break anything [sim or live]

You are about to add **two empty nodes** (`cass4`, `cass5`) to the 3-node cluster, making five nodes with RF = 3. Use the model:

```bash
docker compose exec workbench python app/ring_sim.py hyper --nodes 5 --empty 2 --rf 3
docker compose exec workbench python app/ring_sim.py demo  --nodes 5 --empty 2 --rf 3 --seed 7
```

The first command gives the closed-form chance that a key has 0, 1 or 2 empty replicas, assuming replicas are 3 random distinct
nodes. The second builds a model ring with 16 virtual nodes per node and counts for 3,000 keys.

> **Q3.1: Predict.** (a) What fraction of keys will have **at least two** empty replicas (the keys "at risk" at `QUORUM`)?
> (b) A read fails only if the **two replicas the coordinator contacts** are both empty. If the coordinator picks two of the three
> replicas at random, what fraction of reads would you expect to fail? Show the arithmetic. (c) Write your predicted
> `NOT FOUND` count out of 3,000. You will compare it with the real number in step A5.

### A3. Stage 1: one empty node joins [live]

```bash
# auto_bootstrap=false is the DEFAULT for cass4 in this lab: this is the dangerous configuration, on purpose
docker compose --profile joiners up -d cass4
docker compose exec cass1 nodetool status monzo_lab        # wait until cass4 shows UN
```

Notice what you do **not** see: no `UJ` ("Up, Joining") state, no streaming, and a tiny `Load` for `cass4`. The node declared itself
a full member immediately.

Now observe the node from two different angles. **Run them in this order** (the second one changes the system, as you will see):

```bash
# (1) Ask cass4 ALONE, at consistency ONE: what can this node serve by itself?
docker compose exec workbench python app/lab3_wallets.py check --cl ONE --via cass4
# (2) The check an operator would normally run: a QUORUM read through any node
docker compose exec workbench python app/lab3_wallets.py check --cl QUORUM
```

**You should see:** (1) a large `NOT FOUND` count (roughly three quarters of the keys are replicated on `cass4`, and it holds none of
them; the exact number varies). (2) `NOT FOUND=0`.

> **Q3.2.** (a) Why does the `QUORUM` check pass while `cass4` is serving nothing? Argue from the number of empty replicas a key can
> have at this stage. (b) The Monzo cluster looked healthy in this state: `nodetool status` showed every node `UN`. Name **two other
> signals** an engineer could have checked that would have exposed the problem at this stage. (c) Why is this stage more dangerous
> than the next one, even though no read is failing?

### A4. Stage 2: a second empty node joins [live]

```bash
docker compose --profile joiners up -d cass5
docker compose exec cass1 nodetool status monzo_lab        # wait for UN on all five nodes
docker compose exec workbench python app/ring_sim.py cluster --nodes cass1,cass2,cass3,cass4,cass5 --empty cass4,cass5 --keys 3000
docker compose exec workbench python app/lab3_wallets.py check --cl QUORUM --passes 3
```

The `ring_sim.py cluster` command reads the **real tokens** from the live cluster, replays Cassandra's replica-placement rule, checks
itself against the driver's own answer, and lists the keys that have two empty replicas.

**You should see:** the simulator report a number of **at risk** keys; the checker report `NOT FOUND` for pass 1 and (usually) a
smaller number for passes 2 and 3.

> **Q3.3.** (a) Compare the real `NOT FOUND` of pass 1 with your prediction in Q3.1 and with the simulator's "AT RISK" figure. Is the
> measured value above or below the at-risk figure, and **why must it be below or equal**? (b) Passes 2 and 3 usually show fewer misses.
> Explain this using what a `QUORUM` read does when the two replicas it contacts **disagree** (one has the row, one does not).
> (c) In step A3 you ran the `--via cass4` check **before** the `QUORUM` check. What would have happened to the Stage 1 evidence
> if you had run them the other way round?

[sim] **Simulator track:** use `ring_sim.py demo --nodes 5 --empty 2 --rf 3 --seed 7` and answer Q3.3 (a) from its report. For (b) and
(c) reason from the description of read repair in the lecture notes (Session 3) and say that you have done so.

### A5. Recovery, the way Monzo did it [live]

> **Do not run `nodetool cleanup` on `cass1`, `cass2` or `cass3` during this section.** Cleanup deletes the data a node holds for
> ranges it no longer owns. With empty nodes owning those ranges, it would remove well-populated copies and leave some keys with a single
> good copy. Q3.4(b) asks you to explain this.

Remove the empty nodes from the ring, newest first. `decommission` tells the node to leave and hand its ranges back; it takes a minute.

```bash
docker compose exec cass5 nodetool decommission
docker compose exec cass4 nodetool decommission
docker compose exec cass1 nodetool status monzo_lab        # three nodes again
docker compose exec workbench python app/lab3_wallets.py check --cl QUORUM --passes 2
docker compose stop cass4 cass5                              # the decommissioned containers are no longer needed
```

**You should see:** `NOT FOUND=0` on both passes.

> **Q3.4.** (a) Nothing was copied back to `cass1` to `cass3`, yet the data "returned". Why? (b) Explain precisely what
> `nodetool cleanup` on `cass1` to `cass3` would have done at the start of this step, and why running `decommission` *afterwards* would
> not have restored the data. (c) The standard alternative to decommission is to run a repair on each new node
> (`nodetool repair -full`). Compare the two: what does each assume about where the correct data is?

### A6. The correct procedure [live]

A normal join streams the data first. Add a sixth node **with** bootstrap (its configuration in `docker-compose.yml` sets
`AUTO_BOOTSTRAP: "true"`):

```bash
docker compose --profile joiners up -d cass6
# in another terminal, watch it: first UJ (joining), then UN
docker compose exec cass1 nodetool status monzo_lab
docker compose exec cass1 nodetool netstats | head -20      # streaming progress while it joins
```

When `cass6` shows `UN`:

```bash
docker compose exec workbench python app/lab3_wallets.py check --cl ONE --via cass6     # the canary: NOT FOUND must be 0
docker compose exec cass1 nodetool cleanup monzo_lab                                    # NOW cleanup is safe, one node at a time
docker compose exec cass2 nodetool cleanup monzo_lab
docker compose exec cass3 nodetool cleanup monzo_lab
docker compose exec workbench python app/lab3_wallets.py check --cl QUORUM
```

**You should see:** `cass6` passes through `UJ`, the `--via cass6` canary reports `NOT FOUND=0`, and the final check reports all 3,000
wallets found.

> **Q3.5.** List **three observable signals**, with the exact command for each, that distinguish a node that bootstrapped correctly
> from one that joined empty. For each signal, say whether an automated check could use it as a *gate* before traffic is shifted to
> the new node.

### A7. Deliverable 1 (assessed): a scale-up runbook

Write `my_work/Lab3_runbook.md` (300 to 500 words). Title it *"Adding a node to the Pesa Cassandra cluster"*. A colleague who has never
done this must be able to follow it at 02:00. It must contain, in order:

1. **Preconditions** (what must be true before you start, and how you check each one).
2. **The configuration** that must be present on the new node and the two settings that must **not** be (name them and say why).
3. **The procedure**, numbered, with the exact commands.
4. **Gates:** the checks that must pass before you move to the next step, each with the expected output. Include a canary read.
5. **Abort criteria** and what to do if a gate fails (including the one thing you must never do).
6. **After the join:** cleanup and verification, and in what order.

Marking is described in the instructor's rubric: correctness of the mechanism, a gate for every dangerous step, and a safe abort.

## Part B: The Stackdriver replay: a shared buffer that took monitoring down (about 1.5 hours)

### B0. The arithmetic first

A sensor fleet sends **λ = 1,000** measurements per second. Three consumers read the same measurements: an **archive** (can do
3,000 per second), **alerting** (2,000 per second) and a **time-series database, tsdb** (1,500 per second). In normal operation the
backlog of each stays near zero because every service rate is above λ.

At t = 5 s the database behind tsdb fails, so the tsdb consumer stops (**μ = 0**). Its backlog now grows at λ − μ = 1,000 per second.
Each buffer holds **5,000** messages.

Time to fill = buffer / (λ − μ) = 5,000 / (1,000 − 0) = **5 seconds**.

> **Q3.6: Predict.** The three designs differ in what happens when the buffer is full. For the **shared-block** design (one stream
> for all consumers, and the gateway refuses new measurements while any consumer's backlog is at the cap): at which second does the
> gateway start refusing, how many seconds does the **alerting** consumer go without new data, and approximately how many of the 40,000
> offered measurements are refused? Then run it.

### B1. Run the three designs [needs only Redis]

```bash
docker compose --profile lab3b up -d --build
docker compose exec workbench python app/lab3_pipeline.py --design shared-block        # about 55 seconds
docker compose exec workbench python app/lab3_pipeline.py --design shared-drop
docker compose exec workbench python app/lab3_pipeline.py --design isolated
```

Each run prints a line every two seconds: for every consumer, the throughput (`/s`), the number done and the **backlog**. The last
column, **alerting blind(s)**, counts the seconds the alerting consumer has gone without new data while traffic is flowing. A summary
follows the run.

**You should see** (your figures will differ slightly):

| Design | accepted | refused | tsdb missing | longest time alerting saw no data |
|---|---|---|---|---|
| shared-block | about 34,900 | about 5,100 | 0 | **about 5 s** |
| shared-drop | 40,000 | 0 | **about 5,000** | about 0.1 s |
| isolated | 40,000 | 0 | **0** (the consumer replays what it missed) | about 0.1 s |

> **Q3.7.** (a) In the **shared-block** run, which component protected itself, and which components paid for it? Why is "alerting
> cannot see" the worst possible side effect for a monitoring product? (b) In the **shared-drop** run nothing is refused and
> alerting is fine, but about 5,000 measurements never reach tsdb. Who is told? Name two signals you would add so that this loss is
> **visible** instead of silent. (c) Which of the two designs is worse for a payments system, and why?

> **Q3.8.** (a) Explain why, in the **isolated** design, the failure of tsdb cannot affect alerting. What is shared and what is not?
> (b) Open `app/lab3_pipeline.py` and find where the consumer detects a gap and replays from `pipe:archive`. Explain in your own words how
> the tsdb consumer knows it missed messages. (c) The archive stream is capped at ten times the normal cap (50,000 messages). How long an
> outage of tsdb can be repaired by replay at λ = 1,000, and what happens beyond that? Predict, then run a **65-second** outage
> (`--design isolated --duration 80 --fail-at 5 --recover-at 70 --drain 60 --every 10`, about 2.5 minutes) and read the `missing`
> figure for tsdb in the summary. (d) **Test a proposed fix:** a
> colleague says the shared design failed only because the buffer was too small. Predict whether `--design shared-block --cap 20000`
> avoids the blocking. Run it. What is the flaw in "just make the buffer bigger"?

### B2. Optional: the same idea in Kafka (not required; 30 minutes)

This is an **optional** exercise for students who want to see the same isolation in a broker built around a log. It uses only Kafka's
command-line tools, which run inside the Kafka container. (It needs about 1 GB of extra memory.)

**Windows (Git Bash) users:** run the following line once in the terminal before the commands below. Without it, Git Bash rewrites `/opt/...` into a Windows path and the commands fail with "no such file or directory".

​```bash
export MSYS_NO_PATHCONV=1
​```

```bash
docker compose --profile kafka up -d
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --topic sensors --partitions 3 --replication-factor 1
seq 1 3000 | docker compose exec -T kafka /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server kafka:9092 --topic sensors
# the "alerting" group reads 1000 messages and stops; the "tsdb" group reads none (it is "down")
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --topic sensors --group alerting --from-beginning --max-messages 1000 > /dev/null
docker compose exec kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka:9092 --describe --group alerting
```

Read the `LAG` column. Then keep producing and watch the producer: it is **never blocked** by the lag of a consumer group. Kafka's
retention settings (`retention.ms`, `retention.bytes`) decide how long a slow group has to catch up before the log is trimmed beneath
it.

> **Q3.9 (optional).** Which line of the `shared-drop` experiment does a Kafka topic with a short retention resemble, and what do
> the independent **offsets per consumer group** correspond to in the Redis-based `isolated` design? Is the choice of broker the
> lesson of Stackdriver, or is it something else?

Stop it with `docker compose --profile kafka down`.

### B3. Deliverable 2 (assessed): a failure-isolated pipeline design

Write `my_work/Lab3_pipeline_design.md` (300 to 500 words, with a diagram of boxes and arrows in text or an image). Design the
sensor pipeline so that **no consumer's failure can degrade another consumer or the producers**. It must state:

1. the components and what each **shares** with the others (ideally nothing but the append-only log);
2. for **each** consumer, its **buffer policy** (block, drop, spill to the archive) and why that policy suits that consumer's purpose;
3. the **numbers**: buffer size, how long an outage it tolerates at λ = 1,000, and what changes at 2 × λ;
4. the **signals** you would put on a dashboard (backlog per consumer, age of the oldest unprocessed message, gaps detected,
   replay volume) and the thresholds that should page a human;
5. what happens when an outage **exceeds** the design limit, and who decides what is sacrificed.

## Part C: Check your work (15 minutes)

```bash
bash scripts/verify.sh 3
```

## Shutting down

```bash
docker compose --profile lab3a --profile lab3b --profile joiners --profile kafka down       # keeps the data
bash scripts/reset_lab.sh                                                                    # deletes everything
```

## If something goes wrong

| Symptom | Likely cause | What to do |
|---|---|---|
| A node is stuck in `UJ` for more than 10 minutes | too little memory, or streaming is slow | `docker compose logs cass6`; raise Docker memory to 11 GB |
| `cass4` or `cass5` shows `DN` after `decommission` | expected: the container is still running but has left the ring | `docker compose stop cass4 cass5` |
| You decommissioned in the wrong order, or a node is stuck `UL` | a decommission was interrupted | `docker compose exec <node> nodetool netstats`; if it is idle, `nodetool decommission --force` on that node |
| Part A is hopelessly confused | an earlier step was skipped | `bash scripts/reset_lab.sh`, then start from A1 (the Cassandra volumes are wiped) |
| `lab3_pipeline.py` shows `0/s` for every consumer from the start | leftover state from an earlier run | `docker compose exec redis redis-cli FLUSHALL` and run again |
| Results differ a little between runs | the harness uses real timers | compare the pattern, not the third digit |
