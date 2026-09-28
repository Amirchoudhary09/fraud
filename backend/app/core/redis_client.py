"""Shared Redis connection (optional). When REDIS_URL is unset the app uses in-process
fallbacks, which are correct only for a single API replica."""
from . import config

_client = None


def get():
    """Returns the Redis client, or None when Redis is not configured."""
    global _client
    if _client is None and config.REDIS_URL:
        import redis
        _client = redis.Redis.from_url(config.REDIS_URL, decode_responses=True, socket_timeout=10,
                                       health_check_interval=30)
    return _client


def set_client(client):
    """Tests inject a fakeredis client here."""
    global _client
    _client = client
