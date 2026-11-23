"""
common.py -- names and helpers shared by every capstone program.

The capstone sends ONE payment through FIVE stores:

    PostgreSQL  = the LEDGER, the system of record (balances, transactions, outbox)
    Redis       = rate limiting, a fast duplicate filter, and the event STREAM
    Cassandra   = the account statement ("show my payments for the month")
    MongoDB     = the customer profile document (5 recent payments, loyalty points)
    Neo4j       = the money-flow graph (who paid whom)

Only the ledger decides whether a payment HAPPENED. The other four stores hold copies
shaped for one access pattern each; they are updated from the event stream, and each one
can be rebuilt from the ledger if it is damaged.
"""
import hashlib
import json
import os

import psycopg
import redis

from pesa.config import PG_DSN, REDIS_HOST, REDIS_PORT

STREAM = "pesa.events"                       # the Redis Stream that carries payment events
GROUPS = ("cassandra", "mongo", "neo4j")     # one consumer group per derived store
CASS_KEYSPACE = "pesa_one"                   # the capstone uses a single Cassandra node, replication factor 1
CASS_HOST = os.environ.get("CAPSTONE_CASS_HOST", "cass-solo")
RATE_LIMIT_PER_MINUTE = 20


def pg():
    """A new PostgreSQL connection (psycopg 3). Use as a context manager: commit on success, rollback on error."""
    return psycopg.connect(PG_DSN)


def rds():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def txn_id_for(idempotency_key):
    """A DETERMINISTIC transaction id derived from the client's idempotency key.

    The same key always gives the same id, so a retried request cannot create a second payment:
    the second INSERT collides with the first on the primary key and is ignored.
    """
    return "P" + hashlib.sha1(idempotency_key.encode("utf-8")).hexdigest()[:12]


def encode_event(txn_id, event_type, payload):
    """Flatten an event into the string fields that XADD stores."""
    return {"txn_id": txn_id, "type": event_type, "payload": json.dumps(payload, sort_keys=True)}


def decode_event(fields):
    return json.loads(fields["payload"])
