#!/usr/bin/env python3
"""
lab1_cache_aside.py -- the cache-aside pattern, its benefit and its main bug.

Cache-aside ("lazy loading"):
    read : look in Redis; on a MISS read the source of truth, then store a copy in Redis
    write: change the source of truth, then make sure the stale copy cannot be served

Sub-commands
    python app/lab1_cache_aside.py benchmark   latency with and without the cache, for a cheap and an expensive read
    python app/lab1_cache_aside.py stale       shows the stale-read bug when a write forgets the cache
    python app/lab1_cache_aside.py check       tests YOUR fix (see TODO below)

The "source of truth" here is the PostgreSQL ledger.
"""
import json
import random
import sys
import time

import psycopg
import redis

from pesa.config import PG_DSN, REDIS_HOST, REDIS_PORT

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
pg = psycopg.connect(PG_DSN, autocommit=True)

TTL_SECONDS = 30


def key(account_id):
    return f"bal:{account_id}"


# ---------------------------------------------------------------- reads
def balance_from_db(account_id):
    row = pg.execute("SELECT balance_kes FROM accounts WHERE account_id = %s", (account_id,)).fetchone()
    return None if row is None else int(row[0])


def balance_cached(account_id):
    """READ PATH (cache-aside)."""
    cached = r.get(key(account_id))
    if cached is not None:                       # HIT
        return int(cached), "hit"
    value = balance_from_db(account_id)          # MISS: go to the source of truth
    if value is not None:
        r.set(key(account_id), value, ex=TTL_SECONDS)
    return value, "miss"


def summary_key(account_id):
    return f"sum:{account_id}"


def summary_from_db(account_id):
    """An EXPENSIVE read: one row per month, aggregated over the whole history of an account."""
    rows = pg.execute(
        """SELECT to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM') AS month, count(*), sum(amount_kes)
             FROM transactions
            WHERE from_account = %s AND status = 'SETTLED'
            GROUP BY 1 ORDER BY 1""", (account_id,)).fetchall()
    return json.dumps([[m, int(c), int(s)] for m, c, s in rows])


def summary_cached(account_id):
    cached = r.get(summary_key(account_id))
    if cached is not None:
        return cached, "hit"
    value = summary_from_db(account_id)
    r.set(summary_key(account_id), value, ex=TTL_SECONDS)
    return value, "miss"


# --------------------------------------------------------------- writes
def credit_naive(account_id, amount):
    """WRITE PATH with the classic bug: it updates the database and forgets the cache."""
    pg.execute("UPDATE accounts SET balance_kes = balance_kes + %s WHERE account_id = %s", (amount, account_id))


def credit_safe(account_id, amount):
    """WRITE PATH that must not leave a stale value in Redis.

    TODO(student): complete this function.
      1. update the database exactly as credit_naive does;
      2. then remove the cached copy so the next read reloads the fresh value.
    Hint: one Redis command is enough (look at what key() returns).
    """
    raise NotImplementedError("Complete credit_safe() first - see the TODO in the docstring")


# ----------------------------------------------------------- experiments
def benchmark(n_reads=3000):
    rng = random.Random(1)
    rows = pg.execute("""SELECT a.account_id, count(t.txn_id)
                           FROM accounts a LEFT JOIN transactions t ON t.from_account = a.account_id
                          GROUP BY a.account_id ORDER BY a.account_id""").fetchall()
    ids = [x[0] for x in rows]
    # Realistic access pattern: busy accounts are read much more often than quiet ones.
    sample = rng.choices(ids, weights=[x[1] + 1 for x in rows], k=n_reads)

    def timed(label, direct_fn, cached_fn, drop_keys):
        for a in set(sample):
            r.delete(drop_keys(a))
        t0 = time.perf_counter()
        for a in sample:
            direct_fn(a)
        direct_ms = (time.perf_counter() - t0) * 1000 / n_reads
        hits = 0
        t0 = time.perf_counter()
        for a in sample:
            _, how = cached_fn(a)
            hits += how == "hit"
        cached_ms = (time.perf_counter() - t0) * 1000 / n_reads
        print(f"{label:<34} database only {direct_ms:7.3f} ms | with cache {cached_ms:7.3f} ms "
              f"| hit rate {100 * hits / n_reads:5.1f}%")

    print(f"{n_reads} reads, busy accounts read more often")
    timed("balance (primary-key lookup)", balance_from_db, balance_cached, key)
    timed("monthly summary (aggregation)", summary_from_db, summary_cached, summary_key)


def stale_demo():
    acct = "A0001"
    r.delete(key(acct))
    before, _ = balance_cached(acct)                  # loads the cache
    credit_naive(acct, 1000)                          # money arrives; cache is not touched
    db_now = balance_from_db(acct)
    cached_now, how = balance_cached(acct)
    print(f"balance before credit           : {before}")
    print(f"database after credit of 1000   : {db_now}")
    print(f"balance served by the cache ({how}) : {cached_now}   <-- stale for up to {TTL_SECONDS} s")
    print(f"remaining TTL of the cached copy: {r.ttl(key(acct))} s")
    pg.execute("UPDATE accounts SET balance_kes = balance_kes - 1000 WHERE account_id = %s", (acct,))  # undo
    r.delete(key(acct))


def check():
    acct = "A0002"
    r.delete(key(acct))
    balance_cached(acct)                              # warm the cache
    try:
        credit_safe(acct, 500)
    except NotImplementedError as e:
        print("NOT YET: ", e)
        sys.exit(1)
    value, how = balance_cached(acct)
    truth = balance_from_db(acct)
    pg.execute("UPDATE accounts SET balance_kes = balance_kes - 500 WHERE account_id = %s", (acct,))  # undo
    r.delete(key(acct))
    if value == truth:
        print(f"PASS: after the write the next read returned the new balance ({value}).")
    else:
        print(f"FAIL: cache served {value} but the database holds {truth}.")
        sys.exit(1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "benchmark"
    {"benchmark": benchmark, "stale": stale_demo, "check": check}[cmd]()
