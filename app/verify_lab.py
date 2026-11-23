#!/usr/bin/env python3
"""
verify_lab.py -- a self-check for each lab. It tests the STATE of your databases and the presence of your
written work. It does not mark your answers (your lecturer does that).

Usage (from the lab folder):
    docker compose exec workbench python app/verify_lab.py 1       # or 2, 3, 4, capstone
Each line says PASS or FAIL and, on FAIL, what to look at. Run it as often as you like.
"""
import csv
import os
import subprocess
import sys

from pesa.config import CASS_HOSTS, DATA_DIR, MONGO_URI, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER, PG_DSN, REDIS_HOST, REDIS_PORT

RESULTS = []
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "my_work")


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:                      # noqa: BLE001 - a store that is down is a FAIL, not a crash
        ok, detail = False, f"{type(e).__name__}: {str(e)[:120]}  (is the right profile started?)"
    RESULTS.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"   -> {detail}"))


def eq(label, got, want):
    return got == want, f"{label}: found {got}, expected {want}"


def words(path):
    full = os.path.join(WORK, path)
    if not os.path.exists(full):
        return 0
    text = open(full, encoding="utf-8").read()
    # ignore the template instructions: count only lines that are not the ">" instruction lines or headings
    body = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith((">", "#", "<!--"))]
    return sum(len(ln.split()) for ln in body)


def written_work(path, minimum):
    def f():
        n = words(path)
        return n >= minimum, f"my_work/{path} has about {n} words of your own writing; at least {minimum} expected"
    return f


# --------------------------------------------------------------------------------------- Lab 1
def lab1():
    import pymongo
    import redis
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    db = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)["pesa"]

    check("Redis: merchant leaderboard loaded (40 members)", lambda: eq("members", r.zcard("lb:merchant:2026-09"), 40))
    check("Redis: 92 daily HyperLogLogs loaded", lambda: eq("keys", sum(1 for _ in r.scan_iter("uniq:dev:*")), 92))
    check("MongoDB: 320 customer documents and 40 merchants",
          lambda: eq("customers/merchants", (db.customers.count_documents({}), db.merchants.count_documents({})), (320, 40)))

    def validator():
        opts = db.command("listCollections", filter={"name": "customers"})["cursor"]["firstBatch"][0].get("options", {})
        v = str(opts.get("validator", ""))
        return ("$jsonSchema" in v and "kyc_level" in v), "customers has no $jsonSchema validator that mentions kyc_level (Part F, step 4)"
    check("MongoDB: schema validator on customers", validator)

    def index():
        for ix in db.customers.list_indexes():
            keys = list(ix["key"].keys())
            if "county" in keys and "kyc_level" in keys:
                return True, ""
        return False, "no compound index containing county and kyc_level (Part F, step 5)"
    check("MongoDB: compound index on county and kyc_level", index)

    def cache():
        p = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "lab1_cache_aside.py"), "check"],
                           capture_output=True, text=True, timeout=60)
        return p.returncode == 0, (p.stdout.strip().splitlines() or ["no output"])[-1]
    check("Cache-aside: your credit_safe() keeps the cache fresh", cache)
    check("Written work: answers", written_work("Lab1_answers.md", 150))
    check("Written work: design memo", written_work("Lab1_design_memo.md", 150))


# --------------------------------------------------------------------------------------- Lab 2
def lab2():
    from pesa.cass import connect
    cluster, s = connect(cl="ONE", wait_seconds=20)
    rows = list(csv.DictReader(open(os.path.join(DATA_DIR, "transactions.csv"), encoding="utf-8")))
    n_in = sum(1 for t in rows if t["to_kind"] == "ACCOUNT")
    n_merchant = sum(1 for t in rows if t["to_kind"] == "MERCHANT")
    n_a7 = sum(1 for t in rows if t["from_account"] == "A0007")

    check("Cluster: three nodes are up", lambda: eq("live nodes", sum(1 for h in cluster.metadata.all_hosts() if h.is_up), 3))

    def keyspace():
        row = s.execute("SELECT replication FROM system_schema.keyspaces WHERE keyspace_name = 'pesa'").one()
        rep = dict(row.replication) if row else {}
        return (rep.get("class", "").endswith("NetworkTopologyStrategy") and rep.get("dc1") == "3"), \
            f"keyspace pesa missing or not NetworkTopologyStrategy dc1=3 (found {rep}); run app/lab2_load_cassandra.py"
    check("Keyspace pesa uses NetworkTopologyStrategy, dc1 = 3", keyspace)

    def count(table):
        return s.execute(f"SELECT count(*) FROM pesa.{table}", timeout=120).one()[0]
    check("transactions_by_account holds payer and payee rows",
          lambda: eq("rows", count("transactions_by_account"), len(rows) + n_in))
    check("transactions_by_merchant_day holds merchant payments",
          lambda: eq("rows", count("transactions_by_merchant_day"), n_merchant))
    check("transactions_by_account_nobucket holds only A0007", lambda: eq("rows", count("transactions_by_account_nobucket"), n_a7))
    check("Written work: answers", written_work("Lab2_answers.md", 150))
    check("Written work: design memo", written_work("Lab2_design_memo.md", 150))
    cluster.shutdown()


