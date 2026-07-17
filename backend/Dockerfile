# Latest stable Python (3.14 line) as of writing. The `3.14-slim` tag
# tracks the latest 3.14.x patch release automatically.
FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: libpq is not required (asyncpg is a pure C-extension wheel,
# no system libpq needed), but build-essential covers any package that
# needs to compile from source on platforms without prebuilt wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt --break-system-packages

COPY . .

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/keys \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
