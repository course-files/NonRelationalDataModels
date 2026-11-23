#!/usr/bin/env python3
"""
gen_data.py -- builds the fictional Pesa Platform dataset used by all four labs.

The files in ../data/ were produced by this script and are already included in
the lab pack, so students do NOT need to run it. It is included so that you can
see exactly how the data (and the deliberately planted patterns) were made.

Everything is deterministic: the same seed always produces the same files.
Only the Python standard library is used.

Planted patterns (the labs look for these):
  * A0007            a very busy account (partition-size / hot-key discussion)
  * M001             a very popular merchant (hot-key discussion)
  * A0010 + A0011    a FAMILY sharing one phone (D010): shared device != fraud
  * A0020 <-> A0021  a harmless two-hop money loop (a cycle of length 2)
  * A0316..A0320     a FRAUD RING: five new accounts sharing two phones
                     (D401, D402) and moving ~KES 48,000 around a 4-account
                     loop within six hours, followed by a cash-out.
  * A0100 -> A0101   a one-off large transfer (large amount, but no loop)

All names, phone numbers and merchants are invented.
"""
import csv
import datetime as dt
import hashlib
import json
import math
import os
import random

SEED = 20261010
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

N_CUSTOMERS = 320
N_ACCOUNTS = 400
N_MERCHANTS = 40
N_DEVICES = 402
N_TXNS = 12000
START = dt.datetime(2026, 7, 1, 0, 0, 0)
DAYS = 92  # 1 July .. 30 September 2026

FIRST = ["Wanjiru", "Otieno", "Achieng", "Kamau", "Mwangi", "Njeri", "Odhiambo", "Chebet",
         "Kiprop", "Mutua", "Wambui", "Omondi", "Atieno", "Kariuki", "Naliaka", "Mwakalu",
         "Hussein", "Akinyi", "Barasa", "Cherono", "Mumbi", "Kiplagat", "Nyambura", "Ouma",
         "Auma", "Maina", "Wafula", "Jepkorir", "Kimani", "Adhiambo", "Ndungu", "Wekesa"]
LAST = ["Otieno", "Wanjala", "Kiptoo", "Njoroge", "Muthoni", "Owino", "Karanja", "Mbugua",
        "Chepkoech", "Mwende", "Onyango", "Kibet", "Wairimu", "Nyongesa", "Abdi", "Langat",
        "Wangari", "Odera", "Kilonzo", "Ngugi", "Rotich", "Awino", "Gitau", "Mulwa"]
COUNTIES = [("Nairobi", 35), ("Kiambu", 12), ("Nakuru", 10), ("Mombasa", 10), ("Kisumu", 8),
            ("Uasin Gishu", 7), ("Machakos", 5), ("Kisii", 5), ("Kakamega", 4), ("Nyeri", 4)]
CATEGORIES = ["grocery", "transport", "food", "utilities", "airtime", "health", "retail", "entertainment"]
MERCHANT_NAMES = [
    "Savanna Fresh Mart", "Jua Kali Hardware", "Mto Wa Mawe Pharmacy", "Baraka Matatu Sacco", "Karibu Cafe",
    "Twiga Airtime Kiosk", "Pwani Power Tokens", "Simba Electronics", "Duka la Mama Pima", "Kijani Greens",
    "Safari Fuel Stop", "Mwangaza Water Co", "Bomet Dairy Hub", "Tembo Books", "Nyota Cinema",
    "Chai Bora Tea Room", "Zawadi Gift Shop", "Pembe Fashion", "Harambee Clinic", "Ndege Cabs",
    "Mzuka Pizza", "Kilimo Agrovet", "Upepo Laundry", "Mlima Gas Refill", "Bahari Fish Market",
    "Taa Solar Shop", "Soko Mjinga Bakery", "Wazi Internet Cafe", "Mkulima Maize Mill", "Dhahabu Salon",
    "Kioo Opticians", "Mwenge Phone Repair", "Gari Moshi Tickets", "Kasuku Pet Store", "Moto Moto Grill",
    "Rafiki Stationery", "Mwana Baby Shop", "Kaka Butchery", "Quick Forex Bureau", "Mikoko Eco Tours",
]

