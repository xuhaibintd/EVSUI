FROM ghcr.io/astral-sh/uv:0.12.10 AS uv

FROM python:3.11-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVSUI_ENVIRONMENT=production \
    WEB_CONCURRENCY=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY app /app/app
COPY LICENSE /app/LICENSE
RUN addgroup --system --gid 10001 teradataevsui \
    && adduser --system --uid 10001 --ingroup teradataevsui teradataevsui \
    && mkdir -p /app/data /app/uploads /app/pem_runtime \
    && chown -R teradataevsui:teradataevsui /app

USER teradataevsui
EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/healthz', timeout=3)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1"]
