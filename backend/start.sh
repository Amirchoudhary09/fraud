#!/bin/sh
# Container entrypoint.
#   ./start.sh          API server on $PORT, dual-stack IPv6 + IPv4 (see app/serve.py)
#   ./start.sh worker   Redis job worker (only when REDIS_URL is set)
set -e
if [ "$1" = "worker" ]; then
  exec python -m app.workers.worker
fi
exec python -m app.serve
