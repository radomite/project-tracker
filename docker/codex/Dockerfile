# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
ARG NODE_IMAGE=node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d
FROM ${NODE_IMAGE} AS codex-package
ARG CODEX_VERSION=0.167.0
RUN npm install -g @openai/codex@${CODEX_VERSION} && npm cache clean --force

FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CODEX_STATE=/state CODEX_HOME=/state/login
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates bubblewrap libstdc++6 \
    && python -m pip install --no-cache-dir httpx==0.28.1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=codex-package /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-package /usr/local/lib/node_modules/@openai /usr/local/lib/node_modules/@openai
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && codex --version
WORKDIR /service
COPY codex_service.py ./
COPY scripts/check_codex_container.py ./
COPY scripts/check_release_image.py /usr/local/bin/check-release-image.py
# The supervisor drops each Codex child to its own UID. It needs no Docker socket.
CMD ["python", "codex_service.py"]
