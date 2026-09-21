FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 HF_HOME=/models/huggingface \
    TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1
COPY requirements-ml.lock /tmp/requirements-ml.lock
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps -r /tmp/requirements-ml.lock
WORKDIR /workspace
CMD ["python", "experiments/preflight.py"]
