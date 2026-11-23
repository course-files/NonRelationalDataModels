#!/usr/bin/env python3
"""
dualwrite_demo.py -- the ANTI-PATTERN: writing to several stores directly from the request.

This program settles a payment the "obvious" way: write the ledger, then write Cassandra, then MongoDB, then
Neo4j, one after the other, inside the request. Each write is a separate system, so there is no transaction
spanning them. If the process fails part-way (here: simulated with --crash-after), the stores disagree, and
NOTHING remembers that work is left to do: there is no outbox row and no event in a stream. Compare with
gateway.py + relay.py + consumers.py, where a crash at any point is repaired automatically.

The payment ids start with 'D' so that verify_consistency.py --prefix D can inspect them separately.

Usage:
    python app/capstone/dualwrite_demo.py --from A0003 --to-kind ACCOUNT --to A0004 --amount 700 --key d-1
    python app/capstone/dualwrite_demo.py --from A0003 --to-kind ACCOUNT --to A0004 --amount 800 --key d-2 --crash-after cassandra
    python app/capstone/verify_consistency.py --prefix D
Possible --crash-after values: ledger, cassandra, mongo   (the order of the writes is ledger, cassandra, mongo, neo4j)
"""
import argparse
import datetime as dt
import hashlib
import sys
import time

from capstone.common import pg
from capstone.consumers import SINK_FACTORIES


def dual_write(frm, kind, to_id, amount, key, crash_after=None, sinks=None, now=None):
    txn_id = "D" + hashlib.sha1(key.encode()).hexdigest()[:12]
    ts = dt.datetime.fromtimestamp(int(now or time.time()), tz=dt.timezone.utc)
    with pg() as conn, conn.transaction():
        cust = dict(conn.execute("SELECT account_id, customer_id FROM accounts WHERE account_id = ANY(%s)",
                                 ([frm, to_id],)).fetchall())
        name = None
        if kind == "MERCHANT":
            name = conn.execute("SELECT name FROM merchants WHERE merchant_id = %s", (to_id,)).fetchone()[0]
        conn.execute(
            """INSERT INTO transactions (txn_id, ts, from_account, to_kind, to_id, amount_kes, channel, status)
               VALUES (%s, %s, %s, %s, %s, %s, 'app', 'SETTLED') ON CONFLICT (txn_id) DO NOTHING""",
            (txn_id, ts, frm, kind, to_id, amount))
        conn.execute("UPDATE accounts SET balance_kes = balance_kes - %s WHERE account_id = %s", (amount, frm))
        if kind == "ACCOUNT":
            conn.execute("UPDATE accounts SET balance_kes = balance_kes + %s WHERE account_id = %s", (amount, to_id))
    print(f"1. ledger committed {txn_id}")
    ev = {"txn_id": txn_id, "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "from_account": frm, "from_customer": cust[frm],
          "to_kind": kind, "to_id": to_id, "to_customer": cust.get(to_id), "merchant_name": name,
          "amount_kes": amount, "channel": "app", "status": "SETTLED"}
    sinks = sinks or {g: f() for g, f in SINK_FACTORIES.items()}

    def maybe_die(after):
        if crash_after == after:
            print(f"*** the process dies here, right after the {after} write; the remaining writes never happen ***")
            raise SystemExit(3)

    maybe_die("ledger")
    for step, g in enumerate(("cassandra", "mongo", "neo4j"), start=2):
        sinks[g].apply(ev)
        print(f"{step}. {g} written")
        maybe_die(g)
    return txn_id


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="frm", required=True)
    ap.add_argument("--to-kind", choices=["ACCOUNT", "MERCHANT"], required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--amount", type=int, required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--crash-after", choices=["ledger", "cassandra", "mongo"])
    a = ap.parse_args()
    dual_write(a.frm, a.to_kind, a.to, a.amount, a.key, a.crash_after)


if __name__ == "__main__":
    sys.exit(main())
