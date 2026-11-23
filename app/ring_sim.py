#!/usr/bin/env python3
"""
ring_sim.py -- a small simulator of a Cassandra token ring (Lab 3).

It answers one question: "if some nodes own data they do not hold (they are
EMPTY), how many keys can return 'not found' at QUORUM?"

It reproduces the real mechanics you met in Session 3:
  * each node owns several token positions on a ring (vnodes);
  * a key is hashed with Murmur3 to a token; the key is stored on the node that
    owns the next token clockwise, then on the next DISTINCT nodes clockwise
    until replication factor (RF) nodes are chosen;
  * QUORUM = floor(RF/2) + 1 replicas must answer.

Three sub-commands

  hyper    the closed-form (hypergeometric) estimate used on the Session 4 slides
  demo     a simulated ring of your own design (no Cassandra needed)
  cluster  reads the REAL tokens from a running Cassandra cluster and predicts
           which keys are at risk (used in Lab 3, Part A)

Examples
  python app/ring_sim.py hyper   --nodes 27 --empty 6 --rf 3
  python app/ring_sim.py demo    --nodes 5  --empty 2 --rf 3 --vnodes 16 --seed 7
  python app/ring_sim.py cluster --nodes cass1,cass2,cass3,cass4,cass5 --empty cass4,cass5 --keys 3000
"""
import argparse
import bisect
import itertools
import math
import random
import socket

import mmh3

MIN_TOKEN = -(2 ** 63)
MAX_TOKEN = 2 ** 63 - 1


def token_of(key):
    """Cassandra's Murmur3Partitioner token for a text partition key."""
    return mmh3.hash64(key.encode("utf-8"), 0, True, True)[0]


class Ring:
    def __init__(self):
        self._pairs = []
        self._tokens = []
        self._nodes = []

    def add_node(self, node, tokens):
        self._pairs.extend((t, node) for t in tokens)
        self._pairs.sort()
        self._tokens = [t for t, _ in self._pairs]
        self._nodes = [n for _, n in self._pairs]

    def node_names(self):
        return sorted(set(self._nodes))

    def replicas(self, key, rf):
        """Nodes holding `key`, in ring order (first = primary replica)."""
        i = bisect.bisect_left(self._tokens, token_of(key))
        n = len(self._tokens)
        chosen = []
        for j in range(n):
            node = self._nodes[(i + j) % n]
            if node not in chosen:
                chosen.append(node)
                if len(chosen) == rf:
                    break
        return chosen

    def ownership(self):
        """Fraction of the ring (primary ranges only) owned by each node."""
        span = {}
        n = len(self._tokens)
        for i in range(n):
            prev = self._tokens[i - 1]
            cur = self._tokens[i]
            width = (cur - prev) % (2 ** 64)
            span[self._nodes[i]] = span.get(self._nodes[i], 0) + width
        total = float(2 ** 64)
        return {k: v / total for k, v in span.items()}


def hypergeom(total_nodes, empty_nodes, rf):
    """P(exactly e of a key's RF replicas are empty), if replicas are RF random distinct nodes."""
    out = {}
    denom = math.comb(total_nodes, rf)
    for e in range(0, rf + 1):
        out[e] = math.comb(empty_nodes, e) * math.comb(total_nodes - empty_nodes, rf - e) / denom
    return out


def analyse(ring, keys, rf, empty):
    """Count keys by number of empty replicas and estimate QUORUM failures."""
    quorum = rf // 2 + 1
    counts = {e: 0 for e in range(rf + 1)}
    at_risk = []
    for k in keys:
        reps = ring.replicas(k, rf)
        e = sum(1 for r in reps if r in empty)
        counts[e] += 1
        if rf - e < quorum:          # fewer non-empty replicas than a quorum needs
            at_risk.append((k, reps))
    return counts, at_risk


def expected_quorum_failures(counts, rf):
    """Model: the coordinator contacts `quorum` replicas chosen uniformly at random.
    A read fails only if ALL contacted replicas are empty."""
    quorum = rf // 2 + 1
    total = sum(counts.values())
    exp = 0.0
    for e, c in counts.items():
        exp += c * (math.comb(e, quorum) / math.comb(rf, quorum))
    return exp / total if total else 0.0


def print_report(ring, keys, rf, empty):
    counts, at_risk = analyse(ring, keys, rf, empty)
    n = len(keys)
    quorum = rf // 2 + 1
    print(f"nodes: {len(ring.node_names())} ({len(empty)} empty)  RF={rf}  QUORUM={quorum}  keys={n}")
    own = ring.ownership()
    print("ring ownership (primary ranges):  " +
          "  ".join(f"{k}={100 * v:.1f}%{'*' if k in empty else ''}" for k, v in sorted(own.items())))
    print("empty replicas per key:")
    for e in range(rf + 1):
        print(f"   {e} of {rf} replicas empty : {counts[e]:6d} keys  ({100 * counts[e] / n:5.2f}%)")
    ge1 = sum(counts[e] for e in range(1, rf + 1))
    print(f"   at least one empty replica : {100 * ge1 / n:5.2f}%")
    print(f"   AT RISK at QUORUM (empty replicas >= {quorum}) : {len(at_risk)} keys ({100 * len(at_risk) / n:.2f}%)")
    print(f"   model: expected 'not found' rate if the coordinator picks {quorum} replicas at random: "
          f"{100 * expected_quorum_failures(counts, rf):.2f}% of reads")
    return at_risk


