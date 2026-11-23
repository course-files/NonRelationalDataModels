"""data.py -- small helpers for reading the generated CSV files."""
import csv
import os

from .config import DATA_DIR


def read_csv(name):
    """Yield each row of data/<name> as a dict of strings."""
    with open(os.path.join(DATA_DIR, name), newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def read_all(name):
    return list(read_csv(name))


def ledger_rows(table):
    """Read a whole table from the PostgreSQL LEDGER, in the same shape as read_all(): a list of dicts of strings.

    The derived stores (Neo4j, Cassandra, MongoDB) can be rebuilt from the ledger because the ledger is the
    system of record. Reading from the ledger instead of the CSV files means the rebuild includes payments made
    after the CSV files were generated.
    """
    import datetime as dt

    import psycopg

    from .config import PG_DSN

    def fmt(v):
        if v is None:
            return ""
        if isinstance(v, dt.datetime):
            return v.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return str(v)

    with psycopg.connect(PG_DSN) as conn:
        cur = conn.execute(f"SELECT * FROM {table}")           # table names come from our own code, never from users
        cols = [c.name for c in cur.description]
        return [{c: fmt(v) for c, v in zip(cols, row)} for row in cur.fetchall()]
