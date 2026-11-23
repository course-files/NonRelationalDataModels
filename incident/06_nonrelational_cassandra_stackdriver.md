# Case 6: A Cassandra Failure Became a System-Wide Backpressure Failure

## Module: Non-relational Databases

## Learning Outcome

By the end of this case, you should be able to:

- **Evaluate** a non-relational database architecture not only in terms of the database technology itself but also in terms of failure isolation, consistency, backpressure, replication, and recovery.

## Case type: Real incident, adapted for teaching

> **Important:** This is a lecturer-created teaching case based on [Google Cloud Observability's](https://cloud.google.com/products/observability) public incident report. It has been paraphrased and reorganized for classroom use.

## Original technical incident report

**Stackdriver's Blog (From Internet Archive):**  
[https://web.archive.org/web/20140817025420/http://www.stackdriver.com/post-mortem-october-23-stackdriver-outage/](https://web.archive.org/web/20140817025420/http://www.stackdriver.com/post-mortem-october-23-stackdriver-outage/)

An indexed copy on **[Postmortem.io](https://postmortem.io)**: [https://postmortem.io/incidents/stackdriver--2013-10-23--post-mortem-october-23-stackdriver-outage/](https://postmortem.io/incidents/stackdriver--2013-10-23--post-mortem-october-23-stackdriver-outage/)

---

## 1. Business context

Stackdriver operated a monitoring platform that collected large volumes of time-series measurements.

The architecture used Cassandra to store time-series data.

The platform also used message queues to distribute incoming measurements to multiple downstream consumers.

A simplified architecture was:

```text
                 Incoming measurements
                         |
                         v
                      Gateway
                         |
                    Message broker
              ___________|____________
             |            |            |
             v            v            v
         Archiving    Cassandra      Alerting
                          |
                   Time-series data
```

The architectural intention was that these pipelines should be relatively independent.

That assumption was tested during the incident.

---

## 2. Cassandra configuration

The Cassandra cluster:

- consisted of 36 nodes;
- spanned three availability zones;
- used three-way replication;
- used relatively low consistency levels for writes and reads.

The design was intended to tolerate individual node failures.

However, the incident involved a much larger failure.

---

## 3. The database failure

Several Cassandra nodes had been experiencing memory leaks for days.

Eventually, many nodes exhausted available memory at approximately the same time.

The Cassandra cluster became severely degraded.

Write latency increased.

Writes eventually stopped.

The message queue feeding Cassandra began to grow.

So far, the architecture appeared to be behaving as expected:

> Cassandra is unavailable → queue absorbs the temporary failure.

But the failure lasted longer than the buffering strategy could tolerate.

---

## 4. The unexpected cascade

The system used queue backpressure.

When a queue became too congested, the gateway began spilling messages to disk rather than allowing the queue to grow without limit.

The mechanism was designed to protect the system from overload.

However, the implementation caused messages intended for **other healthy consumers** to stop flowing.

As a result:

- Cassandra was unhealthy;
- the archiving pipeline was still capable of operating;
- the alerting pipeline was still capable of operating;
- but both were affected by the Cassandra-related backpressure.

This created a cascading failure.

---

## 5. Recovery

The engineering team eventually separated the healthy pipelines from the failing Cassandra path.

They also built a new Cassandra cluster and restored historical information from archived data.

Importantly, the incident demonstrated that Cassandra was not the only failure.

The larger architectural problem was **coupling between supposedly independent pipelines**.

---

## 6. Why this is an advanced NoSQL case

Avoid the simplistic conclusion:

> "Cassandra failed, therefore Cassandra was the wrong database."

The organisation had reasons for using Cassandra, and the database had previously handled many failure scenarios.

The more important question is:

> **Did the surrounding architecture correctly isolate Cassandra's failure?**

This introduces:

- backpressure;
- queues;
- failure isolation;
- replication;
- eventual recovery;
- data reconstruction;
- distributed workload design.

---

## 7. Questions for class discussion

### A. NoSQL architecture

1. Why is Cassandra suitable for time-series workloads?
2. Why might high write throughput matter?
3. Why use replication?
4. What does a consistency level of 1 imply?
5. What trade-off is being made by accepting weaker consistency?

### B. Failure handling

6. Why use queues between producers and consumers?
7. What is backpressure?
8. When does buffering stop being sufficient?
9. What happens when a downstream consumer is unavailable for a long time?
10. How should a system prevent one consumer from blocking unrelated consumers?

### C. Data durability

11. Why was historical data recoverable?
12. What role did the archive play?
13. Why is keeping an independent copy of source data useful?
14. Does replication eliminate the need for backups?

### D. Architecture

15. Was Cassandra itself the root cause?
16. What was the architectural coupling problem?
17. How could the system have been designed to isolate failures?
18. Would separate queues per consumer solve the problem?
19. What new operational costs would that create?

### E. Consistency and availability

20. What does the choice of low consistency levels tell us about the application's priorities?
21. Would stronger consistency have prevented the incident?
22. Would stronger consistency have solved the backpressure problem?

---

## 8. [OPTIONAL] Extension activity

Redesign the original architecture so that it ensures:

> Failure of the Cassandra pipeline cannot stop alerting and archival.

Submit:

- architecture diagram
- queue strategy
- retry policy
- dead-letter strategy
- data-recovery strategy
- consistency assumptions
