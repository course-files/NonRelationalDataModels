#!/bin/bash
# =====================================================================
# cassandra-entrypoint.sh -- a thin wrapper around the official image's
# own entrypoint.
#
# It does exactly one extra thing: when the environment variable
# AUTO_BOOTSTRAP is "false", it appends the line "auto_bootstrap: false"
# to cassandra.yaml. That setting is NOT in the default file, so it has to be
# added. (Lab 3 uses it to reproduce the Monzo incident on purpose.)
# For every other node nothing is changed.
# =====================================================================
set -e
CONF="${CASSANDRA_CONFIG:-/etc/cassandra}"

if [ "${AUTO_BOOTSTRAP:-true}" = "false" ]; then
  if ! grep -q '^auto_bootstrap:' "$CONF/cassandra.yaml"; then
    echo "auto_bootstrap: false" >> "$CONF/cassandra.yaml"
  fi
  echo "*** LAB NOTICE: this node starts with auto_bootstrap: false (it will NOT stream data) ***"
fi

exec docker-entrypoint.sh "$@"
