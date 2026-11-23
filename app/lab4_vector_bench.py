#!/usr/bin/env python3
"""
lab4_vector_bench.py -- exact versus approximate nearest-neighbour search, measured.

You will measure three things on 30,000 synthetic 64-dimensional vectors:

  A. EXACT search (no index): always correct, cost grows with the number of rows.
  B. APPROXIMATE search with HNSW and IVFFlat: faster, but it may MISS some true
     neighbours. We measure "recall@10" = (how many of the true 10 nearest
     neighbours the index returned) / 10, averaged over 100 queries.
  C. FILTERED approximate search: "the 10 nearest vectors WHERE tag = 7".
     This is a famous trap: the index finds its candidates first and the filter is
     applied afterwards, so a selective filter can leave you with FEWER THAN 10 rows.

The vectors are clustered (100 clusters) so that "nearest neighbours" is meaningful,
and every row has an independent random `tag` between 0 and 99 (1 per cent each).
The numpy brute-force answer is the ground truth.

Run:  docker compose exec workbench python app/lab4_vector_bench.py          (under a minute)
      docker compose exec workbench python app/lab4_vector_bench.py --n 5000 (a faster, smaller run)
"""
import argparse
import time

import numpy as np
import psycopg

from pesa.config import PG_DSN
from pesa.embed import to_pgvector

DIM = 64
K = 10


def make_data(n, n_queries, seed=7):
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(100, DIM))
    assign = rng.integers(0, 100, size=n)
    x = centres[assign] + 0.7 * rng.normal(size=(n, DIM))
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    q_assign = rng.integers(0, 100, size=n_queries)
    q = centres[q_assign] + 0.7 * rng.normal(size=(n_queries, DIM))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    tags = rng.integers(0, 100, size=n)
    return x.astype(np.float32), q.astype(np.float32), tags


def ground_truth(x, q, tags=None, tag=None):
    """Exact top-K by cosine distance (vectors are unit length, so cosine = dot product)."""
    sims = q @ x.T
    if tag is not None:
        sims = np.where(tags[None, :] == tag, sims, -np.inf)
    return np.argsort(-sims, axis=1)[:, :K]


def run_queries(conn, q, where="", params=()):
    """Run every query vector; return (list of id-lists, average milliseconds)."""
    results, t0 = [], time.perf_counter()
    for v in q:
        rows = conn.execute(
            f"SELECT id FROM bench_vectors {where} ORDER BY embedding <=> %s::vector LIMIT {K}",
            (*params, to_pgvector(v))).fetchall()
        results.append([r[0] for r in rows])
    return results, (time.perf_counter() - t0) * 1000 / len(q)


def recall(found, truth):
    hits = sum(len(set(f) & set(map(int, t))) for f, t in zip(found, truth))
    return hits / (K * len(truth))


