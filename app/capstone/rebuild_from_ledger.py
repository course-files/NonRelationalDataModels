#!/usr/bin/env python3
"""
rebuild_from_ledger.py -- repair a DERIVED store by rebuilding it from the LEDGER.

Why this is possible: the ledger holds the complete, authoritative record of every payment. Cassandra, MongoDB
and Neo4j only hold copies shaped for particular queries, so a damaged or incomplete copy can be thrown away and
recreated. The opposite is NOT true: you cannot rebuild the ledger from the copies (they are partial and
denormalised). That asymmetry is the reason the ledger is the system of record.

Usage:
    python app/capstone/rebuild_from_ledger.py neo4j
    python app/capstone/rebuild_from_ledger.py mongo
    python app/capstone/rebuild_from_ledger.py cassandra
    python app/capstone/rebuild_from_ledger.py all
After a rebuild the consumer group for that store may still hold old messages. They are harmless: every
consumer is idempotent, so replaying them changes nothing.
"""
import argparse

import lab1_load_mongo
import lab4_load_neo4j
from capstone.common import CASS_HOST, CASS_KEYSPACE
from capstone.setup_capstone import rebuild_cassandra_from_ledger
from pesa.cass import connect


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("store", choices=["neo4j", "mongo", "cassandra", "all"])
    store = ap.parse_args().store
    if store in ("neo4j", "all"):
        lab4_load_neo4j.main(from_ledger=True)
    if store in ("mongo", "all"):
        lab1_load_mongo.main()          # this loader already reads the ledger
    if store in ("cassandra", "all"):
        cluster, session = connect(hosts=[CASS_HOST], cl="ONE")
        session.execute(f"TRUNCATE {CASS_KEYSPACE}.transactions_by_account")
        rebuild_cassandra_from_ledger(session)
        cluster.shutdown()
    print("rebuild finished")


if __name__ == "__main__":
    main()
