# Lab 3 — The Two Incidents: my answers

> Name: ____________    Student number: ____________    Date: ____________
> Write your own answer under each question (1 to 4 sentences unless the question asks for more).
> For **Predict** questions write your prediction BEFORE you run the command, and add what actually happened.
> Lines that start with ">" or "#" are instructions and are not counted as your writing.

## Q3.1
> **Q3.1 — Predict.** (a) What fraction of keys will have **at least two** empty replicas (the keys "at risk" at `QUORUM`)?
> (b) A read fails only if the **two replicas the coordinator contacts** are both empty. If the coordinator picks two of the three
> replicas at random, what fraction of reads would you expect to fail? Show the arithmetic. (c) Write your predicted
> `NOT FOUND` count out of 3,000. You will compare it with the real number in step A5.

<!-- write your answer below this line -->

## Q3.2
> **Q3.2.** (a) Why does the `QUORUM` check pass while `cass4` is serving nothing? Argue from the number of empty replicas a key can
> have at this stage. (b) The Monzo cluster looked healthy in this state: `nodetool status` showed every node `UN`. Name **two other
> signals** an engineer could have checked that would have exposed the problem at this stage. (c) Why is this stage more dangerous
> than the next one, even though no read is failing?

<!-- write your answer below this line -->

## Q3.3
> **Q3.3.** (a) Compare the real `NOT FOUND` of pass 1 with your prediction in Q3.1 and with the simulator's "AT RISK" figure. Is the
> measured value above or below the at-risk figure, and **why must it be below or equal**? (b) Passes 2 and 3 usually show fewer misses.
> Explain this using what a `QUORUM` read does when the two replicas it contacts **disagree** (one has the row, one does not).
> (c) In step A3 you ran the `--via cass4` check **before** the `QUORUM` check. What would have happened to the Stage 1 evidence
> if you had run them the other way round?

<!-- write your answer below this line -->

## Q3.4
> **Q3.4.** (a) Nothing was copied back to `cass1` to `cass3`, yet the data "returned". Why? (b) Explain precisely what
> `nodetool cleanup` on `cass1` to `cass3` would have done at the start of this step, and why running `decommission` *afterwards* would
> not have restored the data. (c) The standard alternative to decommission is to run a repair on each new node
> (`nodetool repair -full`). Compare the two: what does each assume about where the correct data is?

<!-- write your answer below this line -->

## Q3.5
> **Q3.5.** List **three observable signals**, with the exact command for each, that distinguish a node that bootstrapped correctly
> from one that joined empty. For each signal, say whether an automated check could use it as a *gate* before traffic is shifted to
> the new node.

<!-- write your answer below this line -->

## Q3.6
> **Q3.6 — Predict.** The three designs differ in what happens when the buffer is full. For the **shared-block** design (one stream
> for all consumers, and the gateway refuses new measurements while any consumer's backlog is at the cap): at which second does the
> gateway start refusing, how many seconds does the **alerting** consumer go without new data, and approximately how many of the 40,000
> offered measurements are refused? Then run it.

<!-- write your answer below this line -->

## Q3.7
> **Q3.7.** (a) In the **shared-block** run, which component protected itself, and which components paid for it? Why is "alerting
> cannot see" the worst possible side effect for a monitoring product? (b) In the **shared-drop** run nothing is refused and
> alerting is fine, but about 5,000 measurements never reach tsdb. Who is told? Name two signals you would add so that this loss is
> **visible** instead of silent. (c) Which of the two designs is worse for a payments system, and why?

<!-- write your answer below this line -->

## Q3.8
> **Q3.8.** (a) Explain why, in the **isolated** design, the failure of tsdb cannot affect alerting. What is shared and what is not?
> (b) Open `app/lab3_pipeline.py` and find where the consumer detects a gap and replays from `pipe:archive`. Explain in your own words how
> the tsdb consumer knows it missed messages. (c) The archive stream is capped at ten times the normal cap (50,000 messages). How long an
> outage of tsdb can be repaired by replay at λ = 1,000, and what happens beyond that? Predict, then run a **65-second** outage
> (`--design isolated --duration 80 --fail-at 5 --recover-at 70 --drain 60 --every 10`, about 2.5 minutes) and read the `missing`
> figure for tsdb in the summary. (d) **Test a proposed fix:** a
> colleague says the shared design failed only because the buffer was too small. Predict whether `--design shared-block --cap 20000`
> avoids the blocking. Run it. What is the flaw in "just make the buffer bigger"?

<!-- write your answer below this line -->

## Q3.9
> **Q3.9 (optional).** Which line of the `shared-drop` experiment does a Kafka topic with a short retention resemble, and what do
> the independent **offsets per consumer group** correspond to in the Redis-based `isolated` design? Is the choice of broker the
> lesson of Stackdriver, or is it something else?

<!-- write your answer below this line -->

