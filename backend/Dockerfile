# GridMind API: a long-running container for Railway, Render or Fly.
#
# Needs, at runtime:
#   - DATABASE_URL, DATABASE_URL_READONLY (Neon direct endpoints), GROQ_*,
#     CORS_ORIGINS: see .env.example;
#   - a persistent volume at /data/fastf1-cache, or every cold question
#     re-downloads its session from the timing API;
#   - the host's health check pointed at /health (it never touches Postgres,
#     so polling it does not keep Neon awake).
#
# Dependencies come from requirements.lock. After changing pyproject.toml:
#   uv pip freeze --python .venv/Scripts/python.exe --exclude-editable > pins.txt
#   uv pip compile pyproject.toml --python-version 3.13 \
#     --python-platform x86_64-manylinux_2_28 -c pins.txt --no-header --no-annotate
# and keep the header comment at the top of requirements.lock.

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    FASTF1_CACHE_DIR=/data/fastf1-cache \
    # The client address the rate limiter sees. uvicorn replaces the proxy's
    # address with the X-Forwarded-For entry nearest to the first untrusted hop,
    # so only the hosts' private and internal ranges are trusted. "*" would
    # make it take the leftmost entry, which any client can write.
    FORWARDED_ALLOW_IPS="127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,fc00::/7"

WORKDIR /app

COPY requirements.lock ./
RUN uv pip install --system --no-cache -r requirements.lock

RUN useradd --system --uid 10001 --create-home app \
    && mkdir -p "$FASTF1_CACHE_DIR" \
    && chown app:app "$FASTF1_CACHE_DIR"

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/health\", timeout=3)"]

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "app"]
