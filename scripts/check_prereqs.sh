#!/usr/bin/env bash
# check_prereqs.sh -- run this ONCE before Lab 1. It checks that your computer can run the labs.
# Usage:  bash scripts/check_prereqs.sh
set -u
ok=1
say() { printf '%-58s %s\n' "$1" "$2"; }

if command -v docker >/dev/null 2>&1; then
  say "Docker is installed" "OK ($(docker --version 2>/dev/null | cut -d, -f1))"
else
  say "Docker is installed" "MISSING -> install Docker Desktop (Windows/macOS) or Docker Engine (Linux)"; ok=0
fi

if docker compose version >/dev/null 2>&1; then
  say "Docker Compose v2 is available" "OK ($(docker compose version --short 2>/dev/null))"
else
  say "Docker Compose v2 is available" "MISSING -> update Docker Desktop (the command is 'docker compose', with a space)"; ok=0
fi

if docker info >/dev/null 2>&1; then
  say "Docker daemon is running" "OK"
  mem_bytes=$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
  mem_gb=$(( mem_bytes / 1024 / 1024 / 1024 ))
  if [ "$mem_gb" -ge 10 ]; then
    say "Memory available to Docker" "OK (${mem_gb} GB)"
  elif [ "$mem_gb" -ge 7 ]; then
    say "Memory available to Docker" "LOW (${mem_gb} GB) -> labs 1, 3B and 4 will run; for Cassandra (labs 2, 3A) raise it to 10 GB or use the simulator track"
  else
    say "Memory available to Docker" "TOO LOW (${mem_gb} GB) -> Docker Desktop > Settings > Resources > Memory: set 10 GB (12 GB is better)"; ok=0
  fi
else
  say "Docker daemon is running" "NOT RUNNING -> start Docker Desktop and wait until it says 'running'"; ok=0
fi

# ports used on your computer (all bound to 127.0.0.1)
for port in 5440 6390 27040 9142 7474 7687; do
  if (command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":${port} ") || \
     (command -v lsof >/dev/null 2>&1 && lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1); then
    say "Port ${port} is free" "IN USE -> stop the program using it, or edit the port in docker-compose.yml"; ok=0
  else
    say "Port ${port} is free" "OK"
  fi
done

df_gb=$(df -Pk . 2>/dev/null | awk 'NR==2 {printf "%d", $4/1024/1024}')
if [ -n "${df_gb:-}" ]; then
  if [ "$df_gb" -ge 15 ]; then say "Free disk space here" "OK (${df_gb} GB)"; else say "Free disk space here" "LOW (${df_gb} GB) -> the images need about 8 GB, and the data needs more; 15 GB free is comfortable"; fi
fi

echo
if [ "$ok" = 1 ]; then echo "Your computer is ready. Next: docker compose --profile lab1 up -d --build"; else echo "Fix the items marked above, then run this script again."; exit 1; fi
