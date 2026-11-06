FROM python:3.12.16-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/backups && chown app:app /app/backups
COPY requirements.txt ./
# Optional corporate CA is mounted for this step only, never copied into layers.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --require-hashes -r requirements.txt

# Root-owned application code remains read-only to the runtime account.
USER app
# The context allowlist contains only the lock, application and Alembic files.
COPY --chmod=0755 . ./
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"
# Hosted Docker deployments use the same reviewed migration/credential-removal
# wrapper as Render's former Python runtime. Compose overrides this entrypoint
# for its separate migration and already-migrated API services.
ENTRYPOINT ["/app/start-hosted.sh"]