# A sensible category for each merchant name (the category is a descriptive attribute only; nothing else depends on it).
MERCHANT_CATEGORY = {
    "Savanna Fresh Mart": "grocery", "Jua Kali Hardware": "retail", "Mto Wa Mawe Pharmacy": "health",
    "Baraka Matatu Sacco": "transport", "Karibu Cafe": "food", "Twiga Airtime Kiosk": "airtime",
    "Pwani Power Tokens": "utilities", "Simba Electronics": "retail", "Duka la Mama Pima": "grocery",
    "Kijani Greens": "grocery", "Safari Fuel Stop": "transport", "Mwangaza Water Co": "utilities",
    "Bomet Dairy Hub": "grocery", "Tembo Books": "retail", "Nyota Cinema": "entertainment",
    "Chai Bora Tea Room": "food", "Zawadi Gift Shop": "retail", "Pembe Fashion": "retail",
    "Harambee Clinic": "health", "Ndege Cabs": "transport", "Mzuka Pizza": "food", "Kilimo Agrovet": "retail",
    "Upepo Laundry": "retail", "Mlima Gas Refill": "utilities", "Bahari Fish Market": "grocery",
    "Taa Solar Shop": "utilities", "Soko Mjinga Bakery": "food", "Wazi Internet Cafe": "utilities",
    "Mkulima Maize Mill": "grocery", "Dhahabu Salon": "retail", "Kioo Opticians": "health",
    "Mwenge Phone Repair": "retail", "Gari Moshi Tickets": "transport", "Kasuku Pet Store": "retail",
    "Moto Moto Grill": "food", "Rafiki Stationery": "retail", "Mwana Baby Shop": "retail", "Kaka Butchery": "grocery",
    "Quick Forex Bureau": "retail", "Mikoko Eco Tours": "entertainment",
}
PHONE_MODELS = ["Tecno Spark 10", "Samsung A14", "Infinix Hot 30", "Itel A60", "Nokia C21", "Xiaomi Redmi 12",
                "Oppo A17", "Samsung A05", "Tecno Camon 20"]

DISPUTE_TEMPLATES = {
    "double_charge": [
        "I was charged twice for the same purchase at {m}.",
        "The same payment of KES {a} appears two times on my statement.",
        "Duplicate debit after I tapped pay only once.",
        "My account was debited two times for a single order at {m}.",
        "Double charge on my wallet for one {m} purchase.",
        "The payment to {m} was repeated and I was billed again.",
    ],
    "not_received": [
        "I paid {m} but never received the goods.",
        "The order was paid for yet nothing was delivered.",
        "Paid for airtime at {m} and it did not arrive.",
        "Goods not delivered even though the money left my account.",
        "I have not received my purchase from {m} after paying KES {a}.",
        "Payment went through but the delivery never came.",
    ],
    "wrong_amount": [
        "I was debited KES {a} but the receipt shows a smaller figure.",
        "The amount taken is higher than the price displayed at the till.",
        "Overcharged compared with the price we agreed at {m}.",
        "The merchant took more money than I authorised.",
        "Wrong amount deducted, the shop quoted a lower price.",
        "KES {a} was charged but the agreed price was less.",
    ],
    "unauthorised": [
        "I did not make this payment, someone used my phone.",
        "A transaction I never authorised appeared on my account.",
        "Payment to {m} that I do not recognise; my device may have been stolen.",
        "Fraudulent debit on my wallet that I did not initiate.",
        "Someone else spent my money, I did not approve KES {a}.",
        "Unrecognised charge, I suspect my SIM was swapped.",
    ],
    "refund_delay": [
        "I returned the item two weeks ago and the refund has not arrived.",
        "Still waiting for my money back after {m} cancelled the order.",
        "The refund promised by the shop is overdue.",
        "Reversal of KES {a} has not been credited to my wallet yet.",
        "I was told I would get my money back but nothing has been credited.",
        "Cancelled order at {m} and the refund is late.",
    ],
    "failed_but_debited": [
        "The payment showed failed but my balance went down.",
        "The app said transaction unsuccessful, yet the money was deducted.",
        "Error message at checkout, funds were deducted anyway.",
        "Transfer failed on screen but KES {a} left my account.",
        "Declined at {m} but the amount was still taken from my wallet.",
        "It said the payment did not go through, however I was debited.",
    ],
}


def weighted_choice(rng, items):
    total = sum(w for _, w in items)
    x = rng.random() * total
    acc = 0.0
    for item, w in items:
        acc += w
        if x <= acc:
            return item
    return items[-1][0]


