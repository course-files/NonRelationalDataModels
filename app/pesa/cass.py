"""
cass.py -- one place that knows how to connect to Cassandra.

Why a helper? The Python driver has many options; the labs only need three:
  * which contact points to use,
  * which consistency level to use by default,
  * (Lab 3) optionally, force every request through ONE chosen coordinator node.
"""
import socket
import time

from cassandra import ConsistencyLevel
from cassandra.cluster import EXEC_PROFILE_DEFAULT, Cluster, ExecutionProfile, NoHostAvailable
from cassandra.policies import DCAwareRoundRobinPolicy, HostFilterPolicy, RoundRobinPolicy, TokenAwarePolicy

from .config import CASS_HOSTS

CL = {
    "ANY": ConsistencyLevel.ANY, "ONE": ConsistencyLevel.ONE, "TWO": ConsistencyLevel.TWO,
    "THREE": ConsistencyLevel.THREE, "QUORUM": ConsistencyLevel.QUORUM, "ALL": ConsistencyLevel.ALL,
    "LOCAL_ONE": ConsistencyLevel.LOCAL_ONE, "LOCAL_QUORUM": ConsistencyLevel.LOCAL_QUORUM,
}


def connect(hosts=None, cl="QUORUM", via=None, local_dc="dc1", wait_seconds=180, timeout=30):
    """Return (cluster, session). Retries until the cluster accepts connections.

    via: name of ONE node (for example "cass4"). When given, every request is sent to that node
         as coordinator; the node then talks to the replicas on our behalf.
    """
    hosts = hosts or CASS_HOSTS
    if via:
        # The node we want to use as coordinator must also be the CONTACT POINT. If the contact point is another
        # node, the driver's control connection is filtered out by the policy below and no connection can be made.
        hosts = [via]
        ip = socket.gethostbyname(via)
        lbp = HostFilterPolicy(child_policy=RoundRobinPolicy(), predicate=lambda h: h.address == ip)
    else:
        lbp = TokenAwarePolicy(DCAwareRoundRobinPolicy(local_dc=local_dc))
    profile = ExecutionProfile(load_balancing_policy=lbp, consistency_level=CL[cl], request_timeout=timeout)
    deadline = time.time() + wait_seconds
    while True:
        cluster = Cluster(contact_points=hosts, execution_profiles={EXEC_PROFILE_DEFAULT: profile})
        try:
            return cluster, cluster.connect()
        except NoHostAvailable:
            cluster.shutdown()
            if time.time() > deadline:
                raise
            print("waiting for Cassandra to accept connections ...", flush=True)
            time.sleep(5)
