#!/usr/bin/env python3
"""
consumers.py -- one CONSUMER GROUP per derived store: Cassandra, MongoDB, Neo4j.

How a Redis Stream consumer group works (the five commands you need)
-------------------------------------------------------------------
  XGROUP CREATE  creates a group: a named position in the stream plus a list of unacknowledged messages
  XREADGROUP     "give me new messages for my group"; each message goes to ONE consumer of the group
                 and is remembered in the group's PENDING list until acknowledged
  XACK           "I have finished with this message"; it leaves the pending list
  XAUTOCLAIM     "give me messages that have been pending for too long" (the retry mechanism)
  XPENDING       "what has been delivered but not acknowledged?"
Each group keeps its OWN position, so the three stores progress independently. A slow or broken
Neo4j does not delay Cassandra or MongoDB. That is the failure isolation you studied in Lab 3 Part B.

The rule that makes this safe: IDEMPOTENT writes
------------------------------------------------
Delivery is at least once: the relay may publish a duplicate, and a retry delivers a message again. Therefore
applying the same event twice must leave the store exactly as applying it once:

  Cassandra  INSERT with the same primary key overwrites the same row                 (an "upsert")
  MongoDB    update only if the payment is not already in the profile ($ne filter)    (a guard in the filter)
  Neo4j      MERGE finds the existing relationship with this txn_id instead of adding a second

A message is acknowledged ONLY after the write succeeded. If the write raises, the message stays pending
and XAUTOCLAIM hands it back after RETRY_AFTER_MS.

Usage:
    python app/capstone/consumers.py --group all --once            # drain the stream into all three stores, then stop
    python app/capstone/consumers.py --group neo4j                  # run one consumer until Ctrl+C
Simulate an outage without stopping a container:   redis-cli SET chaos:neo4j 1      (remove it with DEL)
Simulate a real one:                                docker compose stop neo4j
"""
import argparse
import datetime as dt
import sys
import threading
import time

import redis

from capstone.common import CASS_HOST, CASS_KEYSPACE, GROUPS, STREAM, decode_event, rds

RETRY_AFTER_MS = 2000      # how long a message may stay pending before it is handed out again
BATCH = 50


# ----------------------------------------------------------------------------------------------
# The three sinks. Each has one method, apply(event), which MUST be idempotent.
# ----------------------------------------------------------------------------------------------
class CassandraSink:
    """Writes the payment into the statement table: one row for the payer, one for the payee."""

    def __init__(self):
        from pesa.cass import connect
        self.cluster, self.session = connect(hosts=[CASS_HOST], cl="ONE")     # replication factor 1: ONE is the only choice
        self.insert = self.session.prepare(
            f"""INSERT INTO {CASS_KEYSPACE}.transactions_by_account
                (account_id, month, txn_time, txn_id, direction, to_kind, to_id, counterparty, amount_kes, channel, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""")

    def apply(self, ev):
        ts = dt.datetime.strptime(ev["ts"], "%Y-%m-%dT%H:%M:%SZ")
        month = ts.strftime("%Y-%m")
        # The full primary key is (account_id, month, txn_time, txn_id), so re-running this INSERT rewrites
        # the very same row: nothing new appears, which is what idempotent means.
        self.session.execute(self.insert, (ev["from_account"], month, ts, ev["txn_id"], "OUT", ev["to_kind"], ev["to_id"],
                                           ev["to_id"], ev["amount_kes"], ev["channel"], ev["status"]))
        if ev["to_kind"] == "ACCOUNT":
            self.session.execute(self.insert, (ev["to_id"], month, ts, ev["txn_id"], "IN", ev["to_kind"], ev["to_id"],
                                               ev["from_account"], ev["amount_kes"], ev["channel"], ev["status"]))


