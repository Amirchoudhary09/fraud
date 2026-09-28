"""Standalone job worker for the Redis queue:  python -m app.workers.worker
Run it as a separate service (e.g. a second Railway service from the same backend image)."""
import logging
import sys

from ..core import audit_store, config, database, redis_client
from .jobs import RedisWorker


def main():
    logging.basicConfig(level=logging.INFO)
    r = redis_client.get()
    if r is None:
        sys.exit("REDIS_URL is not set: the API runs jobs in-process, no separate worker is needed.")
    database.init()
    audit_store.init()
    logging.getLogger(__name__).info("mock mode: %s", config.MOCK_MODE)
    RedisWorker(r).run_forever()


if __name__ == "__main__":
    main()
