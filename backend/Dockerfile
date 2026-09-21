# syntax=docker/dockerfile:1
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS dependencies
WORKDIR /build
COPY requirements.lock ./requirements.lock
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock

FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    HF_HOME=/models/huggingface
RUN groupadd --gid 10001 evidencedesk && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin evidencedesk \
    && mkdir -p /app /data /ledger /models \
    && chown 10001:10001 /app /data /ledger /models
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=10001:10001 src ./src
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 alembic.ini pyproject.toml requirements.lock ./
USER 10001:10001
EXPOSE 8106
CMD ["uvicorn", "evidencedesk.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8106", "--no-access-log", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]
