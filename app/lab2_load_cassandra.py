#!/usr/bin/env python3
"""
lab2_load_cassandra.py -- creates the Pesa keyspace and loads transaction history.

The SAME payment is written to more than one table, because in Cassandra each
table serves exactly one query (query-first design):

  transactions_by_account        "show this account's payments for a month"
        partition key (account_id, month) -- the month is a TIME BUCKET that keeps
        partitions from growing forever
  transactions_by_merchant_day   "show a merchant's payments for a day"
        partition key (merchant_id, day)
  transactions_by_account_nobucket   an INTENTIONALLY BAD design used in Part D:
        partition key (account_id) only, so one account's partition grows without limit
        (only the busy account A0007 is loaded into it)

Run:  docker compose exec workbench python app/lab2_load_cassandra.py
"""
import datetime as dt
import sys

from cassandra.concurrent import execute_concurrent_with_args

from pesa.cass import connect
from pesa.data import read_csv

DDL = [
    """CREATE KEYSPACE IF NOT EXISTS pesa
       WITH replication = {'class': 'NetworkTopologyStrategy', 'dc1': 3}""",

    """CREATE TABLE IF NOT EXISTS pesa.transactions_by_account (
         account_id  text,
         month       text,          -- time bucket, e.g. '2026-09'
         txn_time    timestamp,
         txn_id      text,
         direction   text,          -- 'OUT' (this account paid) or 'IN' (this account was paid)
         to_kind     text,
         to_id       text,
         counterparty text,         -- the other side: merchant id or account id
         amount_kes  bigint,
         channel     text,
         status      text,
         PRIMARY KEY ((account_id, month), txn_time, txn_id)
       ) WITH CLUSTERING ORDER BY (txn_time DESC, txn_id ASC)""",

    """CREATE TABLE IF NOT EXISTS pesa.transactions_by_merchant_day (
         merchant_id  text,
         day          date,
         txn_time     timestamp,
         txn_id       text,
         from_account text,
         amount_kes   bigint,
         status       text,
         PRIMARY KEY ((merchant_id, day), txn_time, txn_id)
       ) WITH CLUSTERING ORDER BY (txn_time DESC, txn_id ASC)""",

    """CREATE TABLE IF NOT EXISTS pesa.transactions_by_account_nobucket (
         account_id  text,
         txn_time    timestamp,
         txn_id      text,
         amount_kes  bigint,
         status      text,
         PRIMARY KEY (account_id, txn_time, txn_id)
       ) WITH CLUSTERING ORDER BY (txn_time DESC, txn_id ASC)""",

    """CREATE TABLE IF NOT EXISTS pesa.idempotency_keys (
         idem_key   text PRIMARY KEY,
         txn_id     text,
         created_at timestamp
       )""",
]


def parse_ts(s):
    # 2026-09-14T02:10:00Z -> a naive datetime holding UTC (the driver treats naive values as UTC)
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def main():
    cluster, session = connect(cl="QUORUM")
    for stmt in DDL:
        session.execute(stmt)
    print("keyspace and tables created")

    ins_acct = session.prepare(
        """INSERT INTO pesa.transactions_by_account
           (account_id, month, txn_time, txn_id, direction, to_kind, to_id, counterparty, amount_kes, channel, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""")
    ins_merch = session.prepare(
        """INSERT INTO pesa.transactions_by_merchant_day
           (merchant_id, day, txn_time, txn_id, from_account, amount_kes, status)
           VALUES (?, ?, ?, ?, ?, ?, ?)""")
    ins_nobucket = session.prepare(
        """INSERT INTO pesa.transactions_by_account_nobucket
           (account_id, txn_time, txn_id, amount_kes, status) VALUES (?, ?, ?, ?, ?)""")

    acct_rows, merch_rows, nobucket_rows = [], [], []
    for t in read_csv("transactions.csv"):
        ts = parse_ts(t["ts"])
        month = ts.strftime("%Y-%m")
        amount = int(t["amount_kes"])
        # the payer's view
        acct_rows.append((t["from_account"], month, ts, t["txn_id"], "OUT", t["to_kind"], t["to_id"],
                          t["to_id"], amount, t["channel"], t["status"]))
        if t["to_kind"] == "ACCOUNT":
            # the receiver's view (a second copy of the same payment)
            acct_rows.append((t["to_id"], month, ts, t["txn_id"], "IN", t["to_kind"], t["to_id"],
                              t["from_account"], amount, t["channel"], t["status"]))
        else:
            merch_rows.append((t["to_id"], ts.date(), ts, t["txn_id"], t["from_account"], amount, t["status"]))
        if t["from_account"] == "A0007":
            nobucket_rows.append((t["from_account"], ts, t["txn_id"], amount, t["status"]))

    for label, stmt, rows in (("transactions_by_account", ins_acct, acct_rows),
                              ("transactions_by_merchant_day", ins_merch, merch_rows),
                              ("transactions_by_account_nobucket", ins_nobucket, nobucket_rows)):
        results = execute_concurrent_with_args(session, stmt, rows, concurrency=64, raise_on_first_error=False)
        failed = [r for ok, r in results if not ok]
        print(f"{label:<34} {len(rows) - len(failed):6d} rows written, {len(failed)} failed")
        if failed:
            print("first error:", failed[0])
            sys.exit(1)
    cluster.shutdown()


if __name__ == "__main__":
    main()
