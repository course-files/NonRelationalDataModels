#!/usr/bin/env bash
# reset_lab.sh -- put the labs back to a clean state.
#   bash scripts/reset_lab.sh           stop everything and DELETE all lab data (databases start empty next time)
#   bash scripts/reset_lab.sh soft      stop everything but KEEP the data
# Your written work in my_work/ is never touched.
set -eu
cd "$(dirname "$0")/.."
PROFILES="--profile lab1 --profile lab2 --profile lab3a --profile lab3b --profile lab4 --profile capstone --profile joiners --profile kafka"
if [ "${1:-}" = "soft" ]; then
  docker compose $PROFILES down
  echo "Stopped. Data volumes kept."
else
  echo "This deletes every database volume of the labs (PostgreSQL, Redis, MongoDB, Cassandra, Neo4j)."
  read -r -p "Type yes to continue: " a
  [ "$a" = "yes" ] || { echo "Cancelled."; exit 1; }
  docker compose $PROFILES down -v
  rm -rf chroma_data
  echo "Clean. Next start of a profile re-creates the databases from scratch."
fi
