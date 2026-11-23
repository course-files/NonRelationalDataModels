#!/usr/bin/env python3
"""
lab3_wallets.py -- the small data set for the Monzo replay (Lab 3, Part A).

Creates keyspace monzo_lab (replication factor 3) with table wallets and loads
3,000 rows, each written at consistency level ALL so that every replica holds
every row. The 'balance' of wallet n is a fixed function of n, so a reader can
always tell whether it received the CORRECT row.

    python app/lab3_wallets.py load
    python app/lab3_wallets.py check [--cl QUORUM] [--via cass4] [--passes 2]
"""
import argparse
import sys
import time

from cassandra.concurrent import execute_concurrent_with_args

from pesa.cass import CL, connect

N = 3000


def wallet_id(i):
    return f"W{i:05d}"


def balance(i):
    return (i * 37) % 9000 + 100


def load():
    cluster, session = connect(cl="ALL")
    session.execute("""CREATE KEYSPACE IF NOT EXISTS monzo_lab
                       WITH replication = {'class': 'NetworkTopologyStrategy', 'dc1': 3}""")
    session.execute("""CREATE TABLE IF NOT EXISTS monzo_lab.wallets (
                         wallet_id   text PRIMARY KEY,
                         balance_kes bigint)""")
    ins = session.prepare("INSERT INTO monzo_lab.wallets (wallet_id, balance_kes) VALUES (?, ?)")
    rows = [(wallet_id(i), balance(i)) for i in range(1, N + 1)]
    res = execute_concurrent_with_args(session, ins, rows, concurrency=64, raise_on_first_error=False)
    bad = [r for ok, r in res if not ok]
    print(f"wallets written at consistency ALL: {len(rows) - len(bad)} ok, {len(bad)} failed")
    if bad:
        print("first error:", bad[0])
        sys.exit(1)
    cluster.shutdown()


def check(cl, via, passes):
    cluster, session = connect(cl=cl, via=via)
    sel = session.prepare("SELECT balance_kes FROM monzo_lab.wallets WHERE wallet_id = ?")
    for p in range(1, passes + 1):
        t0 = time.time()
        res = execute_concurrent_with_args(session, sel, [(wallet_id(i),) for i in range(1, N + 1)],
                                           concurrency=32, raise_on_first_error=False)
        missing, wrong, errors = [], [], []
        for i, (ok, r) in enumerate(res, start=1):
            if not ok:
                errors.append((wallet_id(i), type(r).__name__))
                continue
            row = r.one()
            if row is None:
                missing.append(wallet_id(i))          # "not found" -- a SUCCESSFUL read that returned nothing
            elif row.balance_kes != balance(i):
                wrong.append(wallet_id(i))
        print(f"pass {p}: CL={cl}{' via ' + via if via else ''}  found={N - len(missing) - len(errors) - len(wrong)}"
              f"  NOT FOUND={len(missing)}  wrong={len(wrong)}  errors={len(errors)}  ({time.time() - t0:.1f}s)")
        if missing:
            print("   examples of NOT FOUND:", ", ".join(missing[:8]))
        if errors:
            print("   examples of errors   :", errors[:3])
    cluster.shutdown()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["load", "check"])
    ap.add_argument("--cl", default="QUORUM", choices=list(CL))
    ap.add_argument("--via", default=None, help="send every request through this one coordinator node")
    ap.add_argument("--passes", type=int, default=1)
    a = ap.parse_args()
    load() if a.cmd == "load" else check(a.cl, a.via, a.passes)
