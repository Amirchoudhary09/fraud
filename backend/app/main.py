"""FastAPI application: wiring only. Business logic lives in services/ and agents/."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import middleware
from .api.routes import admin, auth, cases, me, searches
from .core import audit_store, config, database
from .services import retention
from .workers import jobs

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init()
    audit_store.init()
    jobs.fail_interrupted()
    retention.purge()
    jobs.start()
    yield
    jobs.stop()


app = FastAPI(title="Public Identity & Evidence Intelligence API", version="0.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"],
                   expose_headers=["Content-Disposition", "X-Request-ID", "X-Evidence-SHA256"])
middleware.install(app)


@app.get("/api/health", tags=["health"])
def health():
    return {"ok": True, "mode": "mock" if config.MOCK_MODE else "gemini", "model": config.GEMINI_MODEL,
            "embed_model": config.GEMINI_EMBED_MODEL, "llm_judge": config.LLM_JUDGE}


for r in (auth.router, me.router, searches.router, cases.router, admin.router):
    app.include_router(r)
