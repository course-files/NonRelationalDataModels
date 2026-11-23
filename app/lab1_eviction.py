#!/usr/bin/env python3
"""
lab1_eviction.py -- what Redis does when it runs out of memory, and why the policy matters.

Setup
  * Redis is given a small memory limit (maxmemory = what it uses now + 4 MB).
  * 200 IDEMPOTENCY KEYS are written first (each SET ... NX EX 86400, the pattern from Part C).
  * Then the script keeps adding CACHE entries (about 1 KB each, with a TTL) until it has written 20,000
    of them or the server refuses.
At the end it counts: how many cache entries were accepted, how many keys Redis evicted, and
HOW MANY OF THE 200 IDEMPOTENCY KEYS SURVIVED.

Run one policy at a time:
    python app/lab1_eviction.py --policy noeviction
    python app/lab1_eviction.py --policy allkeys-lru
    python app/lab1_eviction.py --policy volatile-ttl
The script puts the server's settings back when it finishes.

Policies in one line each
    noeviction    never delete anything; refuse writes with an OOM error when full
    allkeys-lru   delete the least recently used key, whatever it is
    volatile-lru  delete the least recently used key AMONG KEYS THAT HAVE A TTL
    volatile-ttl  delete the keys that are closest to expiring first
"""
import argparse

import redis

from pesa.config import REDIS_HOST, REDIS_PORT

N_IDEM = 200
N_CACHE = 20000
PAYLOAD = "x" * 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True,
                    choices=["noeviction", "allkeys-lru", "volatile-lru", "volatile-ttl", "allkeys-random"])
    ap.add_argument("--headroom-mb", type=int, default=4)
    a = ap.parse_args()

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    old_max = r.config_get("maxmemory")["maxmemory"]
    old_policy = r.config_get("maxmemory-policy")["maxmemory-policy"]
    try:
        for k in list(r.scan_iter("evict:*")):
            r.delete(k)
        r.config_resetstat()
        used = r.info("memory")["used_memory"]
        limit = used + a.headroom_mb * 1024 * 1024
        r.config_set("maxmemory-policy", a.policy)
        r.config_set("maxmemory", limit)
        print(f"policy={a.policy}  maxmemory={limit / 1024 / 1024:.1f} MB (in use now: {used / 1024 / 1024:.1f} MB)")

        for i in range(N_IDEM):
            r.set(f"evict:idem:{i}", "done", nx=True, ex=86400)
        written = refused = 0
        first_refusal = None
        for i in range(N_CACHE):
            try:
                r.set(f"evict:cache:{i}", PAYLOAD, ex=3600)
                written += 1
            except redis.exceptions.ResponseError as e:      # "OOM command not allowed when used memory > 'maxmemory'"
                refused += 1
                first_refusal = first_refusal or (i, str(e)[:70])
        surviving = sum(1 for i in range(N_IDEM) if r.exists(f"evict:idem:{i}"))
        evicted = r.info("stats")["evicted_keys"]
        print(f"cache entries accepted : {written}   refused with an error: {refused}")
        if first_refusal:
            print(f"first refusal at entry : {first_refusal[0]}   message: {first_refusal[1]}")
        print(f"keys evicted by Redis  : {evicted}")
        print(f"idempotency keys that survived: {surviving} of {N_IDEM}")
        if surviving < N_IDEM:
            print("  -> a retried payment whose key was evicted would be treated as NEW. Money could move twice.")
    finally:
        for k in list(r.scan_iter("evict:*")):
            r.delete(k)
        r.config_set("maxmemory", old_max)
        r.config_set("maxmemory-policy", old_policy)
        print("(server settings restored)")


if __name__ == "__main__":
    main()
