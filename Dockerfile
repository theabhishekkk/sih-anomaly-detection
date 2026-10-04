FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    WEB_CONCURRENCY=2

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir --requirement /app/backend/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app && \
    mkdir -p /app/backend/data && \
    chown -R app:app /app

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"

CMD ["sh", "-c", "exec uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2}"]
