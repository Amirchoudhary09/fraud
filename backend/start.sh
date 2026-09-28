#!/bin/sh
# Bind to "::" (IPv6 + IPv4) when the container has IPv6, as Railway private networking needs;
# fall back to 0.0.0.0 where IPv6 is disabled (e.g. Docker's default bridge network).
set -e
if [ -z "$HOST" ]; then
  if [ "$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6 2>/dev/null || echo 1)" = "0" ]; then HOST="::"; else HOST="0.0.0.0"; fi
fi
if [ "$1" = "worker" ]; then
  exec python -m app.workers.worker
fi
exec uvicorn app.main:app --host "$HOST" --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
