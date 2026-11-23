#!/usr/bin/env python3
"""
lab1_mongo_txn.py -- single-document atomicity versus a multi-document transaction.

Task: move loyalty points from one customer's document to another's.
That touches TWO documents, so a failure between the two updates is dangerous.

    python app/lab1_mongo_txn.py plain  --fail   two separate updates, crash in the middle
    python app/lab1_mongo_txn.py txn    --fail   one transaction, the same crash
    python app/lab1_mongo_txn.py txn             one transaction, no crash

MongoDB supports multi-document ACID transactions on replica sets (the lab runs a
one-member replica set for exactly this reason). They work, but the document model
is designed so that most operations touch ONE document, where atomicity is free.
"""
import argparse

from pymongo import MongoClient

from pesa.config import MONGO_URI

SRC, DST, POINTS = "C0001", "C0002", 100


def points(col, cid):
    return col.find_one({"_id": cid}, {"loyalty_points": 1})["loyalty_points"]


def move_plain(col, fail):
    ok = col.update_one({"_id": SRC, "loyalty_points": {"$gte": POINTS}}, {"$inc": {"loyalty_points": -POINTS}})
    if ok.modified_count != 1:
        raise RuntimeError("source customer has too few points")
    if fail:
        raise RuntimeError("simulated crash between the two updates")
    col.update_one({"_id": DST}, {"$inc": {"loyalty_points": POINTS}})


def move_txn(client, col, fail):
    def work(session):
        ok = col.update_one({"_id": SRC, "loyalty_points": {"$gte": POINTS}},
                            {"$inc": {"loyalty_points": -POINTS}}, session=session)
        if ok.modified_count != 1:
            raise RuntimeError("source customer has too few points")
        if fail:
            raise RuntimeError("simulated crash between the two updates")
        col.update_one({"_id": DST}, {"$inc": {"loyalty_points": POINTS}}, session=session)

    with client.start_session() as session:
        session.with_transaction(work)      # commits if work() returns, aborts if it raises


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["plain", "txn"])
    ap.add_argument("--fail", action="store_true")
    args = ap.parse_args()

    client = MongoClient(MONGO_URI)
    col = client["pesa"]["customers"]
    orig_src, orig_dst = points(col, SRC), points(col, DST)
    print(f"before: {SRC}={orig_src}  {DST}={orig_dst}  total={orig_src + orig_dst}")
    try:
        if args.mode == "plain":
            move_plain(col, args.fail)
        else:
            move_txn(client, col, args.fail)
        print("the function finished normally")
    except RuntimeError as e:
        print(f"error: {e}")
    now_src, now_dst = points(col, SRC), points(col, DST)
    print(f"after : {SRC}={now_src}  {DST}={now_dst}  total={now_src + now_dst}")
    lost = (orig_src + orig_dst) - (now_src + now_dst)
    print("TOTAL UNCHANGED" if lost == 0 else f"POINTS LOST: {lost}")
    # restore the original values so that the demonstration can be repeated
    col.update_one({"_id": SRC}, {"$set": {"loyalty_points": orig_src}})
    col.update_one({"_id": DST}, {"$set": {"loyalty_points": orig_dst}})


if __name__ == "__main__":
    main()
