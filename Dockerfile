# Fallback execution path for the judges, and the artifact Azure Container Apps runs.
# No conda in the image: smaller, faster to pull, and requirements.txt is the single
# source of truth shared with the local conda environment.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Dependency layer first so code edits do not invalidate the pip cache.
# Locked at Gate 5 (v1.0 freeze) so the image matches what was tested, not
# whatever requirements.txt's version ranges happen to resolve to today.
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY app/ ./app/
COPY schemas/ ./schemas/
COPY fixtures/public_cases.json ./fixtures/public_cases.json

# Non-root: Azure Container Apps and most registries flag root-run images.
RUN useradd --create-home --uid 10001 gridwise && chown -R gridwise:gridwise /app
USER gridwise

EXPOSE 8000

# Judges must reach /health within 60 s of start.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD python -c "import os,urllib.request,sys;u='http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health';sys.exit(0 if urllib.request.urlopen(u,timeout=2).status==200 else 1)"

# Bind 0.0.0.0 and honour the platform-injected $PORT (Azure sets it).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
