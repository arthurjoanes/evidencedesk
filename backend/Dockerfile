# syntax=docker/dockerfile:1
FROM python:3.12.14-alpine3.24@sha256:c4634f578a412db396771b61b064c6e546c9d6414c7fb5b1b05d5871f1885f7b AS dependencies
WORKDIR /build
COPY requirements.lock ./requirements.lock
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements.lock

FROM python:3.12.14-alpine3.24@sha256:c4634f578a412db396771b61b064c6e546c9d6414c7fb5b1b05d5871f1885f7b AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    HF_HOME=/models/huggingface
RUN addgroup -g 10001 evidencedesk && adduser -D -H -u 10001 -G evidencedesk -s /sbin/nologin evidencedesk \
    && mkdir -p /app /data /ledger /models \
    && chown 10001:10001 /app /data /ledger /models
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
# Installation belongs to the build stage; runtime never needs package installers.
# Keep the application distributions and OS package database intact for scanning.
RUN rm -rf /opt/venv/lib/python3.12/site-packages/pip \
        /opt/venv/lib/python3.12/site-packages/pip-*.dist-info \
        /usr/local/lib/python3.12/site-packages/pip \
        /usr/local/lib/python3.12/site-packages/pip-*.dist-info \
        /usr/local/lib/python3.12/ensurepip \
    && rm -f /opt/venv/bin/pip* /usr/local/bin/pip*
COPY --chown=10001:10001 src ./src
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 alembic.ini pyproject.toml requirements.lock ./
USER 10001:10001
EXPOSE 8106
CMD ["uvicorn", "evidencedesk.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8106", "--no-access-log", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]
