#!/usr/bin/env python3
"""
lab4_search.py -- semantic search over customer disputes (pgvector).

Usage:
    python app/lab4_search.py "charged twice for the same payment"
    python app/lab4_search.py "the shop says it sent it but nothing arrived" --k 8
    python app/lab4_search.py "my money was taken but the app said it failed" --metric l2
    python app/lab4_search.py "..." --keyword            # compare with a plain keyword (LIKE) search

pgvector distance operators
    <->  Euclidean (L2) distance        smaller = closer
    <=>  cosine distance (1 - cosine similarity)   smaller = closer      <- used by default
    <#>  NEGATIVE inner product         smaller = closer (the sign trick lets one index serve ORDER BY)
For unit-length vectors all three give the same ranking. The stand-in embedder returns unit vectors.
"""
import argparse
import re

import psycopg

from pesa.config import PG_DSN
from pesa.embed import embed, to_pgvector

OPS = {"cosine": "<=>", "l2": "<->", "ip": "<#>"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--metric", choices=OPS, default="cosine")
    ap.add_argument("--keyword", action="store_true", help="also run a keyword search for comparison")
    args = ap.parse_args()
    op = OPS[args.metric]

    qv = to_pgvector(embed(args.query))
    sql = f"""
        SELECT d.dispute_id, d.category, v.embedding {op} %s::vector AS distance, d.description
        FROM   dispute_vectors v JOIN disputes d USING (dispute_id)
        ORDER  BY v.embedding {op} %s::vector
        LIMIT  %s"""
    with psycopg.connect(PG_DSN) as conn:
        print(f'\nquery: "{args.query}"   metric: {args.metric} ({op})')
        print(f"{'dispute':8} {'category':19} {'distance':>9}  description")
        for did, cat, dist, desc in conn.execute(sql, (qv, qv, args.k)):
            print(f"{did:8} {cat:19} {dist:9.4f}  {desc}")

        if args.keyword:
            words = [w for w in re.findall(r"[a-z]+", args.query.lower()) if len(w) > 3]
            where = " OR ".join(["description ILIKE %s"] * len(words))
            rows = conn.execute(f"SELECT dispute_id, category, description FROM disputes WHERE {where} ORDER BY dispute_id",
                                [f"%{w}%" for w in words]).fetchall() if words else []
            print(f"\nkeyword search (a description containing ANY of {words}) matched {len(rows)} of 60 disputes,")
            print("in no useful order and with no sense of 'closeness' (showing the first few):")
            for did, cat, desc in rows[:args.k]:
                print(f"{did:8} {cat:19} {'':9}  {desc}")


if __name__ == "__main__":
    main()
