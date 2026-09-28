# Backend image. Built from the repository root so the tools (log generator,
# replay, sns_tail) ship alongside the service; docker-compose reuses this
# image for the log generator.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
RUN pip install ./backend

COPY tools tools

RUN useradd --create-home --uid 10001 claimswatch \
    && mkdir -p logs data \
    && chown claimswatch logs data
USER claimswatch

ENV LOG_PATH=/app/logs/app.log \
    DB_PATH=/app/data/claimswatch.db

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