class MongoSink:
    """Adds the payment to the payer's profile document (5 newest payments) and awards loyalty points."""

    def __init__(self):
        from pymongo import MongoClient
        from pesa.config import MONGO_URI
        self.customers = MongoClient(MONGO_URI)["pesa"]["customers"]

    def apply(self, ev):
        ts = dt.datetime.strptime(ev["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        entry = {"txn_id": ev["txn_id"], "ts": ts, "from_account": ev["from_account"], "to_kind": ev["to_kind"],
                 "to_id": ev["to_id"], "amount_kes": ev["amount_kes"], "status": ev["status"]}
        if ev.get("merchant_name"):
            entry["merchant_name"] = ev["merchant_name"]
        # ONE atomic update on ONE document. The filter says "only if this payment is not already listed",
        # so a second delivery matches nothing and changes nothing (the points are not awarded twice).
        #   $push + $each + $position 0 + $slice 5  = put it first, keep only the 5 newest
        # Limit of this guard (discuss in the lab): once a payment has been pushed out of the 5-item list, a
        # very late duplicate would no longer be recognised. A production design keeps a processed-event id elsewhere.
        self.customers.update_one(
            {"_id": ev["from_customer"], "recent_transactions.txn_id": {"$ne": ev["txn_id"]}},
            {"$push": {"recent_transactions": {"$each": [entry], "$position": 0, "$slice": 5}},
             "$inc": {"loyalty_points": ev["amount_kes"] // 100}})


class Neo4jSink:
    """Adds one relationship per payment: (:Account)-[:SENT]->(:Account) or (:Account)-[:PAID]->(:Merchant)."""

    def __init__(self):
        from neo4j import GraphDatabase
        from pesa.config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    def apply(self, ev):
        rel, label = ("SENT", "Account") if ev["to_kind"] == "ACCOUNT" else ("PAID", "Merchant")
        # MERGE = "find it, otherwise create it". Matching on the txn_id property makes a repeat harmless.
        # A missing node would make MATCH return no rows and the event would be lost silently, so we
        # RETURN something and treat "no row" as a failure: the message then stays pending.
        query = f"""
            MATCH (a:Account {{id: $frm}}), (b:{label} {{id: $to}})
            MERGE (a)-[r:{rel} {{txn_id: $txn}}]->(b)
              ON CREATE SET r.amount = $amount, r.ts = datetime($ts), r.channel = $channel
            RETURN r.txn_id AS txn"""
        with self.driver.session() as s:
            rec = s.run(query, frm=ev["from_account"], to=ev["to_id"], txn=ev["txn_id"], amount=ev["amount_kes"],
                        ts=ev["ts"], channel=ev["channel"]).single()
        if rec is None:
            raise RuntimeError(f"graph has no node for {ev['from_account']} or {ev['to_id']}")


SINK_FACTORIES = {"cassandra": CassandraSink, "mongo": MongoSink, "neo4j": Neo4jSink}


# ----------------------------------------------------------------------------------------------
# The generic consumer loop (the same for every store)
# ----------------------------------------------------------------------------------------------
def ensure_group(r, group):
    try:
        # id="0": a NEW group starts from the beginning of the stream, so it also receives past events.
        r.xgroup_create(STREAM, group, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):          # BUSYGROUP = the group already exists, which is fine
            raise


def handle(r, group, sink, entries, log):
    """Apply each message; acknowledge only the ones that succeeded. Returns (ok, failed, first_error)."""
    ok = failed = 0
    first_error = None
    for msg_id, fields in entries:
        try:
            if r.exists(f"chaos:{group}"):
                raise RuntimeError("simulated outage (chaos key is set)")
            sink.apply(decode_event(fields))
            r.xack(STREAM, group, msg_id)
            ok += 1
        except Exception as e:                  # noqa: BLE001 - any store error: leave the message pending
            failed += 1
            first_error = first_error or f"{type(e).__name__}: {str(e)[:100]}"
    return ok, failed, first_error


def pending_count(r, group):
    return r.xpending(STREAM, group)["pending"]


def run_group(group, consumer, once=False, timeout=60, log=print, sink=None, stop=None):
    r = rds()
    ensure_group(r, group)
    sink = sink or SINK_FACTORIES[group]()
    done = 0
    last_warning = 0.0
    deadline = time.time() + timeout
    while stop is None or not stop.is_set():
        new = r.xreadgroup(group, consumer, {STREAM: ">"}, count=BATCH, block=300) or []
        entries = new[0][1] if new else []
        ok, bad, err = handle(r, group, sink, entries, log)
        # Messages that failed earlier (or belong to a crashed consumer) come back after RETRY_AFTER_MS.
        claimed = r.xautoclaim(STREAM, group, consumer, min_idle_time=RETRY_AFTER_MS, start_id="0-0", count=BATCH)[1]
        ok2, bad2, err2 = handle(r, group, sink, claimed, log)
        done += ok + ok2
        if ok + ok2:
            log(f"[{group}] applied {ok + ok2} event(s) (total {done})")
        if (bad + bad2) and time.time() - last_warning > 5:      # one warning every 5 s, not one per message
            last_warning = time.time()
            log(f"[{group}] {bad + bad2} event(s) could not be applied ({err or err2}); "
                f"{pending_count(r, group)} pending, retrying every {RETRY_AFTER_MS // 1000} s")
        if once and not entries and not claimed and pending_count(r, group) == 0:
            break
        if once and time.time() > deadline:
            log(f"[{group}] gave up after {timeout}s with {pending_count(r, group)} message(s) still pending")
            return done, pending_count(r, group)
        if not entries and not claimed:
            time.sleep(0.2)
    return done, pending_count(r, group)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", choices=list(GROUPS) + ["all"], required=True)
    ap.add_argument("--once", action="store_true", help="stop when the group has caught up")
    ap.add_argument("--timeout", type=int, default=60, help="with --once: give up after this many seconds")
    a = ap.parse_args()
    groups = list(GROUPS) if a.group == "all" else [a.group]
    results = {}

    def work(g):
        results[g] = run_group(g, f"{g}-1", a.once, a.timeout)

    threads = [threading.Thread(target=work, args=(g,), daemon=True) for g in groups]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("stopping")
        sys.exit(0)
    for g, (done, pending) in results.items():
        print(f"{g:10} applied {done:4d}   still pending {pending}")
    sys.exit(1 if any(p for _, p in results.values()) else 0)


if __name__ == "__main__":
    main()
