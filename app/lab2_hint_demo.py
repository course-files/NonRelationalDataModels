#!/usr/bin/env python3
"""
lab2_hint_demo.py -- watch a node fall behind and catch up (Lab 2, Part E).

    python app/lab2_hint_demo.py create
    python app/lab2_hint_demo.py write [--n 500] [--cl QUORUM] [--start 1]
    python app/lab2_hint_demo.py count [--n 500] --via cass3 [--cl ONE]

'write' inserts rows numbered start .. start+n-1.
'count' reads every row number 1..n through ONE chosen coordinator node at consistency ONE, so the answer
shows what THAT node can serve. With replication factor 3 on 3 nodes, every node is a replica of every row,
and a coordinator that is itself a replica normally answers from its own copy.
"""
import argparse
import time

from cassandra.concurrent import execute_concurrent_with_args

from pesa.cass import CL, connect


def create():
    cluster, s = connect(cl="ALL")
    s.execute("""CREATE KEYSPACE IF NOT EXISTS pesa
                 WITH replication = {'class': 'NetworkTopologyStrategy', 'dc1': 3}""")
    s.execute("CREATE TABLE IF NOT EXISTS pesa.hint_demo (id int PRIMARY KEY, v text)")
    s.execute("TRUNCATE pesa.hint_demo")
    print("table pesa.hint_demo is ready and empty")
    cluster.shutdown()


def write(n, cl, start):
    cluster, s = connect(cl=cl)
    ins = s.prepare("INSERT INTO pesa.hint_demo (id, v) VALUES (?, ?)")
    rows = [(i, f"row-{i}") for i in range(start, start + n)]
    res = execute_concurrent_with_args(s, ins, rows, concurrency=32, raise_on_first_error=False)
    bad = [r for ok, r in res if not ok]
    print(f"wrote rows {start}..{start + n - 1} at consistency {cl}: {len(rows) - len(bad)} succeeded, {len(bad)} failed")
    if bad:
        print("first error:", type(bad[0]).__name__, str(bad[0])[:160])
    cluster.shutdown()


def count(n, via, cl):
    cluster, s = connect(cl=cl, via=via)
    sel = s.prepare("SELECT id FROM pesa.hint_demo WHERE id = ?")
    t0 = time.time()
    res = execute_concurrent_with_args(s, sel, [(i,) for i in range(1, n + 1)], concurrency=32, raise_on_first_error=False)
    found = sum(1 for ok, r in res if ok and r.one() is not None)
    errors = sum(1 for ok, _ in res if not ok)
    print(f"rows 1..{n} read at {cl} through {via or 'any node'}: found {found}, missing {n - found - errors}, errors {errors}"
          f"  ({time.time() - t0:.1f}s)")
    cluster.shutdown()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["create", "write", "count"])
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--cl", default=None, choices=list(CL))
    ap.add_argument("--via", default=None)
    a = ap.parse_args()
    if a.cmd == "create":
        create()
    elif a.cmd == "write":
        write(a.n, a.cl or "QUORUM", a.start)
    else:
        count(a.n, a.via, a.cl or "ONE")
