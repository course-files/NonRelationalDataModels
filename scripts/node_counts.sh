#!/usr/bin/env bash
# node_counts.sh -- how many rows (partitions) does EACH Cassandra node hold locally for one table?
#   bash scripts/node_counts.sh pesa.hint_demo
# It asks every running node for its own "Number of partitions (estimate)". A node that is down is reported as down.
# For a table whose partition key is the whole primary key (like hint_demo), partitions = rows.
cd "$(dirname "$0")/.."
table="${1:?usage: bash scripts/node_counts.sh <keyspace.table>}"
for n in cass1 cass2 cass3 cass4 cass5 cass6; do
  if docker compose ps --status running --services 2>/dev/null | grep -qx "$n"; then
    docker compose exec -T "$n" nodetool flush >/dev/null 2>&1      # write memtables to disk so the estimate is complete
    c=$(docker compose exec -T "$n" nodetool tablestats "$table" 2>/dev/null | awk -F': ' '/Number of partitions \(estimate\)/ {print $2}')
    printf '%-6s holds %s partitions of %s\n' "$n" "${c:-?}" "$table"
  fi
done
