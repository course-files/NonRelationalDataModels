#!/usr/bin/env python3
"""
relay.py -- the OUTBOX RELAY: moves events from the ledger's outbox table to the Redis Stream.

Why a relay exists
------------------
The gateway must not write to five stores directly. If it did, a crash between two writes would leave the
stores disagreeing, and nothing would ever repair the difference (dualwrite_demo.py shows exactly that).
Instead the gateway writes the payment AND an outbox row in ONE database transaction. This relay then
publishes outbox rows to the stream and marks them published.

Delivery guarantee: AT LEAST ONCE
---------------------------------
The relay does two things that cannot be made atomic: (1) XADD to Redis, (2) mark the row published in PostgreSQL.
If it stops between (1) and (2), the next run publishes the same event again. A duplicate in the stream is
acceptable ONLY because every consumer is idempotent (consumers.py). The alternative, "at most once", would
mean losing events, which is worse for a payments system.

Concurrency: FOR UPDATE SKIP LOCKED
-----------------------------------
Several relays may run at once. Each locks the rows it takes; a second relay SKIPS rows that are locked
instead of waiting, so two relays never publish the same row in the same moment.

Usage:
    python app/capstone/relay.py --once                    # publish everything pending, then stop
    python app/capstone/relay.py                           # keep polling every 0.5 s (Ctrl+C to stop)
    python app/capstone/relay.py --once --simulate-crash   # publish, then DIE before marking rows published
"""
import argparse
import os
import time

from capstone.common import STREAM, encode_event, pg, rds


def publish_batch(r, batch_size=100, simulate_crash=False):
    """Publish one batch of unpublished outbox rows. Returns the number published."""
    with pg() as conn:
        with conn.transaction():
            rows = conn.execute(
                """SELECT id, aggregate_id, event_type, payload FROM outbox
                    WHERE published_at IS NULL ORDER BY id LIMIT %s
                    FOR UPDATE SKIP LOCKED""", (batch_size,)).fetchall()
            if not rows:
                return 0
            for oid, aggregate_id, event_type, payload in rows:
                # MAXLEN ~ keeps the stream from growing without limit (a stream is a log with a cap, not a database).
                fields = encode_event(aggregate_id, event_type, payload)
                fields["outbox_id"] = str(oid)
                r.xadd(STREAM, fields, maxlen=100_000, approximate=True)
            if simulate_crash:
                print(f"SIMULATED CRASH after publishing {len(rows)} event(s) and BEFORE marking them published.")
                os._exit(1)            # no cleanup, no commit: this is what a power cut or kill -9 looks like
            conn.execute("UPDATE outbox SET published_at = now() WHERE id = ANY(%s)", ([row[0] for row in rows],))
            return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--simulate-crash", action="store_true")
    ap.add_argument("--poll", type=float, default=0.5)
    a = ap.parse_args()
    r = rds()
    total = 0
    while True:
        n = publish_batch(r, simulate_crash=a.simulate_crash)
        total += n
        if n:
            print(f"published {n} event(s) (total {total})")
        if a.once and n == 0:
            break
        if n == 0:
            time.sleep(a.poll)
    print(f"relay finished: {total} event(s) published")


if __name__ == "__main__":
    main()
