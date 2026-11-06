# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
FROM node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS editor-build
ENV NODE_OPTIONS=--max-old-space-size=384
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY editor-src/ ./editor-src/
COPY scripts/ ./scripts/
COPY third-party/ ./third-party/
COPY static/ ./static/
RUN npm run build

FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RESEARCH_DB=/data/research.db

# Git serves the authenticated smart-HTTP remotes in this process.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 tracker \
    && useradd --uid 1000 --gid tracker --create-home tracker \
    && install -d -o tracker -g tracker /data /data/research-files

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY static/ ./static/
COPY --from=editor-build /build/static/vendor/ ./static/vendor/
COPY --from=editor-build /build/static/editor-assets/ ./static/editor-assets/
COPY editor-src/ ./editor-src/
COPY third-party/ ./third-party/
COPY scripts/ ./scripts/
COPY docker/ ./docker/
COPY scripts/check_release_image.py /usr/local/bin/check-release-image.py
COPY tests/ ./tests/
COPY package.json package-lock.json ./
COPY Dockerfile compose.yaml README.md .dockerignore .gitignore .gitattributes run.ps1 ./
COPY playwright.config.js playwright.editor.config.js ./
COPY LICENSE ./
COPY init.ps1 ./
COPY deploy/ ./deploy/
COPY .github/ ./.github/
RUN python scripts/editor-fonts.py

USER tracker
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=4).read()"
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1"]

FROM runtime AS test
COPY tests/ ./tests/
USER root
RUN install -d -o tracker -g tracker /tmp/container-tests
USER tracker
WORKDIR /tmp/container-tests
ENV PYTHONPATH=/app RESEARCH_DB=/tmp/container-tests/default.db
CMD ["python", "-m", "unittest", "discover", "-s", "/app/tests", "-p", "test_*.py", "-v"]

FROM runtime AS app
