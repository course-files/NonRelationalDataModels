#!/usr/bin/env python3
"""
lab4_load_neo4j.py -- builds the fraud GRAPH from the data files.

Graph model (a "labelled property graph"):

    (:Customer)-[:OWNS]->(:Account)-[:USED]->(:Device)
                          (:Account)-[:SENT {txn_id, amount, ts, channel}]->(:Account)
                          (:Account)-[:PAID {txn_id, amount, ts, channel}]->(:Merchant)

Only SETTLED payments become edges. Each payment is its own relationship, so two
accounts that pay each other many times are joined by many parallel edges.

Run:  docker compose exec workbench python app/lab4_load_neo4j.py
      docker compose exec workbench python app/lab4_load_neo4j.py --from-ledger
          (the second form reads PostgreSQL instead of the CSV files. The graph is a DERIVED copy, so it
           can always be rebuilt from the ledger; the capstone uses this to repair a graph that missed events)
"""
import argparse
import time

from neo4j import GraphDatabase

from pesa.config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER
from pesa.data import ledger_rows
from pesa.data import read_all as _read_csv_all

BATCH = 1000


def chunks(rows, n=BATCH):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def load(driver, from_ledger=False):
    with driver.session() as s:
        # Constraints make "MATCH by id" fast (they create an index) and stop duplicates.
        for label in ("Customer", "Account", "Device", "Merchant"):
            s.run(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE").consume()
        s.run("MATCH (n) DETACH DELETE n").consume()      # start clean so the script can be re-run

        def read_all(name):                               # CSV file name -> rows, from the CSV or from the ledger
            if from_ledger:
                return ledger_rows(name.replace(".csv", ""))
            return _read_csv_all(name)

        customers = read_all("customers.csv")
        accounts = read_all("accounts.csv")
        devices = read_all("devices.csv")
        merchants = read_all("merchants.csv")
        owns = [{"c": a["customer_id"], "a": a["account_id"]} for a in accounts]
        used = read_all("account_devices.csv")
        txns = [t for t in read_all("transactions.csv") if t["status"] == "SETTLED"]
        p2p = [{"txn_id": t["txn_id"], "from": t["from_account"], "to": t["to_id"], "amount": int(t["amount_kes"]),
                "ts": t["ts"], "channel": t["channel"]} for t in txns if t["to_kind"] == "ACCOUNT"]
        pay = [{"txn_id": t["txn_id"], "from": t["from_account"], "to": t["to_id"], "amount": int(t["amount_kes"]),
                "ts": t["ts"], "channel": t["channel"]} for t in txns if t["to_kind"] == "MERCHANT"]

        for rows in chunks([{"id": c["customer_id"], "name": c["full_name"], "county": c["county"]} for c in customers]):
            s.run("UNWIND $rows AS r CREATE (:Customer {id: r.id, name: r.name, county: r.county})", rows=rows).consume()
        for rows in chunks([{"id": a["account_id"], "type": a["account_type"]} for a in accounts]):
            s.run("UNWIND $rows AS r CREATE (:Account {id: r.id, type: r.type})", rows=rows).consume()
        for rows in chunks([{"id": d["device_id"], "model": d["model"]} for d in devices]):
            s.run("UNWIND $rows AS r CREATE (:Device {id: r.id, model: r.model})", rows=rows).consume()
        for rows in chunks([{"id": m["merchant_id"], "name": m["name"], "category": m["category"]} for m in merchants]):
            s.run("UNWIND $rows AS r CREATE (:Merchant {id: r.id, name: r.name, category: r.category})", rows=rows).consume()

        for rows in chunks(owns):
            s.run("""UNWIND $rows AS r
                     MATCH (c:Customer {id: r.c}), (a:Account {id: r.a})
                     CREATE (c)-[:OWNS]->(a)""", rows=rows).consume()
        for rows in chunks([{"a": u["account_id"], "d": u["device_id"]} for u in used]):
            s.run("""UNWIND $rows AS r
                     MATCH (a:Account {id: r.a}), (d:Device {id: r.d})
                     CREATE (a)-[:USED]->(d)""", rows=rows).consume()
        for rows in chunks(p2p):
            s.run("""UNWIND $rows AS r
                     MATCH (a:Account {id: r.from}), (b:Account {id: r.to})
                     CREATE (a)-[:SENT {txn_id: r.txn_id, amount: r.amount, ts: datetime(r.ts), channel: r.channel}]->(b)""",
                  rows=rows).consume()
        for rows in chunks(pay):
            s.run("""UNWIND $rows AS r
                     MATCH (a:Account {id: r.from}), (m:Merchant {id: r.to})
                     CREATE (a)-[:PAID {txn_id: r.txn_id, amount: r.amount, ts: datetime(r.ts), channel: r.channel}]->(m)""",
                  rows=rows).consume()

        n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        e = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        print(f"loaded {n} nodes and {e} relationships "
              f"({len(p2p)} SENT, {len(pay)} PAID, {len(owns)} OWNS, {len(used)} USED)")


def main(from_ledger=False):
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    for attempt in range(60):                          # wait for Neo4j to finish starting
        try:
            driver.verify_connectivity()
            break
        except Exception as e:                         # noqa: BLE001 - any start-up error: wait and retry
            if attempt == 59:
                raise
            print("waiting for Neo4j ...", type(e).__name__, flush=True)
            time.sleep(3)
    t0 = time.time()
    load(driver, from_ledger)
    print(f"done in {time.time() - t0:.1f}s")
    driver.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-ledger", action="store_true", help="read PostgreSQL instead of the CSV files")
    main(ap.parse_args().from_ledger)