def hour_weights():
    # Daily rhythm (UTC+3 local time shown): morning, lunch and evening peaks
    w = [1, 1, 1, 1, 1, 2, 4, 8, 9, 7, 6, 7, 9, 8, 6, 6, 7, 9, 10, 8, 5, 3, 2, 1]
    return [(h, w[h]) for h in range(24)]


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    rng = random.Random(SEED)
    os.makedirs(OUT, exist_ok=True)

    # ---------------------------------------------------------------- customers
    customers = []
    for i in range(1, N_CUSTOMERS + 1):
        cid = f"C{i:04d}"
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        phone = f"+2547{rng.randrange(0, 100_000_000):08d}"
        county = weighted_choice(rng, COUNTIES)
        kyc = rng.choices([1, 2, 3], weights=[20, 55, 25])[0]
        if i >= 316:  # ring customers are brand new
            joined = dt.date(2026, 8, 28)
        else:
            joined = dt.date(2024, 1, 1) + dt.timedelta(days=rng.randrange(0, 900))
        # Optional attributes: present only for SOME customers (schema flexibility)
        lang = rng.choice(["en", "sw"]) if rng.random() < 0.6 else ""
        optin = rng.choice(["true", "false"]) if rng.random() < 0.4 else ""
        customers.append([cid, name, phone, county, kyc, joined.isoformat(), lang, optin])
    # make sure phone numbers are unique
    seen = set()
    for c in customers:
        while c[2] in seen:
            c[2] = f"+2547{rng.randrange(0, 100_000_000):08d}"
        seen.add(c[2])

    # ----------------------------------------------------------------- accounts
    # A0001..A0320 are each customer's main wallet (A00nn belongs to C00nn).
    # A0321..A0400 are extra BUSINESS accounts of randomly chosen customers 1..300.
    accounts = []  # [account_id, customer_id, type]
    for i in range(1, N_CUSTOMERS + 1):
        accounts.append([f"A{i:04d}", f"C{i:04d}", "WALLET"])
    for i in range(N_CUSTOMERS + 1, N_ACCOUNTS + 1):
        accounts.append([f"A{i:04d}", f"C{rng.randrange(1, 301):04d}", "BUSINESS"])
    acc_ids = [a[0] for a in accounts]

    # ---------------------------------------------------------------- merchants
    merchants = []
    for i in range(1, N_MERCHANTS + 1):
        mid = f"M{i:03d}"
        cat = "grocery" if i == 1 else rng.choice(CATEGORIES)
        # `cat` above still draws from the random generator so that every other number in the data set stays
        # exactly as before; the descriptive category is then taken from the name.
        cat = MERCHANT_CATEGORY[MERCHANT_NAMES[i - 1]]
        merchants.append([mid, MERCHANT_NAMES[i - 1], cat, weighted_choice(rng, COUNTIES)])
    merchant_name = {m[0]: m[1] for m in merchants}

    # ------------------------------------------------------------------ devices
    devices = []
    for i in range(1, N_DEVICES + 1):
        first_seen = dt.date(2024, 1, 1) + dt.timedelta(days=rng.randrange(0, 900))
        if i >= 401:
            first_seen = dt.date(2026, 8, 29)
        devices.append([f"D{i:03d}", rng.choice(PHONE_MODELS), first_seen.isoformat()])

    account_devices = []  # [account_id, device_id]
    ring = [f"A{i:04d}" for i in range(316, 321)]
    for i, a in enumerate(accounts, start=1):
        aid = a[0]
        if aid in ring:
            continue
        if aid == "A0011":
            account_devices.append([aid, "D010"])  # family phone shared with A0010
            continue
        account_devices.append([aid, f"D{i:03d}"])
        if rng.random() < 0.08:  # a few people own two phones
            j = rng.randrange(1, 391)
            if j != i:
                account_devices.append([aid, f"D{j:03d}"])
    for aid in ring:
        account_devices.append([aid, "D401"])
    for aid in ("A0317", "A0319"):
        account_devices.append([aid, "D402"])
    dev_of = {}
    for aid, did in account_devices:
        dev_of.setdefault(aid, []).append(did)

    # -------------------------------------------------------------- transactions
    contacts = {}
    for aid in acc_ids:
        k = rng.randrange(4, 9)
        contacts[aid] = rng.sample([x for x in acc_ids if x != aid and x not in ring], k)

    zipf = [(m[0], 1.0 / (i ** 1.1)) for i, m in enumerate(merchants, start=1)]
    # Quick Forex Bureau (M039) is low-volume in normal traffic
    zipf = [(m, (w * 0.2 if m == "M039" else w)) for m, w in zipf]
    activity = {}
    for aid in acc_ids:
        activity[aid] = math.exp(rng.gauss(0, 0.7))
    for aid in ring:
        activity[aid] = 0.05
    activity["A0007"] = 0.0  # A0007 is added separately below
    act_items = [(a, w) for a, w in activity.items() if w > 0]
    hours = hour_weights()

    def random_ts(first_day=0):
        d = rng.randrange(first_day, DAYS)
        h = weighted_choice(rng, hours)
        return START + dt.timedelta(days=d, hours=h, minutes=rng.randrange(0, 60), seconds=rng.randrange(0, 60))

    def amount_merchant():
        return int(min(25000, max(20, round(math.exp(rng.gauss(6.6, 0.9)), -1))))

    def amount_p2p():
        return int(min(35000, max(50, round(math.exp(rng.gauss(7.3, 1.0)) / 50) * 50)))

    def pick_status():
        return rng.choices(["SETTLED", "FAILED", "REVERSED"], weights=[97, 2, 1])[0]

    def pick_channel():
        return rng.choices(["app", "ussd", "card"], weights=[60, 25, 15])[0]

    txns = []  # [ts, from, kind, to, amount, channel, device, status]

    def add(ts, frm, kind, to, amount, channel=None, status=None, device=None):
        channel = channel or pick_channel()
        status = status or pick_status()
        if device is None:
            device = rng.choice(dev_of[frm]) if (channel != "card" and frm in dev_of) else ""
        txns.append([ts, frm, kind, to, amount, channel, device, status])

    # Planted: the fraud ring (a 4-account loop and a cash-out), 14 September 2026
    day = dt.datetime(2026, 9, 14)
    loop = [("A0316", "A0317", 48500, dt.timedelta(hours=2, minutes=10)),
            ("A0317", "A0318", 48000, dt.timedelta(hours=3, minutes=40)),
            ("A0318", "A0319", 47500, dt.timedelta(hours=5, minutes=15)),
            ("A0319", "A0316", 47000, dt.timedelta(hours=7, minutes=55))]
    for frm, to, amt, off in loop:
        add(day + off, frm, "ACCOUNT", to, amt, channel="app", status="SETTLED", device="D401")
    add(day + dt.timedelta(hours=9, minutes=20), "A0320", "MERCHANT", "M039", 46000, channel="app",
        status="SETTLED", device="D401")
    # Planted: harmless family sharing one phone (A0010/A0011) -- just normal traffic via D010
    # Planted: harmless two-hop loop A0020 <-> A0021
    add(dt.datetime(2026, 8, 3, 9, 15), "A0020", "ACCOUNT", "A0021", 1200, "app", "SETTLED")
    add(dt.datetime(2026, 8, 3, 9, 40), "A0021", "ACCOUNT", "A0020", 1200, "app", "SETTLED")
    # Planted: benign large one-off transfers (large, but no loop)
    add(dt.datetime(2026, 7, 5, 8, 30), "A0100", "ACCOUNT", "A0101", 45000, "app", "SETTLED")
    add(dt.datetime(2026, 8, 20, 12, 5), "A0150", "ACCOUNT", "A0151", 42000, "app", "SETTLED")
    add(dt.datetime(2026, 9, 2, 17, 45), "A0222", "ACCOUNT", "A0223", 40000, "app", "SETTLED")
    # Ring accounts: a few small ordinary payments after joining (they look normal at first)
    for aid in ring:
        for _ in range(3):
            add(random_ts(first_day=62), aid, "MERCHANT", weighted_choice(rng, zipf), amount_merchant())

    # A0007: very busy account -- 2,500 transactions
    for _ in range(2500):
        if rng.random() < 0.8:
            add(random_ts(), "A0007", "MERCHANT", weighted_choice(rng, zipf), amount_merchant())
        else:
            add(random_ts(), "A0007", "ACCOUNT", rng.choice(contacts["A0007"]), amount_p2p())

    # Everyone else
    while len(txns) < N_TXNS:
        frm = weighted_choice(rng, act_items)
        if frm in ring:
            continue
        if rng.random() < 0.70:
            add(random_ts(), frm, "MERCHANT", weighted_choice(rng, zipf), amount_merchant())
        else:
            if rng.random() < 0.8:
                to = rng.choice(contacts[frm])
            else:
                to = rng.choice([a for a in acc_ids if a != frm and a not in ring])
            add(random_ts(), frm, "ACCOUNT", to, amount_p2p())

    txns.sort(key=lambda t: (t[0], t[1], t[3]))
    txn_rows = []
    for n, t in enumerate(txns, start=1):
        txn_rows.append([f"T{n:06d}", iso(t[0]), t[1], t[2], t[3], t[4], t[5], t[6], t[7]])

    # ----------------------------------------------------------------- balances
    # Compute an opening balance large enough that no balance ever goes negative,
    # then store the CURRENT balance (opening + effect of SETTLED transactions).
    delta = {a: 0 for a in acc_ids}
    lowest = {a: 0 for a in acc_ids}
    for r in txn_rows:
        if r[8] != "SETTLED":
            continue
        frm, kind, to, amt = r[2], r[3], r[4], r[5]
        delta[frm] -= amt
        lowest[frm] = min(lowest[frm], delta[frm])
        if kind == "ACCOUNT":
            delta[to] += amt
    balance = {}
    for a in acc_ids:
        opening = -lowest[a] + rng.randrange(500, 5000, 10)
        balance[a] = opening + delta[a]
        assert balance[a] >= 0

    # ----------------------------------------------------------------- disputes
    settled_m = [r for r in txn_rows if r[8] == "SETTLED" and r[3] == "MERCHANT" and r[2] not in ring]
    failed = [r for r in txn_rows if r[8] == "FAILED" and r[3] == "MERCHANT" and r[2] not in ring]
    owner = {a[0]: a[1] for a in accounts}
    disputes = []
    cats = list(DISPUTE_TEMPLATES)
    n = 0
    for cat in cats:
        for k in range(10):
            pool = failed if cat == "failed_but_debited" else settled_m
            r = rng.choice(pool)
            tmpl = rng.choice(DISPUTE_TEMPLATES[cat])
            text = tmpl.format(m=merchant_name.get(r[4], "the merchant"), a=f"{r[5]:,}")
            opened = dt.datetime.strptime(r[1], "%Y-%m-%dT%H:%M:%SZ") + dt.timedelta(days=rng.randrange(1, 6),
                                                                                  hours=rng.randrange(0, 20))
            disputes.append([r[0], owner[r[2]], iso(opened), cat, text])
    rng.shuffle(disputes)
    dispute_rows = [[f"DSP{i:03d}"] + d for i, d in enumerate(disputes, start=1)]

    # -------------------------------------------------------------------- write
    def write(name, header, rows):
        with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(header)
            w.writerows(rows)

    write("customers.csv", ["customer_id", "full_name", "phone", "county", "kyc_level", "joined_on",
                            "preferred_language", "marketing_opt_in"], customers)
    write("accounts.csv", ["account_id", "customer_id", "account_type", "currency", "balance_kes"],
          [[a[0], a[1], a[2], "KES", balance[a[0]]] for a in accounts])
    write("merchants.csv", ["merchant_id", "name", "category", "county"], merchants)
    write("devices.csv", ["device_id", "model", "first_seen"], devices)
    write("account_devices.csv", ["account_id", "device_id"], account_devices)
    write("transactions.csv", ["txn_id", "ts", "from_account", "to_kind", "to_id", "amount_kes", "channel",
                               "device_id", "status"], txn_rows)
    write("disputes.csv", ["dispute_id", "txn_id", "customer_id", "opened_at", "category", "description"],
          dispute_rows)

    manifest = {"seed": SEED, "counts": {
        "customers": len(customers), "accounts": len(accounts), "merchants": len(merchants),
        "devices": len(devices), "account_devices": len(account_devices),
        "transactions": len(txn_rows), "disputes": len(dispute_rows)}, "sha256": {}}
    for fn in sorted(os.listdir(OUT)):
        if fn.endswith(".csv"):
            with open(os.path.join(OUT, fn), "rb") as f:
                manifest["sha256"][fn] = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(OUT, "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(json.dumps(manifest["counts"], indent=2))


if __name__ == "__main__":
    main()
