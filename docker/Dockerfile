# Reference development / CI image for every Xenoide repository.
#
# Build (from the devkit root):
#   docker build -f docker/Dockerfile -t xenoide-dev:v0.1.0 .
#
# The image is the reference environment for future CI. It is Linux-only;
# macOS and Windows toolchains always run on the host.

ARG UBUNTU_DIGEST=sha256:9c7f200c07e3d4a03e7249d2c16bf66a51120fb876aa2242cf31451412543289
FROM ubuntu:24.04@${UBUNTU_DIGEST}

ARG DEBIAN_FRONTEND=noninteractive
ARG LLVM_VERSION=19
ARG MULL_VERSION=0.39.1
ARG TARGETARCH=amd64

# ----------------------------------------------------------------- base tools
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        gdb \
        ninja-build \
        valgrind \
        lsb-release \
        software-properties-common \
        gnupg \
        sudo \
        unzip \
        xz-utils \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# ----------------------------------------------------------------------- LLVM
RUN curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key \
        -o /usr/share/keyrings/llvm.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/llvm.gpg] \
http://apt.llvm.org/noble/ llvm-toolchain-noble-${LLVM_VERSION} main" \
        > /etc/apt/sources.list.d/llvm.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        clang-${LLVM_VERSION} \
        clang-tools-${LLVM_VERSION} \
        clang-format-${LLVM_VERSION} \
        clang-tidy-${LLVM_VERSION} \
        lld-${LLVM_VERSION} \
        lldb-${LLVM_VERSION} \
        llvm-${LLVM_VERSION} \
        libc++-${LLVM_VERSION}-dev \
        libc++abi-${LLVM_VERSION}-dev \
    && rm -rf /var/lib/apt/lists/* \
    && for tool in clang clang++ clang-format clang-tidy llvm-cov llvm-profdata lldb; do \
         ln -sf /usr/bin/${tool}-${LLVM_VERSION} /usr/local/bin/${tool}; \
       done

# ----------------------------------------------------------------------- Mull
# Mull is bound to an exact LLVM major. Keep MULL_VERSION and LLVM_VERSION in
# lockstep when updating either.
RUN set -eux; \
    arch="${TARGETARCH}"; \
    case "${arch}" in amd64) mull_arch=amd64 ;; arm64) mull_arch=aarch64 ;; *) mull_arch=amd64 ;; esac; \
    url="https://github.com/mull-project/mull/releases/download/${MULL_VERSION}/Mull-${LLVM_VERSION}-${MULL_VERSION}-LLVM-${LLVM_VERSION}.1.1-ubuntu-${mull_arch}-24.04.deb"; \
    if ! curl -fsSL "${url}" -o /tmp/mull.deb; then \
        echo "Mull ${MULL_VERSION} for LLVM ${LLVM_VERSION} not available at ${url}; skipping"; \
    else \
        apt-get update; \
        apt-get install -y --no-install-recommends /tmp/mull.deb; \
        rm -f /tmp/mull.deb; \
        rm -rf /var/lib/apt/lists/*; \
    fi

# ----------------------------------------------------------------------- mise
ENV MISE_DATA_DIR=/opt/mise
RUN curl -fsSL https://mise.run | sh && mv /root/.local/bin/mise /usr/local/bin/mise

# Pin the portable orchestration tools at the devkit reference versions.
COPY mise/reference-tools.toml /etc/mise/config.toml
RUN mise install && mise prune

# A non-root user keeps bind-mounted files owned by the host user once
# devcontainer.json applies updateRemoteUserUID.
ARG USERNAME=xenoide
ARG USER_UID=1000
ARG USER_GID=1000
RUN groupadd --gid ${USER_GID} ${USERNAME} || true \
    && useradd --uid ${USER_UID} --gid ${USER_GID} -m ${USERNAME} || true \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME}

ENV XENOIDE_CONAN_HOME=/conan \
    XENOIDE_BUILD_ROOT=build/devcontainer \
    XENOIDE_CONFIG=clang-debug \
    PATH=/opt/mise/shims:/usr/local/bin:${PATH}

USER ${USERNAME}
WORKDIR /workspace

CMD ["/bin/bash"]
