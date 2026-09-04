FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVSUI_ENVIRONMENT=production \
    WEB_CONCURRENCY=1

WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir . \
    && addgroup --system --gid 10001 evsui \
    && adduser --system --uid 10001 --ingroup evsui evsui \
    && mkdir -p /app/data /app/uploads /app/pem_runtime \
    && chown -R evsui:evsui /app

USER evsui
EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/healthz', timeout=3)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1"]
