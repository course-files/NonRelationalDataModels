#!/usr/bin/env python3
"""
lab3_pipeline.py -- a miniature of the Stackdriver pipeline (Lab 3, Part B), built on Redis Streams.

        sensors --> [ gateway ] --> broker --> archive consumer   (keeps the raw record)
                                          \\--> alerting consumer  (raises alarms; must stay fresh)
                                           \\-> tsdb consumer      (writes the time-series database,
                                                                    the "Cassandra" of this story)

At second FAIL_AT the tsdb consumer's database "goes down": the consumer stops acknowledging
messages. At second RECOVER_AT it comes back. The question is what happens to everybody else.

Three broker designs (--design):

  shared-block  ONE stream shared by all consumers, and the gateway BLOCKS (stops accepting
                measurements) while any consumer's backlog is above the buffer capacity.
                This is the Stackdriver failure: protection that sits on a shared path.

  shared-drop   ONE stream capped at the buffer capacity with XADD ... MAXLEN ~ N. The gateway
                never blocks, but the oldest entries are trimmed even if a slow consumer has not
                read them yet.

  isolated      ONE STREAM PER CONSUMER, each with its own cap; the archive stream keeps everything.
                A failing consumer can only hurt itself, and when it recovers it REPLAYS what it
                missed from the archive stream.

Every message gets the explicit stream id "<sequence>-0", so message number n has the same offset in
every stream; that is what makes replay-from-archive simple.

Examples
  python app/lab3_pipeline.py --design shared-block
  python app/lab3_pipeline.py --design shared-drop
  python app/lab3_pipeline.py --design isolated
  python app/lab3_pipeline.py --design isolated --fail-at 5 --recover-at 0     # never recovers
"""
import argparse
import threading
import time

import redis

from pesa.config import REDIS_HOST, REDIS_PORT

CONSUMERS = {
    # name: cost in seconds to process one message (so capacity = 1 / cost messages per second)
    "archive": 1 / 3000,
    "alerting": 1 / 2000,
    "tsdb": 1 / 1500,
}
BATCH = 100


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.processed = {c: set() for c in CONSUMERS}
        self.last_ts = {c: time.time() for c in CONSUMERS}   # publish time of the newest message handled
        self.max_stale = {c: 0.0 for c in CONSUMERS}         # longest time a consumer went without NEW data
        self.max_backlog = {c: 0 for c in CONSUMERS}
        self.accepted = 0
        self.offered = 0
        self.replayed = 0
        self.gaps_found = 0


def stream_for(design, consumer):
    if design == "isolated":
        return f"pipe:{consumer}"
    return "pipe:shared"


def seq_of(stream_id):
    """Stream ids in this lab are '<sequence>-0', so the sequence number is the part before the dash."""
    return int(stream_id.split("-")[0])


def backlog(r, design, consumer):
    """Messages the consumer still has to finish: entries that EXIST in the stream but have not been
    delivered to it, plus entries delivered but not yet acknowledged (pending).

    Why not simply read the 'lag' field of XINFO GROUPS? After old entries are trimmed away, 'lag'
    can keep counting entries that no longer exist. Because our ids are consecutive sequence numbers
    we can compute the true figure from the first and last ids still in the stream."""
    key = stream_for(design, consumer)
    info = r.xinfo_stream(key)
    first = info.get("first-entry")
    last_seq = seq_of(info["last-generated-id"])
    first_seq = seq_of(first[0]) if first else last_seq + 1
    for g in r.xinfo_groups(key):
        if g["name"] == consumer:
            delivered = seq_of(g["last-delivered-id"])
            undelivered_existing = max(0, last_seq - max(delivered, first_seq - 1))
            return undelivered_existing + int(g["pending"])
    return 0


def is_down(r, consumer):
    return r.exists(f"chaos:{consumer}:down") == 1


