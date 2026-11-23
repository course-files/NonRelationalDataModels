# Case 5: Adding Servers Made Some Data Disappear

## Module: Non-relational Databases

## Learning Outcome

By the end of this case, you should be able to:

- **Explain** why non-relational distributed databases scale differently from conventional relational systems and why data modelling, partitioning, replication, and operational knowledge are critical.

## Case type: Real incident, adapted for teaching

> **Important:** This is a lecturer-created teaching case based on [Monzo's](https://monzo.com/) public incident report. It has been paraphrased and reorganized for classroom use.

## Original technical incident report

**Monzo's Blog:**  
[https://monzo.com/blog/2019/09/08/why-monzo-wasnt-working-on-july-29th](https://monzo.com/blog/2019/09/08/why-monzo-wasnt-working-on-july-29th)

An indexed copy on **[Postmortem.io](https://postmortem.io)**: [https://postmortem.io/incidents/monzo--2019-07-29--cassandra-auto-bootstrap-outage/](https://postmortem.io/incidents/monzo--2019-07-29--cassandra-auto-bootstrap-outage/)

---

## 1. Business context

Monzo operated a highly available distributed banking platform using Apache Cassandra.

The Cassandra cluster consisted of multiple servers, with data replicated across nodes.

The organization used Cassandra because it provided:

- horizontal scalability
- distribution across servers
- high availability
- replication
- high throughput

As customer usage increased, the team needed more capacity.

The planned solution appeared straightforward:

> Add more Cassandra servers.

---

## 2. Existing architecture

The production cluster contained 21 servers.

Data was replicated three ways.

A simplified view is:

```text
                 Cassandra Cluster
        +--------------------------------+
        | N1 N2 N3 N4 ... N19 N20 N21    |
        +--------------------------------+
                    |
             Replication factor = 3
                    |
          Data stored on 3 nodes
```

The system used quorum operations.

For a replicated item:

```text
3 replicas
   |
   +--- Replica A
   +--- Replica B
   +--- Replica C

Quorum = 2
```

The architecture was designed so that the loss of one replica would not necessarily make the data unavailable.

---

## 3. The scaling operation

The team decided to add six servers.

They expected the new servers to join the cluster but remain effectively inactive until data had been streamed to them.

This expectation was wrong.

A Cassandra configuration parameter called `auto_bootstrap` influenced both data streaming and how new nodes participated in the cluster.

The production configuration had been set to a non-default value for operational reasons.

When the six new nodes joined:

- they became responsible for some partitions;
- they did not yet contain the corresponding data;
- some requests were routed to those nodes;
- the application therefore received "not found" results for data that actually existed elsewhere.

The system had effectively changed **data ownership before data availability had caught up**.

---

## 4. Customer impact

The consequences were serious because the database supported financial services.

Some customers experienced:

- difficulty logging in;
- failed payments;
- inability to retrieve some information;
- inaccurate-looking balances or transactions;
- problems with customer-support tooling.

The team initially struggled to reconcile apparently contradictory evidence.

Database metrics showed successful reads and writes.

Yet some specific keys could not be found.

Eventually, the team queried Cassandra directly and identified that some requests were reaching the new nodes.

---

## 5. Recovery

The team removed the newly added nodes.

As ownership returned to the original nodes, the immediate errors declined.

The team then performed reconciliation and replayed externally retained events to ensure that data written during the incident was consistent.

The incident exposed several weaknesses:

- insufficient understanding of a production configuration parameter;
- insufficient scale-up testing;
- a shared Cassandra cluster serving many services;
- insufficient metrics for "unexpectedly missing data";
- operational procedures that did not fully document the semantics of the configuration.

---

## 6. Why this is a non-relational database case

The incident is not simply about Cassandra.

It illustrates why distributed non-relational databases require engineers to understand:

- partitioning;
- replication;
- consistency;
- quorum;
- data ownership;
- node membership;
- rebalancing;
- failure recovery.

A database can be "up" while a particular item is temporarily unavailable because the system's logical ownership and physical data placement are out of alignment.

---

## 7. Questions for class discussion

### A. Why Cassandra?

1. Why might a bank choose Cassandra rather than a traditional relational database for some workloads?
2. What workload characteristics make Cassandra attractive?
3. What trade-offs accompany that choice?
4. What does horizontal scalability mean?

### B. Data modelling

5. Why is data modelling particularly important in Cassandra?
6. What is a partition key?
7. How does a partition key influence data placement?
8. Why is Cassandra not simply "a relational database spread over many machines"?

### C. Replication and consistency

9. What does replication factor 3 mean?
10. What does quorum mean?
11. Why can quorum improve reliability?
12. Does quorum guarantee that every read will always see the latest data?
13. What consistency assumptions should application developers understand?

### D. Scaling

14. Why is adding servers to a distributed database more complicated than adding CPU or RAM to one server?
15. What happens during data rebalancing?
16. What can go wrong if data ownership changes before data has been transferred?
17. What tests should have been performed before the production scale-up?

### E. Architectural design

18. Why might a single Cassandra cluster serving many services increase blast radius?
19. What would be gained by splitting the cluster?
20. What operational costs would that introduce?

---

## 8. [OPTIONAL] Extension activity

Design a safe production scale-up procedure for a Cassandra cluster.

The following is required:

1. pre-flight checks
2. staging test
3. one-node canary
4. monitoring
5. rollback procedure
6. data-consistency checks
7. post-change verification
