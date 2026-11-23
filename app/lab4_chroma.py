#!/usr/bin/env python3
"""
lab4_chroma.py -- the OPTIONAL alternative to pgvector: a dedicated vector database (Chroma).

Why this exists
---------------
pgvector keeps vectors INSIDE PostgreSQL, next to the ledger, so one SQL query can combine
vector search with ordinary joins and filters, and one backup covers everything.
Chroma is a stand-alone vector store. Doing the same search there shows what you gain
(a simple, purpose-built API) and what you give up (a second system to run, a second copy
of the data to keep in step, and no SQL join to the ledger).

Install once (it is big, so it is not in requirements.txt):
    docker compose exec workbench pip install "chromadb>=1.0,<2"

Run:
    docker compose exec workbench python app/lab4_chroma.py
    docker compose exec workbench python app/lab4_chroma.py "charged twice for the same payment"

This script uses Chroma in EMBEDDED mode: the library runs inside the Python process and keeps
its files in ./chroma_data (no extra container). The same calls work against a Chroma server.
"""
import sys

import chromadb

from pesa.data import read_all
from pesa.embed import embed

QUERIES = [
    "charged twice for the same payment",
    "the shop says it sent it but nothing arrived",
    "my money was taken but the app said it failed",
]


def main():
    client = chromadb.PersistentClient(path="chroma_data")
    try:
        client.delete_collection("disputes")        # start clean so the script can be re-run
    except Exception:                               # noqa: BLE001 - collection did not exist yet
        pass
    # hnsw:space = which distance the index uses. Chroma's default is squared L2;
    # we choose cosine to match the pgvector part of the lab.
    col = client.create_collection("disputes", metadata={"hnsw:space": "cosine"})

    disputes = read_all("disputes.csv")
    col.add(
        ids=[d["dispute_id"] for d in disputes],
        embeddings=[embed(d["description"]).tolist() for d in disputes],   # we supply the vectors ourselves
        documents=[d["description"] for d in disputes],
        metadatas=[{"category": d["category"], "customer_id": d["customer_id"]} for d in disputes],
    )
    print(f"stored {col.count()} disputes in Chroma collection 'disputes'")

    queries = sys.argv[1:] or QUERIES
    for text in queries:
        res = col.query(query_embeddings=[embed(text).tolist()], n_results=5)
        print(f'\nquery: "{text}"')
        for i in range(len(res["ids"][0])):
            print(f"  {res['ids'][0][i]:7} {res['metadatas'][0][i]['category']:19} "
                  f"dist={res['distances'][0][i]:.4f}  {res['documents'][0][i]}")

    # A metadata filter is part of the query API. Chroma applies it together with the vector search.
    text = "refund"
    res = col.query(query_embeddings=[embed(text).tolist()], n_results=3, where={"category": "refund_delay"})
    print(f'\nfiltered query ("{text}", only category = refund_delay):')
    for i in range(len(res["ids"][0])):
        print(f"  {res['ids'][0][i]:7} dist={res['distances'][0][i]:.4f}  {res['documents'][0][i]}")


if __name__ == "__main__":
    main()