def consumer_loop(name, design, stats, stop, t_start, caps):
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    key = stream_for(design, name)
    cost = CONSUMERS[name]
    expected = 1                                    # next sequence number we expect to see
    gaps = []                                       # missing ranges to replay from the archive

    def handle(batch_entries, replay=False):
        nonlocal expected
        time.sleep(len(batch_entries) * cost)
        now = time.time()
        with stats.lock:
            for _id, fields in batch_entries:
                seq = int(fields["seq"])
                stats.processed[name].add(seq)
                stats.last_ts[name] = max(stats.last_ts[name], float(fields["ts"]))
            if replay:
                stats.replayed += len(batch_entries)

    while not stop.is_set():
        # Part of the "database is down" behaviour: the consumer cannot make progress.
        if is_down(r, name):
            time.sleep(0.05)
            continue

        # After recovery, the isolated design replays the gaps from the archive stream.
        if gaps and design == "isolated" and name != "archive":
            lo, hi = gaps.pop(0)
            cur = lo
            while cur <= hi and not stop.is_set() and not is_down(r, name):
                top = min(cur + 499, hi)
                chunk = r.xrange("pipe:archive", f"{cur}-0", f"{top}-0")
                if chunk:
                    handle(chunk, replay=True)
                cur = top + 1
            continue

        resp = r.xreadgroup(name, "c1", {key: ">"}, count=BATCH, block=200)
        if not resp:
            continue
        entries = resp[0][1]
        seqs = [int(f["seq"]) for _, f in entries]
        if seqs[0] > expected:                      # entries between expected and seqs[0]-1 were trimmed
            gaps.append((expected, seqs[0] - 1))
            with stats.lock:
                stats.gaps_found += 1
        expected = seqs[-1] + 1

        # "write to the database": blocked while it is down. Nothing is acknowledged meanwhile.
        while is_down(r, name) and not stop.is_set():
            time.sleep(0.05)
        handle(entries)
        r.xack(key, name, *[i for i, _ in entries])