def cmd_hyper(a):
    h = hypergeom(a.nodes, a.empty, a.rf)
    quorum = a.rf // 2 + 1
    print(f"{a.nodes} nodes in total, {a.empty} empty, RF={a.rf}  (replicas = {a.rf} random distinct nodes)")
    for e in range(a.rf + 1):
        print(f"   exactly {e} empty replica(s): {100 * h[e]:7.3f}%")
    print(f"   at least 1 empty          : {100 * (1 - h[0]):7.3f}%")
    print(f"   at least {quorum} empty (QUORUM can fail): {100 * sum(h[e] for e in range(quorum, a.rf + 1)):7.3f}%")


def cmd_demo(a):
    rng = random.Random(a.seed)
    ring = Ring()
    names = [f"n{i + 1:02d}" for i in range(a.nodes)]
    for nm in names:
        ring.add_node(nm, [rng.randrange(MIN_TOKEN, MAX_TOKEN) for _ in range(a.vnodes)])
    empty = set(names[-a.empty:]) if a.empty else set()
    keys = [f"W{i:05d}" for i in range(1, a.keys + 1)]
    print_report(ring, keys, a.rf, empty)
    h = hypergeom(a.nodes, a.empty, a.rf)
    q = a.rf // 2 + 1
    print(f"   (closed-form estimate of 'empty >= {q}': {100 * sum(h[e] for e in range(q, a.rf + 1)):.2f}%)")


def cmd_cluster(a):
    from cassandra.cluster import Cluster

    names = [x.strip() for x in a.nodes.split(",")]
    empty = {x.strip() for x in a.empty.split(",")} if a.empty else set()
    ip_to_name = {socket.gethostbyname(nm): nm for nm in names}

    cluster = Cluster(a.hosts.split(","))
    cluster.connect()
    tmap = cluster.metadata.token_map
    per_node = {}
    for tok, host in tmap.token_to_host_owner.items():
        nm = ip_to_name.get(host.address)
        if nm is None:
            raise SystemExit(f"cluster has a node at {host.address} that is not in --nodes {a.nodes}")
        per_node.setdefault(nm, []).append(tok.value)
    ring = Ring()
    for nm, toks in per_node.items():
        ring.add_node(nm, toks)
    print("tokens read from the live cluster: " +
          ", ".join(f"{nm}={len(t)}" for nm, t in sorted(per_node.items())))
    keys = [f"W{i:05d}" for i in range(1, a.keys + 1)]

    # Self-check: does the simulator choose the same replicas as the driver (and therefore Cassandra)?
    agree = 0
    sample = keys[:20]
    for k in sample:
        driver_reps = {ip_to_name[h.address] for h in cluster.metadata.get_replicas(a.keyspace, k.encode("utf-8"))}
        agree += driver_reps == set(ring.replicas(k, a.rf))
    print(f"self-check: simulator and driver choose the same replicas for {agree} of {len(sample)} sample keys")
    at_risk = print_report(ring, keys, a.rf, empty)
    if a.show and at_risk:
        print("first at-risk keys (key -> replicas):")
        for k, reps in at_risk[:a.show]:
            print(f"   {k} -> {', '.join(r + ('*' if r in empty else '') for r in reps)}")
    cluster.shutdown()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("hyper")
    p.add_argument("--nodes", type=int, required=True)
    p.add_argument("--empty", type=int, required=True)
    p.add_argument("--rf", type=int, default=3)
    p.set_defaults(fn=cmd_hyper)

    p = sub.add_parser("demo")
    p.add_argument("--nodes", type=int, default=5)
    p.add_argument("--empty", type=int, default=2)
    p.add_argument("--rf", type=int, default=3)
    p.add_argument("--vnodes", type=int, default=16)
    p.add_argument("--keys", type=int, default=3000)
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("cluster")
    p.add_argument("--hosts", default="cass1")
    p.add_argument("--nodes", required=True, help="comma-separated node host names, e.g. cass1,cass2,cass3,cass4,cass5")
    p.add_argument("--empty", default="", help="comma-separated names of the nodes that hold no data")
    p.add_argument("--keyspace", default="monzo_lab")
    p.add_argument("--keys", type=int, default=3000)
    p.add_argument("--rf", type=int, default=3)
    p.add_argument("--show", type=int, default=8, help="how many at-risk keys to list")
    p.set_defaults(fn=cmd_cluster)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
