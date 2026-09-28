"""Redis backends (rate limit + reliable job queue). Uses fakeredis locally; CI also runs this
file against a real Redis service by setting TEST_REDIS_URL."""
import json
import os

import fakeredis
import pytest
from fastapi import HTTPException

from app.core import config, ratelimit, redis_client
from app.workers import jobs

REQ = {"identity": {"name": "Queue Person", "company": "WASP3D"}, "purpose": "research", "acknowledged": True}


@pytest.fixture
def redis_backend(monkeypatch):
    url = os.getenv("TEST_REDIS_URL")
    if url:
        import redis
        r = redis.Redis.from_url(url, decode_responses=True)
    else:
        r = fakeredis.FakeRedis(decode_responses=True)
    r.flushdb()
    redis_client.set_client(r)
    monkeypatch.setattr(config, "JOBS_INLINE", False)
    yield r
    redis_client.set_client(None)
    r.flushdb()


def test_shared_rate_limit(redis_backend):
    for _ in range(3):
        ratelimit.check("user:1", limit=3, window=60)
    with pytest.raises(HTTPException) as e:
        ratelimit.check("user:1", limit=3, window=60)
    assert e.value.status_code == 429
    ratelimit.check("user:2", limit=3, window=60)  # other keys unaffected
    assert redis_backend.zcard("ie:rl:user:1") == 3  # rejected attempt not counted


def test_search_runs_through_redis_worker(client, analyst_h, redis_backend):
    sid = client.post("/api/searches", json=REQ, headers=analyst_h).json()["id"]
    assert client.get(f"/api/searches/{sid}", headers=analyst_h).json()["status"] == "queued"
    assert redis_backend.llen(jobs.QUEUE) == 1

    worker = jobs.RedisWorker(redis_backend, "w1")
    assert worker.run_once(timeout=1) is True
    s = client.get(f"/api/searches/{sid}", headers=analyst_h).json()
    assert s["status"] == "completed" and s["candidate_count"] == 3
    assert redis_backend.llen(jobs.QUEUE) == 0 and redis_backend.llen(worker.processing) == 0
    assert worker.run_once(timeout=1) is False  # queue empty


def test_jobs_of_dead_worker_are_requeued(redis_backend, monkeypatch):
    ran = []
    monkeypatch.setitem(jobs.REGISTRY, "probe", lambda x: ran.append(x))
    raw = json.dumps({"id": "j1", "name": "probe", "args": [42]})
    # a worker took the job, then died without a heartbeat
    redis_backend.lpush(jobs.PROCESSING + "dead-worker", raw)

    alive = jobs.RedisWorker(redis_backend, "alive")
    alive.heartbeat()
    assert alive.recover_orphans() == 1
    assert alive.run_once(timeout=1) and ran == [42]


def test_live_worker_jobs_are_not_stolen(redis_backend):
    busy = jobs.RedisWorker(redis_backend, "busy")
    busy.heartbeat()
    redis_backend.lpush(busy.processing, json.dumps({"id": "j2", "name": "run_search", "args": []}))
    assert jobs.RedisWorker(redis_backend, "other").recover_orphans() == 0


def test_unknown_job_names_are_rejected():
    with pytest.raises(KeyError):
        jobs.submit("rm_rf", "/")
