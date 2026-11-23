#!/usr/bin/env python3
"""
gateway.py -- the payment gateway: where one payment enters the system.

Order of work for ONE payment request, and WHY each step is where it is:

  1. REDIS rate limit      cheap, approximate, temporary -> a key-value store is ideal
  2. REDIS duplicate check "have I already answered this idempotency key?" -> a fast filter only
  3. POSTGRES transaction  the authoritative part. In ONE ACID transaction:
        a. lock the payer's (and payee's) account rows           SELECT ... FOR UPDATE
        b. check funds
        c. INSERT the payment with a deterministic id            ON CONFLICT DO NOTHING
        d. move the money (debit, credit)
        e. INSERT one OUTBOX row describing the event
     Either all of c, d, e happen or none do. The outbox row is how the other stores will
     eventually hear about the payment (relay.py publishes it). There is NO direct call to
     Cassandra, MongoDB or Neo4j here, on purpose.
  4. REDIS remember the answer for the idempotency key (so the next retry is cheap)

If the process dies between 3 and 4, a retry skips the Redis shortcut, reaches the ledger, collides on
the primary key, and returns the original answer. The LEDGER is the final judge of duplicates; Redis only
makes the common case fast.

Usage (inside the workbench container):
    python app/capstone/gateway.py --from A0001 --to-kind MERCHANT --to M003 --amount 500 --key order-1001
    python app/capstone/gateway.py --from A0001 --to-kind ACCOUNT  --to A0002 --amount 250 --key order-1002
Run the same command twice: the second answer says DUPLICATE and the balance changes only once.
"""
import argparse
import datetime as dt
import json
import sys
import time

from capstone.common import RATE_LIMIT_PER_MINUTE, pg, rds, txn_id_for


class PaymentRefused(Exception):
    """Raised for business refusals: unknown account, insufficient funds, rate limit."""


def pay(from_account, to_kind, to_id, amount, key, channel="app", device_id=None, r=None, now=None):
    """Process one payment request. Returns a dict describing the outcome."""
    r = r or rds()
    now = now or time.time()
    txn_id = txn_id_for(key)
    if amount <= 0:
        raise PaymentRefused("INVALID_AMOUNT")
    if to_kind == "ACCOUNT" and to_id == from_account:
        raise PaymentRefused("INVALID_PAYEE: an account cannot pay itself")

    # ---- 1. rate limit: at most N requests per account per minute ------------------------------
    # INCR + EXPIRE inside MULTI so that the counter can never exist without an expiry.
    # EXPIRE ... NX sets the expiry only the first time, so the window does not slide forever.
    window = int(now // 60)
    rl_key = f"rl:{from_account}:{window}"
    pipe = r.pipeline(transaction=True)
    pipe.incr(rl_key)
    pipe.expire(rl_key, 70, nx=True)
    count = pipe.execute()[0]
    if count > RATE_LIMIT_PER_MINUTE:
        raise PaymentRefused(f"RATE_LIMITED: more than {RATE_LIMIT_PER_MINUTE} requests this minute for {from_account}")

    # ---- 2. duplicate shortcut (a hint, not the authority) --------------------------------------
    idem_key = f"idem:{key}"
    cached = r.get(idem_key)
    if cached:
        return {"outcome": "DUPLICATE", "txn_id": cached, "source": "redis"}

    # ---- 3. the ledger transaction --------------------------------------------------------------
    ts = dt.datetime.fromtimestamp(int(now), tz=dt.timezone.utc)       # whole seconds, like the CSV data
    with pg() as conn:                                                  # leaving the block commits (or rolls back on error)
        with conn.transaction():
            # Lock BOTH account rows in a fixed (sorted) order. Two payments in opposite directions between the
            # same two accounts would otherwise lock them in opposite orders and deadlock.
            ids = sorted({from_account} | ({to_id} if to_kind == "ACCOUNT" else set()))
            rows = conn.execute(
                "SELECT account_id, balance_kes, customer_id FROM accounts WHERE account_id = ANY(%s) ORDER BY account_id FOR UPDATE",
                (ids,)).fetchall()
            acct = {a: (bal, cust) for a, bal, cust in rows}
            if from_account not in acct:
                raise PaymentRefused(f"UNKNOWN_ACCOUNT: {from_account}")
            if to_kind == "ACCOUNT" and to_id not in acct:
                raise PaymentRefused(f"UNKNOWN_ACCOUNT: {to_id}")
            merchant_name = None
            if to_kind == "MERCHANT":
                m = conn.execute("SELECT name FROM merchants WHERE merchant_id = %s", (to_id,)).fetchone()
                if not m:
                    raise PaymentRefused(f"UNKNOWN_MERCHANT: {to_id}")
                merchant_name = m[0]
            # The primary key (txn_id) is derived from the idempotency key, so a repeated request
            # inserts nothing and RETURNING comes back empty. This INSERT comes BEFORE the funds check on
            # purpose: a retry of an already-settled payment must be answered DUPLICATE, even if the
            # balance has since dropped below the amount.
            inserted = conn.execute(
                """INSERT INTO transactions (txn_id, ts, from_account, to_kind, to_id, amount_kes, channel, device_id, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'SETTLED')
                   ON CONFLICT (txn_id) DO NOTHING RETURNING txn_id""",
                (txn_id, ts, from_account, to_kind, to_id, amount, channel, device_id)).fetchone()
            if inserted is None:
                result = {"outcome": "DUPLICATE", "txn_id": txn_id, "source": "ledger"}
            else:
                if acct[from_account][0] < amount:
                    # Raising inside conn.transaction() rolls back everything, including the INSERT above.
                    raise PaymentRefused(f"INSUFFICIENT_FUNDS: balance {acct[from_account][0]} < {amount}")
                conn.execute("UPDATE accounts SET balance_kes = balance_kes - %s WHERE account_id = %s", (amount, from_account))
                if to_kind == "ACCOUNT":
                    conn.execute("UPDATE accounts SET balance_kes = balance_kes + %s WHERE account_id = %s", (amount, to_id))
                event = {
                    "txn_id": txn_id, "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "from_account": from_account, "from_customer": acct[from_account][1],
                    "to_kind": to_kind, "to_id": to_id,
                    "to_customer": acct[to_id][1] if to_kind == "ACCOUNT" else None,
                    "merchant_name": merchant_name, "amount_kes": amount, "channel": channel, "status": "SETTLED",
                }
                # THE OUTBOX ROW: same transaction as the payment. If the payment commits, this row commits.
                conn.execute(
                    "INSERT INTO outbox (aggregate_id, event_type, payload) VALUES (%s, 'PaymentSettled', %s::jsonb)",
                    (txn_id, json.dumps(event)))
                result = {"outcome": "SETTLED", "txn_id": txn_id}

    # ---- 4. remember the answer (24 hours). Losing this write is harmless: see the docstring. ------
    r.set(idem_key, txn_id, ex=86400)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="frm", required=True)
    ap.add_argument("--to-kind", choices=["ACCOUNT", "MERCHANT"], required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--amount", type=int, required=True)
    ap.add_argument("--key", required=True, help="the client's idempotency key, e.g. an order number")
    ap.add_argument("--channel", default="app")
    a = ap.parse_args()
    try:
        res = pay(a.frm, a.to_kind, a.to, a.amount, a.key, a.channel)
    except PaymentRefused as e:
        print("REFUSED:", e)
        sys.exit(2)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
