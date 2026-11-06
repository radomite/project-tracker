# syntax=docker/dockerfile:1
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc
ARG MATHLIB_REVISION=56a005855ea17e0b0958f73ec801ae140b0a1679
ENV ELAN_HOME=/opt/elan \
    PATH=/usr/local/bin:/opt/elan/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    MATHLIB_CACHE_DIR=/tmp/mathlib-cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git build-essential zstd xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Install only inside this image. Verify the pinned Elan release archive.
RUN set -eu; \
    case "$(dpkg --print-architecture)" in \
      amd64) arch=x86_64; checksum=42b94d4244e8353142c456ec0e4ca6528fd898a6c604d4059f494e706e431f63 ;; \
      arm64) arch=aarch64; checksum=05febd124d84ebf994b2e7479922a5650b1e950c17ae3bd1ddd776b65bb72bf9 ;; \
      *) echo 'Lean image supports amd64 and arm64.' >&2; exit 1 ;; \
    esac; \
    curl -fSL --retry 3 "https://github.com/leanprover/elan/releases/download/v4.2.4/elan-${arch}-unknown-linux-gnu.tar.gz" -o /tmp/elan.tar.gz; \
    echo "$checksum  /tmp/elan.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/elan.tar.gz -C /tmp; \
    /tmp/elan-init -y --no-modify-path --default-toolchain none; \
    rm /tmp/elan.tar.gz /tmp/elan-init

COPY smoke.lean /tmp/Smoke.lean
WORKDIR /opt/mathlib
RUN set -eu; \
    git init; \
    git remote add origin https://github.com/leanprover-community/mathlib4.git; \
    git fetch --depth=1 origin "$MATHLIB_REVISION"; \
    git checkout --detach FETCH_HEAD; \
    test "$(git rev-parse HEAD)" = "$MATHLIB_REVISION"; \
    toolchain="$(cat lean-toolchain)"; \
    elan toolchain install "$toolchain"; \
    elan default "$toolchain"; \
    lake exe cache get; \
    cp /tmp/Smoke.lean DockerSmoke.lean; \
    lake env lean DockerSmoke.lean; \
    lake env printenv LEAN_PATH > /opt/mathlib/lean-path; \
    ln -s "$(elan which lean)" /usr/local/bin/lean-compiler; \
    ln -s "$(elan which lake)" /usr/local/bin/lake; \
    rm DockerSmoke.lean /tmp/Smoke.lean; \
    rm -rf /tmp/mathlib-cache; \
    chmod -R a+rX /opt/elan /opt/mathlib

COPY --chmod=755 lean-with-mathlib.sh /usr/local/bin/lean-with-mathlib
WORKDIR /work
CMD ["lean-with-mathlib", "--version"]
