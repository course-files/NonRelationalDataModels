#!/usr/bin/env python3
"""
setup_capstone.py -- puts the five stores into a known starting state.

What it does (about one minute):
  1. PostgreSQL : removes payments made by earlier capstone runs (ids starting with 'P' or 'D') and puts the
                  balances back; empties the outbox.
  2. Redis      : deletes the stream, its consumer groups and the capstone keys (rate limits, idempotency, chaos).
  3. Cassandra  : creates keyspace pesa_one (ONE node, replication factor 1) and loads the transaction history.
  4. MongoDB    : reloads the customer profile documents (reuses lab1_load_mongo.py).
  5. Neo4j      : reloads the graph (reuses lab4_load_neo4j.py).

Run:  docker compose --profile capstone up -d
      docker compose exec workbench python app/capstone/setup_capstone.py
"""
import datetime as dt

from cassandra.concurrent import execute_concurrent_with_args

import lab1_load_mongo
import lab4_load_neo4j
from capstone.common import CASS_HOST, CASS_KEYSPACE, STREAM, pg, rds
from pesa.cass import connect

DDL = [
    f"""CREATE KEYSPACE IF NOT EXISTS {CASS_KEYSPACE}
        WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}}""",
    f"""CREATE TABLE IF NOT EXISTS {CASS_KEYSPACE}.transactions_by_account (
          account_id text, month text, txn_time timestamp, txn_id text, direction text, to_kind text,
          to_id text, counterparty text, amount_kes bigint, channel text, status text,
          PRIMARY KEY ((account_id, month), txn_time, txn_id)
        ) WITH CLUSTERING ORDER BY (txn_time DESC, txn_id ASC)""",
]


def reset_ledger():
    with pg() as conn, conn.transaction():
        # Undo the money movements of earlier capstone payments, then delete those payments.
        conn.execute("""UPDATE accounts a SET balance_kes = a.balance_kes + s.d FROM (
                           SELECT acct, sum(delta) AS d FROM (
                             SELECT from_account AS acct, amount_kes AS delta FROM transactions
                              WHERE txn_id ~ '^[PD]' AND status = 'SETTLED'
                             UNION ALL
                             SELECT to_id, -amount_kes FROM transactions
                              WHERE txn_id ~ '^[PD]' AND status = 'SETTLED' AND to_kind = 'ACCOUNT') x
                           GROUP BY acct) s WHERE a.account_id = s.acct""")
        conn.execute("DELETE FROM outbox")
        conn.execute("DELETE FROM transactions WHERE txn_id ~ '^[PD]'")
        n = conn.execute("SELECT count(*) FROM transactions").fetchone()[0]
    print(f"ledger reset: {n} historical transactions remain, outbox empty")


def reset_redis():
    r = rds()
    r.delete(STREAM)
    for pattern in ("rl:*", "idem:*", "chaos:*"):
        for k in r.scan_iter(pattern):
            r.delete(k)
    print("redis reset: stream, rate-limit, idempotency and chaos keys removed")


def load_cassandra():
    cluster, session = connect(hosts=[CASS_HOST], cl="ONE")
    for stmt in DDL:
        session.execute(stmt)
    session.execute(f"TRUNCATE {CASS_KEYSPACE}.transactions_by_account")
    rebuild_cassandra_from_ledger(session)
    cluster.shutdown()


def rebuild_cassandra_from_ledger(session):
    """Write every ledger transaction into the statement table (payer row and, for account payees, payee row)."""
    insert = session.prepare(
        f"""INSERT INTO {CASS_KEYSPACE}.transactions_by_account
            (account_id, month, txn_time, txn_id, direction, to_kind, to_id, counterparty, amount_kes, channel, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""")
    rows = []
    with pg() as conn:
        for txn_id, ts, frm, kind, to_id, amount, channel, status in conn.execute(
                "SELECT txn_id, ts, from_account, to_kind, to_id, amount_kes, channel, status FROM transactions"):
            ts = ts.astimezone(dt.timezone.utc).replace(tzinfo=None)      # naive UTC, as the driver expects
            month = ts.strftime("%Y-%m")
            rows.append((frm, month, ts, txn_id, "OUT", kind, to_id, to_id, amount, channel, status))
            if kind == "ACCOUNT":
                rows.append((to_id, month, ts, txn_id, "IN", kind, to_id, frm, amount, channel, status))
    results = execute_concurrent_with_args(session, insert, rows, concurrency=64, raise_on_first_error=False)
    failed = [r for ok, r in results if not ok]
    if failed:
        raise RuntimeError(f"{len(failed)} Cassandra writes failed; first: {failed[0]}")
    print(f"cassandra: {len(rows)} statement rows written from the ledger")


def main():
    reset_ledger()
    reset_redis()
    load_cassandra()
    lab1_load_mongo.main()
    lab4_load_neo4j.main(from_ledger=True)
    print("\ncapstone ready. Next: python app/capstone/gateway.py ... (see the lab manual)")


if __name__ == "__main__":
    main()
