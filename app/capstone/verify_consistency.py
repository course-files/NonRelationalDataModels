#!/usr/bin/env python3
"""
verify_consistency.py -- does every store agree with the LEDGER about the capstone payments?

For each payment in the ledger whose id starts with P (gateway payments) or D (dual-write demo), the script
asks every other store "do you have it?" and prints a table. It also prints the plumbing state: unpublished
outbox rows, stream length, and per-group pending messages.

Reading the table:
    ok        the store has exactly one copy
    MISSING   the store has not (yet) received this payment
    DUPx2     the store holds the payment more than once (an idempotency failure)
    aged-out  MongoDB keeps only the 5 newest payments per customer; this one has legitimately been pushed out
"MISSING" is normal for a short while (eventual consistency: the relay and consumers have not run yet). It is a
problem only if it PERSISTS after the relay and consumers have run, or if no process will ever deliver it.

Usage:
    python app/capstone/verify_consistency.py
    python app/capstone/verify_consistency.py --prefix D       # only the dual-write demo payments
Exit status: 0 = all stores agree, 1 = at least one payment is missing or duplicated somewhere.
"""
import argparse
import datetime as dt
import sys

from capstone.common import CASS_HOST, CASS_KEYSPACE, GROUPS, STREAM, pg, rds


class RealStores:
    """Read-only access to the three derived stores."""

    def __init__(self):
        from cassandra.query import SimpleStatement  # noqa: F401
        from neo4j import GraphDatabase
        from pymongo import MongoClient
        from pesa.cass import connect
        from pesa.config import MONGO_URI, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER
        self.cluster, self.cass = connect(hosts=[CASS_HOST], cl="ONE")
        self.customers = MongoClient(MONGO_URI)["pesa"]["customers"]
        self.neo = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    def cassandra_has(self, txn_id, ts, from_account, to_kind, to_id):
        t = ts.astimezone(dt.timezone.utc).replace(tzinfo=None)
        q = (f"SELECT txn_id FROM {CASS_KEYSPACE}.transactions_by_account "
             "WHERE account_id = %s AND month = %s AND txn_time = %s AND txn_id = %s")
        month = t.strftime("%Y-%m")
        found = bool(list(self.cass.execute(q, (from_account, month, t, txn_id))))
        if to_kind == "ACCOUNT":
            found = found and bool(list(self.cass.execute(q, (to_id, month, t, txn_id))))
        return found

    def mongo_count(self, txn_id, customer_id):
        """Return (copies of the payment in the profile, number of items in the list, oldest item's time)."""
        doc = self.customers.find_one({"_id": customer_id}, {"recent_transactions": 1}) or {}
        items = doc.get("recent_transactions", [])
        return (sum(1 for t in items if t["txn_id"] == txn_id), len(items),
                min((t["ts"] for t in items), default=None))

    def neo4j_count(self, txn_id):
        with self.neo.session() as s:
            return s.run("MATCH ()-[r {txn_id: $t}]->() RETURN count(r) AS c", t=txn_id).single()["c"]


def ledger_payments(prefix):
    with pg() as conn:
        rows = conn.execute(
            """SELECT txn_id, ts, from_account, to_kind, to_id, amount_kes FROM transactions
                WHERE txn_id LIKE %s AND txn_id ~ '^[PD]' ORDER BY ts, txn_id""", ((prefix or "") + "%",)).fetchall()
        cust = dict(conn.execute("SELECT account_id, customer_id FROM accounts").fetchall())
        unpublished = conn.execute("SELECT count(*) FROM outbox WHERE published_at IS NULL").fetchone()[0]
        outbox_total = conn.execute("SELECT count(*) FROM outbox").fetchone()[0]
    return rows, cust, unpublished, outbox_total


def plumbing(r):
    length = r.xlen(STREAM) if r.exists(STREAM) else 0
    lines = [f"stream {STREAM}: {length} message(s)"]
    for g in GROUPS:
        try:
            pend = r.xpending(STREAM, g)["pending"]
            lines.append(f"  group {g:10} pending (delivered, not acknowledged): {pend}")
        except Exception:                                   # noqa: BLE001 - group not created yet
            lines.append(f"  group {g:10} not created yet (consumers have never run)")
    return lines


def main(stores=None, out=print, argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prefix", default="", help="only payments whose id starts with this letter (P or D)")
    args = ap.parse_args(argv) if stores is None else argparse.Namespace(prefix="")
    stores = stores or RealStores()
    r = rds()

    rows, cust, unpublished, outbox_total = ledger_payments(args.prefix)
    out(f"ledger holds {len(rows)} capstone payment(s); outbox: {unpublished} unpublished of {outbox_total} rows")
    for line in plumbing(r):
        out(line)
    out("")
    out(f"{'txn_id':14} {'amount':>8}  {'ledger':7} {'cassandra':10} {'mongo':9} {'neo4j':7}")
    bad = 0
    for txn_id, ts, frm, kind, to_id, amount in rows:
        c_ok = stores.cassandra_has(txn_id, ts, frm, kind, to_id)
        n, size, oldest = stores.mongo_count(txn_id, cust[frm])
        if n == 1:
            m = "ok"
        elif n > 1:
            m = f"DUPx{n}"
        elif size >= 5 and oldest is not None and ts.astimezone(dt.timezone.utc) <= oldest.replace(tzinfo=dt.timezone.utc):
            m = "aged-out"
        else:
            m = "MISSING"
        g = stores.neo4j_count(txn_id)
        g_s = "ok" if g == 1 else ("MISSING" if g == 0 else f"DUPx{g}")
        c_s = "ok" if c_ok else "MISSING"
        bad += (c_s != "ok") + (m not in ("ok", "aged-out")) + (g_s != "ok")
        out(f"{txn_id:14} {amount:>8}  {'ok':7} {c_s:10} {m:9} {g_s:7}")
    out("")
    out("RESULT: all stores agree with the ledger" if bad == 0 else f"RESULT: {bad} discrepancy(ies) between the ledger and the derived stores")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
