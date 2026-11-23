#!/usr/bin/env bash
# verify.sh -- run the self-check of one lab.
#   bash scripts/verify.sh 1        (or 2, 3, 4, capstone)
cd "$(dirname "$0")/.." || exit 1
lab="${1:-}"
case "$lab" in
  1|2|3|4|capstone) ;;
  *) echo "usage: bash scripts/verify.sh 1|2|3|4|capstone"; exit 2 ;;
esac
docker compose exec workbench python app/verify_lab.py "$lab"
