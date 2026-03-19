# harbor-runner: image for running Harbor coding evals.
#
# Provides:
#   - Docker Engine  (harbor run --env docker needs a daemon inside the VM)
#   - Python 3.11 + harbor + vendor-eval
#   - Node.js 22 + opencode-ai  (the agent harbor uses for coding tasks)
#
# Build (single-arch):
#   docker build -t harbor-runner:latest .
#
# Multi-arch build (amd64 + arm64):
#   docker buildx build \
#     --platform linux/amd64,linux/arm64 \
#     -t harbor-runner:latest \
#     --push \
#     .

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# ── System packages ────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        lsb-release \
        iptables \
        iproute2 \
        python3 \
        python3-pip \
        git \
        bash \
        xz-utils \
        pigz \
    && rm -rf /var/lib/apt/lists/*

# ── Docker Engine ──────────────────────────────────────────────────────────
# NOTE: $(dpkg --print-architecture) is evaluated at build time per platform,
# so multi-arch buildx works correctly for both amd64 and arm64.
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
       | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Docker daemon config: vfs storage driver works in nested containers where
# overlayfs is unavailable (common in gVisor / runc environments). Switch to
# overlay2 if you confirm it is supported on your cluster.
COPY daemon.json /etc/docker/daemon.json

# ── Node.js 22 + opencode-ai ───────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g opencode-ai@latest

# ── Harbor ─────────────────────────────────────────────────────────────────
# Ubuntu 24.04 enforces PEP 668 — need --break-system-packages in Docker images.
RUN pip3 install --no-cache-dir --break-system-packages harbor

# ── vendor-eval (local package from this repo) ─────────────────────────────
COPY vendor_eval/   /opt/vendor-eval/vendor_eval/
COPY pyproject.toml /opt/vendor-eval/pyproject.toml
RUN pip3 install --no-cache-dir --break-system-packages /opt/vendor-eval/

# ── Sanity checks ──────────────────────────────────────────────────────────
RUN docker --version \
    && harbor --version \
    && opencode --version \
    && vendor-eval --help

CMD ["/bin/bash"]
