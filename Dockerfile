FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home /app app

COPY pyproject.toml README.md alembic.ini ./
COPY financial_bot ./financial_bot
COPY migrations ./migrations
COPY scripts ./scripts

RUN python -m pip install --upgrade pip \
    && python -m pip install .

RUN mkdir -p /app/data /app/backups \
    && chown -R app:app /app

COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint
RUN chmod +x /usr/local/bin/docker-entrypoint

USER app

ENTRYPOINT ["docker-entrypoint"]
CMD ["family-finance-bot"]
