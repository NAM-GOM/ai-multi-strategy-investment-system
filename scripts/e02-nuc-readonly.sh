#!/usr/bin/env bash
# Inventory only. Does not start services, open a writable DB, source keys or install software.
set -euo pipefail
release_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$release_dir"
date --utc --iso-8601=seconds
id
ps -eo user,pid,etimes,comm,args | grep -E '[t]rading_system|[t]mux' || true
systemctl list-units --all --type=service --no-pager --plain | grep -Ei 'crypto|collector|observer' || true
for unit in crypto-market-collector crypto-strategy-observer crypto-testnet-bridge crypto-t1-testnet-executor; do
  systemctl show "$unit.service" --no-pager -p LoadState -p ActiveState -p SubState -p User -p Group -p FragmentPath
done
for item in \
  /var/lib/CryptoAutoTrading/state/continuous-01/collector/health.json \
  /var/lib/CryptoAutoTrading/state/continuous-01/observer/health.json \
  /var/lib/CryptoAutoTrading/state/continuous-01/bridge/latest-preview.json; do
  if [[ -f "$item" ]]; then cat -- "$item"; fi
done
stat -c '%U %G %a %n' /var/lib/CryptoAutoTrading/state/testnet-e01 \
  /var/lib/CryptoAutoTrading/state/testnet-e01/testnet_execution.sqlite
bash "$release_dir/scripts/e02-runtime.sh" preflight
bash "$release_dir/scripts/e02-runtime.sh" status
