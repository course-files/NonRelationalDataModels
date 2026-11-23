#!/usr/bin/env python3
"""
lab1_load_redis.py -- fills Redis with two DERIVED views of the ledger.

The ledger (PostgreSQL) is the system of record. Redis never holds the truth;
it holds copies shaped for fast, specific questions:

  1. a SORTED SET  lb:merchant:2026-09   member = merchant id, score = total
     KES paid to that merchant in September 2026 (a leaderboard);
  2. one HYPERLOGLOG per day  uniq:dev:<date>  that estimates how many distinct
     devices made a payment that day, using a few kilobytes instead of a list.

Run:  docker compose exec workbench python app/lab1_load_redis.py
"""
import psycopg
import redis

from pesa.config import PG_DSN, REDIS_HOST, REDIS_PORT


def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    with psycopg.connect(PG_DSN) as conn:
        # --- 1. September merchant leaderboard -> sorted set --------------------
        rows = conn.execute(
            """SELECT to_id, SUM(amount_kes)
                 FROM transactions
                WHERE to_kind = 'MERCHANT' AND status = 'SETTLED'
                  AND ts >= '2026-09-01' AND ts < '2026-10-01'
                GROUP BY to_id"""
        ).fetchall()
        r.delete("lb:merchant:2026-09")
        r.zadd("lb:merchant:2026-09", {mid: int(total) for mid, total in rows})
        print(f"sorted set lb:merchant:2026-09  -> {len(rows)} merchants")

        # --- 2. distinct devices per day -> one HyperLogLog per day -------------
        rows = conn.execute(
            """SELECT (ts AT TIME ZONE 'UTC')::date AS day, device_id
                 FROM transactions
                WHERE device_id IS NOT NULL AND status = 'SETTLED'"""
        ).fetchall()
        days = {}
        for day, dev in rows:
            days.setdefault(day.isoformat(), []).append(dev)
        pipe = r.pipeline()
        for day, devs in days.items():
            key = f"uniq:dev:{day}"
            pipe.delete(key)
            pipe.pfadd(key, *devs)
        pipe.execute()
        print(f"HyperLogLogs uniq:dev:<date>    -> {len(days)} days")


if __name__ == "__main__":
    main()
