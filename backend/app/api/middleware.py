"""HTTP middleware: request id + audit context, request size limit, security headers, error counts."""
from collections import Counter

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..core import config, context
from .deps import client_ip

error_counts: Counter = Counter()  # status code -> count since start (shown on the admin dashboard)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def install(app: FastAPI):
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id")
        rid = rid if rid and len(rid) <= 64 and rid.replace("-", "").isalnum() else context.new_request_id()
        context.request_id.set(rid)
        context.ip_hash.set(context.hash_ip(client_ip(request)))
        context.actor_id.set(None)

        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > config.MAX_BODY_MB * 1024 * 1024:
            return JSONResponse({"detail": f"Request body larger than {config.MAX_BODY_MB} MB"}, status_code=413)

        resp = await call_next(request)
        if resp.status_code >= 400:
            error_counts[str(resp.status_code)] += 1
        resp.headers["X-Request-ID"] = rid
        for k, v in _SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        if request.url.path.endswith("/report"):
            # Reports are HTML built from public web data: no scripts may run in them.
            resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        return resp
