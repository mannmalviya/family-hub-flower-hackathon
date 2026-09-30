#!/usr/bin/env bash
# Start the local SuperLink, register the family nodes by name, start the nodes.
set -euo pipefail
cd "$(dirname "$0")"

docker compose -f compose.local.yaml up -d superlink
sleep 5

for name in Mann Bro Dad Mom; do
  key="keys/supernode-${name,,}.pub"
  if out=$(uvx --from flwr==1.39.0 flwr supernode register "$key" local-deploy --name="$name" 2>&1); then
    echo "Registered $name"
  elif grep -q "already in use" <<<"$out"; then
    echo "$name already registered"
  else
    echo "$out"; exit 1
  fi
done

docker compose -f compose.local.yaml up -d
