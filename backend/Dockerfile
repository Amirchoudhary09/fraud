FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/data
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY eval ./eval
COPY start.sh ./start.sh
# strip Windows line endings in case the repo was checked out with CRLF
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh

# Run as an unprivileged user. On Railway, mount a volume at /data (evidence, databases, audit log).
RUN useradd --create-home --uid 10001 appuser && mkdir -p /data && chown appuser /data
USER appuser

EXPOSE 8000
# API by default; `./start.sh worker` runs the Redis job worker (see README, multi-replica setup).
CMD ["./start.sh"]
