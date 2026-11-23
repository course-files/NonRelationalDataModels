#!/usr/bin/env python3
"""
lab4_embed_disputes.py -- put a VECTOR next to every customer dispute in PostgreSQL.

What you will see
-----------------
1. PostgreSQL gains a new column TYPE, vector(64), from the pgvector extension.
2. Every dispute description is turned into a 64-number vector (an "embedding").
3. An HNSW index is built so that "nearest vector" queries do not scan every row.

The embedding function here (pesa/embed.py) is a small teaching stand-in, NOT a
trained language model. See the lab manual for the honest discussion, and run
`python app/lab4_embed_disputes.py --model fastembed` if you have internet access
and want to try a real model (it uses a different, larger vector size).

Run:  docker compose exec workbench python app/lab4_embed_disputes.py
"""
import argparse

import psycopg

from pesa.config import PG_DSN
from pesa.embed import DIM, embed, to_pgvector


def get_embedder(model):
    """Return (dimension, function text->list-like) for the chosen model."""
    if model == "standin":
        return DIM, embed
    if model == "fastembed":
        # Optional path. Needs internet access the first time (downloads about 90 MB).
        from fastembed import TextEmbedding
        te = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")
        return 384, lambda text: next(iter(te.embed([text])))
    raise SystemExit(f"unknown model {model}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["standin", "fastembed"], default="standin")
    args = ap.parse_args()
    dim, fn = get_embedder(args.model)

    with psycopg.connect(PG_DSN, autocommit=True) as conn:
        # Extensions are installed per database. The pgvector Docker image already ships the files.
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        # Start clean so the script can be re-run (also when you switch model and the dimension changes).
        conn.execute("DROP TABLE IF EXISTS dispute_vectors")
        # One row per dispute. vector(64) means "exactly 64 floating-point numbers".
        conn.execute(f"""
            CREATE TABLE dispute_vectors (
                dispute_id text PRIMARY KEY REFERENCES disputes (dispute_id),
                embedding  vector({dim}) NOT NULL
            )""")

        rows = conn.execute("SELECT dispute_id, description FROM disputes ORDER BY dispute_id").fetchall()
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO dispute_vectors (dispute_id, embedding) VALUES (%s, %s::vector)",
                [(d, to_pgvector(fn(text))) for d, text in rows])
        print(f"embedded {len(rows)} disputes into vector({dim})")

        # HNSW = Hierarchical Navigable Small World graph, an APPROXIMATE nearest-neighbour index.
        # vector_cosine_ops says: this index answers queries that use the cosine-distance operator <=>.
        # With only 60 rows PostgreSQL will usually still choose a sequential scan (it is cheaper);
        # Lab 4 part D builds a 30,000-vector table where the index matters.
        conn.execute("CREATE INDEX dispute_vectors_hnsw ON dispute_vectors USING hnsw (embedding vector_cosine_ops)")
        print("created HNSW index dispute_vectors_hnsw (cosine)")

        sample = conn.execute("SELECT dispute_id, left(embedding::text, 60) FROM dispute_vectors LIMIT 1").fetchone()
        print("what a stored vector looks like:", sample[0], sample[1], "...")


if __name__ == "__main__":
    main()
