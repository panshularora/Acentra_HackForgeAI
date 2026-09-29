# Production image: dashboard + API + demo log generator in one process tree.
# Browser talks to a single origin; nginx is not required.
#
#   docker build -t claimswatch .
#   docker run --rm -p 8000:8000 --env-file .env claimswatch

FROM node:22-alpine AS frontend
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SERVE_DASHBOARD=true \
    DEMO_LOGGEN=true \
    LOG_PATH=/app/logs/app.log \
    DB_PATH=/app/data/claimswatch.db \
    CW_ENABLED=false \
    PORT=8000

WORKDIR /app

COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
RUN pip install ./backend

COPY tools tools
COPY --from=frontend /web/dist frontend/dist

RUN mkdir -p logs data

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=8 --start-period=20s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'))"

CMD ["sh", "-c", "exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
