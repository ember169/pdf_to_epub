# Build from the repository root:  docker build -f deploy/Dockerfile -t pdftoepub .
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
# Exact, hash-checked dependency versions (requirements.lock; regenerate with packaging/relock.sh)
COPY requirements.lock packaging/build-backend.lock ./
RUN /opt/venv/bin/pip install --require-hashes --no-deps -r build-backend.lock -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN /opt/venv/bin/pip install --no-deps --no-build-isolation .
# wordfreq lexicons (glued-word splitter): git-ignored, so not in the wheel. Fetched into src/ (pinned, sha256-checked;
# a valid copy from the build context is kept) and copied into the installed package.
RUN python src/pdftoepub/core/lexicon.py fetch \
 && cp -R src/pdftoepub/core/data "$(/opt/venv/bin/python -c 'import os, pdftoepub.core as c; print(os.path.dirname(c.__file__))')/"

FROM python:3.12-slim AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    TMPDIR=/data/tmp \
    MAX_UPLOAD_MB=100 \
    JOB_TTL_HOURS=24 \
    MAX_CONCURRENT_JOBS=2
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/venv /opt/venv
RUN useradd --system --uid 10001 --create-home app \
    && mkdir -p /data/tmp && chown -R app:app /data
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"
CMD ["uvicorn", "pdftoepub.web.app:app", "--host", "0.0.0.0", "--port", "8000"]

# Test image: docker build -f deploy/Dockerfile --target test -t pdftoepub-test .
#   docker run --rm pdftoepub-test
FROM runtime AS test
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-dev.lock /tmp/requirements-dev.lock
COPY packaging/build-backend.lock /tmp/build-backend.lock
RUN pip install --require-hashes --no-deps -r /tmp/build-backend.lock -r /tmp/requirements-dev.lock
COPY pyproject.toml README.md /src/
COPY src /src/src
COPY tests /src/tests
RUN pip install --no-deps --no-build-isolation /src \
 && python /src/src/pdftoepub/core/lexicon.py fetch \
 && cp -R /src/src/pdftoepub/core/data "$(python -c 'import os, pdftoepub.core as c; print(os.path.dirname(c.__file__))')/" \
 && chown -R app /src
USER app
WORKDIR /src
CMD ["pytest", "-v"]

# Keep last so a plain `docker build` yields the production image.
FROM runtime AS final