def producer_loop(design, rate, cap, duration, stats, stop, t_start):
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    seq = 0
    tick = 0.01
    total = int(rate * duration)          # the sensors offer exactly rate x duration measurements
    sent = 0                              # measurements offered so far
    while sent < total:
        # How many measurements are DUE by now? If this machine is slow, the next batch is simply bigger, so the
        # offered load stays at the nominal rate and does not depend on the speed of the computer.
        elapsed = time.perf_counter() - t_start
        due = min(total, int(rate * elapsed)) - sent
        if due <= 0:
            time.sleep(tick / 2)
            continue
        with stats.lock:
            stats.offered += due
        sent += due

        if design == "shared-block":
            worst = max(backlog(r, design, c) for c in CONSUMERS)
            if worst >= cap:                        # the shared buffer is full: refuse the measurements
                time.sleep(tick)
                continue

        pipe = r.pipeline(transaction=False)
        now = time.time()
        for _ in range(due):
            seq += 1
            fields = {"seq": seq, "ts": now}
            sid = f"{seq}-0"
            if design == "shared-block":
                pipe.xadd("pipe:shared", fields, id=sid)
            elif design == "shared-drop":
                pipe.xadd("pipe:shared", fields, id=sid, maxlen=cap, approximate=True)
            else:  # isolated: one entry per consumer path, each path with its own cap
                for c in CONSUMERS:
                    big = 10 * cap if c == "archive" else cap
                    pipe.xadd(f"pipe:{c}", fields, id=sid, maxlen=big, approximate=True)
        pipe.execute()
        with stats.lock:
            stats.accepted += due
    return time.perf_counter()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--design", choices=["shared-block", "shared-drop", "isolated"], required=True)
    ap.add_argument("--rate", type=int, default=1000, help="measurements per second offered by the sensors")
    ap.add_argument("--cap", type=int, default=5000, help="buffer capacity per path (messages)")
    ap.add_argument("--duration", type=int, default=40, help="seconds of traffic")
    ap.add_argument("--fail-at", type=int, default=5, help="second at which the tsdb database fails")
    ap.add_argument("--recover-at", type=int, default=15, help="second at which it recovers (0 = never)")
    ap.add_argument("--drain", type=int, default=15, help="extra seconds to let consumers catch up at the end")
    ap.add_argument("--every", type=int, default=2, help="print a status line every N seconds")
    a = ap.parse_args()

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    for k in r.scan_iter("pipe:*"):
        r.delete(k)
    for k in r.scan_iter("chaos:*"):
        r.delete(k)

    streams = ["pipe:shared"] if a.design != "isolated" else [f"pipe:{c}" for c in CONSUMERS]
    for s in streams:
        for c in CONSUMERS:
            if a.design == "isolated" and s != f"pipe:{c}":
                continue
            r.xgroup_create(s, c, id="0", mkstream=True)
    # mkstream creates an empty stream; the group starts from id 0 so it sees every entry

    stats = Stats()
    stop = threading.Event()
    t_start = time.perf_counter()
    threads = [threading.Thread(target=consumer_loop, args=(c, a.design, stats, stop, t_start, a.cap), daemon=True)
               for c in CONSUMERS]
    for t in threads:
        t.start()
    prod = threading.Thread(target=producer_loop, args=(a.design, a.rate, a.cap, a.duration, stats, stop, t_start),
                            daemon=True)
    prod.start()

    print(f"design={a.design}  rate={a.rate}/s  buffer cap={a.cap}  tsdb fails at t={a.fail_at}s"
          f"{', recovers at t=' + str(a.recover_at) + 's' if a.recover_at else ', never recovers'}")
    expected_fill = a.cap / a.rate
    print(f"expected time for the failed consumer's buffer to fill after the failure: cap/(lambda-mu) = "
          f"{a.cap}/{a.rate} = {expected_fill:.1f} s")
    header = f"{'t(s)':>4} {'accepted':>8} | " + " | ".join(f"{c:>8} {'done':>6} {'backlog':>7}" for c in CONSUMERS) + \
             f" | {'alerting blind(s)':>17}"
    print(header)

    failed = recovered = False
    last_done = {c: 0 for c in CONSUMERS}
    t_end = a.duration + a.drain
    while True:
        time.sleep(1.0)
        t = int(round(time.perf_counter() - t_start))
        if not failed and t >= a.fail_at:
            r.set("chaos:tsdb:down", 1)
            failed = True
            print(f"{t:>4} *** tsdb database goes DOWN")
        if a.recover_at and failed and not recovered and t >= a.recover_at:
            r.delete("chaos:tsdb:down")
            recovered = True
            print(f"{t:>4} *** tsdb database is back UP")
        row = []
        with stats.lock:
            accepted = stats.accepted
            done = {c: len(stats.processed[c]) for c in CONSUMERS}
            stale = {c: time.time() - stats.last_ts[c] for c in CONSUMERS}
            if t <= a.duration:                      # only count staleness while sensors are still sending
                for c in CONSUMERS:
                    stats.max_stale[c] = max(stats.max_stale[c], stale[c])
        for c in CONSUMERS:
            b = backlog(r, a.design, c)
            stats.max_backlog[c] = max(stats.max_backlog[c], b)
            row.append(f"{done[c] - last_done[c]:>8}/s {done[c]:>6} {b:>7}")
            last_done[c] = done[c]
        blind = f"{stale['alerting']:>17.1f}" if t <= a.duration else f"{'(traffic stopped)':>17}"
        if t % a.every == 0 or t >= t_end:
            print(f"{t:>4} {accepted:>8} | " + " | ".join(row) + f" | {blind}")
        if t >= t_end:
            break
    stop.set()
    time.sleep(0.3)

    print("\n=== summary ===")
    print(f"offered by the sensors : {stats.offered}")
    print(f"accepted by the gateway: {stats.accepted}   (refused at the edge: {stats.offered - stats.accepted})")
    for c in CONSUMERS:
        got = len(stats.processed[c])
        print(f"{c:>9}: processed {got:6d}  missing {stats.accepted - got:6d} of accepted  "
              f"| worst backlog {stats.max_backlog[c]:6d}  | longest time without new data {stats.max_stale[c]:5.1f} s")
    if a.design == "isolated":
        print(f"replayed from the archive by the tsdb consumer: {stats.replayed}   (gaps detected: {stats.gaps_found})")
    for k in r.scan_iter("chaos:*"):
        r.delete(k)


if __name__ == "__main__":
    main()
