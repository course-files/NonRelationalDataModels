#!/usr/bin/env python3
"""
lab1_load_mongo.py -- builds the CUSTOMER PROFILE documents in MongoDB.

Relational design asks "what are the entities?" and spreads a customer across
five tables. Document design asks "what does the app read together?". The
mobile app's home screen reads ONE customer's profile, so we store everything
that screen needs inside ONE document (an "aggregate"):

    {
      _id: "C0007", full_name, phone, county, kyc_level, joined_on,
      preferred_language, marketing_opt_in      <- present for SOME customers only
      accounts: [ {account_id, type, currency} ... ],        <- embedded (few, bounded)
      devices:  [ {device_id, model} ... ],                  <- embedded (few, bounded)
      recent_transactions: [ ...the 5 newest... ],           <- a BOUNDED subset, not all history
      loyalty_points: 1234
    }

Two things are deliberately NOT inside the document:
  * account BALANCES -- they change on every payment and must be exactly right,
    so they stay in the ledger (PostgreSQL);
  * the full transaction history -- it is unbounded; a document must stay small.

The merchant NAME is copied into each recent transaction (denormalisation) so the
screen needs no second lookup. Lab 1, Part E shows what that copy costs you.

Run:  docker compose exec workbench python app/lab1_load_mongo.py
"""
import datetime as dt

import psycopg
from pymongo import MongoClient

from pesa.config import MONGO_URI, PG_DSN

RECENT = 5


def main():
    client = MongoClient(MONGO_URI)
    db = client["pesa"]
    with psycopg.connect(PG_DSN) as conn:
        customers = conn.execute(
            """SELECT customer_id, full_name, phone, county, kyc_level, joined_on,
                      preferred_language, marketing_opt_in FROM customers ORDER BY customer_id""").fetchall()
        accounts = {}
        for cid, aid, typ, cur in conn.execute(
                "SELECT customer_id, account_id, account_type, currency FROM accounts ORDER BY account_id"):
            accounts.setdefault(cid, []).append({"account_id": aid, "type": typ, "currency": cur})
        devices = {}
        for cid, did, model in conn.execute(
                """SELECT DISTINCT a.customer_id, d.device_id, d.model
                     FROM accounts a JOIN account_devices ad ON ad.account_id = a.account_id
                     JOIN devices d ON d.device_id = ad.device_id ORDER BY 1, 2"""):
            devices.setdefault(cid, []).append({"device_id": did, "model": model})
        recent = {}
        for row in conn.execute(
                """SELECT customer_id, txn_id, ts, from_account, to_kind, to_id, amount_kes, status, merchant_name
                     FROM (SELECT a.customer_id, t.txn_id, t.ts, t.from_account, t.to_kind, t.to_id,
                                  t.amount_kes, t.status, m.name AS merchant_name,
                                  row_number() OVER (PARTITION BY a.customer_id
                                                     ORDER BY t.ts DESC, t.txn_id DESC) AS rn
                             FROM transactions t
                             JOIN accounts a ON a.account_id = t.from_account
                             LEFT JOIN merchants m ON t.to_kind = 'MERCHANT' AND m.merchant_id = t.to_id) x
                    WHERE rn <= %s ORDER BY customer_id, rn""", (RECENT,)):
            cid, txn_id, ts, frm, kind, to_id, amount, status, mname = row
            entry = {"txn_id": txn_id, "ts": ts, "from_account": frm, "to_kind": kind, "to_id": to_id,
                     "amount_kes": int(amount), "status": status}
            if mname:
                entry["merchant_name"] = mname           # denormalised copy
            recent.setdefault(cid, []).append(entry)
        points = dict(conn.execute(
            """SELECT a.customer_id, SUM(t.amount_kes / 100)::int
                 FROM transactions t JOIN accounts a ON a.account_id = t.from_account
                WHERE t.status = 'SETTLED' GROUP BY a.customer_id""").fetchall())
        merchants = conn.execute("SELECT merchant_id, name, category, county FROM merchants ORDER BY 1").fetchall()

    docs = []
    for cid, name, phone, county, kyc, joined, lang, optin in customers:
        doc = {
            "_id": cid, "full_name": name, "phone": phone, "county": county, "kyc_level": kyc,
            "joined_on": dt.datetime(joined.year, joined.month, joined.day, tzinfo=dt.timezone.utc),
            "accounts": accounts.get(cid, []),
            "devices": devices.get(cid, []),
            "recent_transactions": recent.get(cid, []),
            "loyalty_points": int(points.get(cid, 0)),
            "schema_version": 1,
        }
        # Optional attributes: simply ABSENT when the customer has no value.
        # There is no NULL column and no ALTER TABLE; documents may differ in shape.
        if lang:
            doc["preferred_language"] = lang
        if optin is not None:
            doc["marketing_opt_in"] = bool(optin)
        docs.append(doc)

    db.drop_collection("customers")
    db.drop_collection("merchants")
    db.customers.insert_many(docs)
    db.merchants.insert_many(
        [{"_id": m[0], "name": m[1], "category": m[2], "county": m[3]} for m in merchants])
    print(f"customers: {db.customers.count_documents({})} documents")
    print(f"merchants: {db.merchants.count_documents({})} documents")


if __name__ == "__main__":
    main()