# --------------------------------------------------------------------------------------- Lab 3
def lab3():
    import redis
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    check("Part B: the pipeline harness has been run (its streams exist in Redis)",
          lambda: (any(True for _ in r.scan_iter("pipe:*")), "run app/lab3_pipeline.py at least once"))

    def wallets():
        from pesa.cass import connect
        cluster, s = connect(cl="ONE", wait_seconds=15)
        n = s.execute("SELECT count(*) FROM monzo_lab.wallets", timeout=60).one()[0]
        live = sum(1 for h in cluster.metadata.all_hosts() if h.is_up)
        cluster.shutdown()
        print(f"      (information) Part A state: {n} wallets readable at ONE, {live} node(s) up")
        return n == 3000, f"found {n} wallets, expected 3000 (run app/lab3_wallets.py load)"
    check("Part A: the wallets table is loaded (3,000 rows)", wallets)
    check("Written work: answers", written_work("Lab3_answers.md", 150))
    check("Deliverable 1: scale-up runbook", written_work("Lab3_runbook.md", 250))
    check("Deliverable 2: failure-isolated pipeline design", written_work("Lab3_pipeline_design.md", 250))


# --------------------------------------------------------------------------------------- Lab 4
def lab4():
    import psycopg
    from neo4j import GraphDatabase

    def graph():
        d = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with d.session() as s:
            n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            e = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        d.close()
        return n == 1162 and e >= 12435, (f"graph has {n} nodes and {e} relationships; the clean load gives 1162 and 12435 "
                                          "(more relationships are normal after the capstone)")
    check("Neo4j: the fraud graph is loaded", graph)

    def vectors():
        with psycopg.connect(PG_DSN) as c:
            n = c.execute("SELECT count(*) FROM dispute_vectors").fetchone()[0]
            ix = c.execute("SELECT count(*) FROM pg_indexes WHERE indexname = 'dispute_vectors_hnsw'").fetchone()[0]
        return (n, ix) == (60, 1), f"dispute_vectors rows={n}, hnsw index={ix}; run app/lab4_embed_disputes.py"
    check("pgvector: 60 dispute embeddings and an HNSW index", vectors)

    def bench():
        with psycopg.connect(PG_DSN) as c:
            n = c.execute("SELECT count(*) FROM bench_vectors").fetchone()[0]
        return n == 30000, f"bench_vectors has {n} rows; run app/lab4_vector_bench.py"
    check("pgvector: the benchmark table exists (30,000 vectors)", bench)
    check("Written work: answers", written_work("Lab4_answers.md", 200))
    check("Written work: design memo", written_work("Lab4_design_memo.md", 250))


def capstone():
    from capstone import verify_consistency
    check("Capstone: every store agrees with the ledger (verify_consistency.py)",
          lambda: (verify_consistency.main(out=lambda *_: None, argv=[]) == 0, "run the relay and the consumers, then look at verify_consistency.py"))
    check("Written work: capstone answers", written_work("Lab4_answers.md", 200))


LABS = {"1": lab1, "2": lab2, "3": lab3, "4": lab4, "capstone": capstone}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in LABS:
        raise SystemExit("usage: python app/verify_lab.py {1|2|3|4|capstone}")
    print(f"=== checks for lab {sys.argv[1]} ===")
    LABS[sys.argv[1]]()
    ok = sum(RESULTS)
    print(f"\n{ok} of {len(RESULTS)} checks passed")
    sys.exit(0 if ok == len(RESULTS) else 1)
