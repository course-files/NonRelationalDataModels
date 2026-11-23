#!/usr/bin/env python3
"""
lab1_race.py -- why "check, then set" is NOT safe, and why SET ... NX is.

Scenario: a mobile app retries a payment request because the network was slow.
The same request (same idempotency key) arrives 50 times at once. Exactly ONE
of those requests may move money.

  naive : GET the key; if it is missing, do some work, then SET it.
  atomic: one command, SET key value NX EX 60  ("set only if not exists").

Run:  docker compose exec workbench python app/lab1_race.py
"""
import threading
import time
import uuid

import redis

from pesa.config import REDIS_HOST, REDIS_PORT

N_CLIENTS = 50


def naive_claim(r, key):
    """Check-then-act. Between the GET and the SET, other clients can do the same."""
    if r.get(key) is None:
        time.sleep(0.05)                 # a little application work (validation, logging ...)
        r.set(key, "processing", ex=60)
        return True                      # "I am the first; I will move the money"
    return False


def atomic_claim(r, key):
    """One atomic command: only the first caller gets True."""
    return bool(r.set(key, "processing", nx=True, ex=60))


def run(label, claim_fn):
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    key = f"idem:race:{label}:{uuid.uuid4().hex[:8]}"
    winners = []
    barrier = threading.Barrier(N_CLIENTS)

    def client(i):
        # each thread gets its own connection, like 50 separate app servers
        rc = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        barrier.wait()                   # release all 50 at the same instant
        if claim_fn(rc, key):
            winners.append(i)

    threads = [threading.Thread(target=client, args=(i,)) for i in range(N_CLIENTS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    r.delete(key)
    print(f"{label:>6}: {len(winners):2d} of {N_CLIENTS} requests believed they were first "
          f"-> money would move {len(winners)} time(s)")
    return len(winners)


if __name__ == "__main__":
    run("naive", naive_claim)
    run("atomic", atomic_claim)