def plan_uses_index(conn, v):
    plan = "\n".join(r[0] for r in conn.execute(
        f"EXPLAIN SELECT id FROM bench_vectors ORDER BY embedding <=> %s::vector LIMIT {K}", (to_pgvector(v),)))
    return "Index Scan" in plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30000)
    ap.add_argument("--queries", type=int, default=100)
    args = ap.parse_args()

    x, q, tags = make_data(args.n, args.queries)
    truth = ground_truth(x, q)

    with psycopg.connect(PG_DSN, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("DROP TABLE IF EXISTS bench_vectors")
        conn.execute(f"CREATE TABLE bench_vectors (id int PRIMARY KEY, tag int NOT NULL, embedding vector({DIM}) NOT NULL)")
        with conn.cursor() as cur, cur.copy("COPY bench_vectors (id, tag, embedding) FROM STDIN") as cp:
            for i in range(args.n):
                cp.write_row((i, int(tags[i]), to_pgvector(x[i])))
        conn.execute("ANALYZE bench_vectors")
        print(f"loaded {args.n} vectors of {DIM} dimensions; {args.queries} test queries\n")

        # ---------------- A. exact ----------------
        found, ms = run_queries(conn, q)
        print("A. EXACT search (no index, sequential scan)")
        print(f"   recall@{K} = {recall(found, truth):.3f}    average latency = {ms:6.1f} ms\n")

        # ---------------- B1. HNSW ----------------
        t0 = time.perf_counter()
        conn.execute("CREATE INDEX bench_hnsw ON bench_vectors USING hnsw (embedding vector_cosine_ops) "
                     "WITH (m = 16, ef_construction = 64)")
        print(f"B1. HNSW index (m=16, ef_construction=64) built in {time.perf_counter() - t0:.1f} s; "
              f"planner uses the index: {plan_uses_index(conn, q[0])}")
        print("    ef_search = how many candidates the search keeps while walking the graph (default 40)")
        print(f"    {'ef_search':>10} {'recall@10':>10} {'latency ms':>11}")
        for ef in (10, 40, 100, 200):
            conn.execute(f"SET hnsw.ef_search = {ef}")
            found, ms = run_queries(conn, q)
            print(f"    {ef:>10} {recall(found, truth):>10.3f} {ms:>11.2f}")

        # ---------------- C. filtered search (still on the HNSW index) ----------------
        print("\nC. FILTERED search: nearest 10 vectors WHERE tag = 7   (1 per cent of rows qualify)")
        conn.execute("SET hnsw.ef_search = 40")
        truth7 = ground_truth(x, q, tags, 7)
        found, ms = run_queries(conn, q, "WHERE tag = %s", (7,))
        avg_rows = sum(len(f) for f in found) / len(found)
        print(f"   ef_search=40 : rows returned per query = {avg_rows:4.1f} (asked for {K}), "
              f"recall@10 = {recall(found, truth7):.3f}")
        conn.execute("SET hnsw.ef_search = 1000")
        found, ms = run_queries(conn, q, "WHERE tag = %s", (7,))
        avg_rows = sum(len(f) for f in found) / len(found)
        print(f"   ef_search=1000: rows returned per query = {avg_rows:4.1f}, "
              f"recall@10 = {recall(found, truth7):.3f}, latency = {ms:.1f} ms")
        try:   # pgvector 0.8 and later: keep scanning the index until enough rows pass the filter
            conn.execute("SET hnsw.iterative_scan = relaxed_order")
            conn.execute("SET hnsw.ef_search = 40")
            found, ms = run_queries(conn, q, "WHERE tag = %s", (7,))
            avg_rows = sum(len(f) for f in found) / len(found)
            print(f"   iterative scan (pgvector 0.8+): rows returned per query = {avg_rows:4.1f}, "
                  f"recall@10 = {recall(found, truth7):.3f}, latency = {ms:.1f} ms")
        except psycopg.Error:
            print("   (this pgvector version has no hnsw.iterative_scan; it was added in 0.8.0)")
        conn.execute("RESET hnsw.ef_search")
        conn.execute("RESET ALL")
        conn.execute("DROP INDEX bench_hnsw")

        # ---------------- B2. IVFFlat ----------------
        t0 = time.perf_counter()
        conn.execute("CREATE INDEX bench_ivf ON bench_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")
        print(f"\nB2. IVFFlat index (lists=100) built in {time.perf_counter() - t0:.1f} s; "
              f"planner uses the index: {plan_uses_index(conn, q[0])}")
        print("    probes = how many of the 100 clusters ('lists') are searched (default 1)")
        print(f"    {'probes':>10} {'recall@10':>10} {'latency ms':>11}")
        for probes in (1, 5, 10, 20):
            conn.execute(f"SET ivfflat.probes = {probes}")
            found, ms = run_queries(conn, q)
            print(f"    {probes:>10} {recall(found, truth):>10.3f} {ms:>11.2f}")
        conn.execute("RESET ALL")
        conn.execute("DROP INDEX bench_ivf")
    print("\nDone. Table bench_vectors is left in place so that you can run your own EXPLAIN ANALYZE queries.")


if __name__ == "__main__":
    main()
