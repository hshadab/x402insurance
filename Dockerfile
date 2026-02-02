# x402 Insurance API — AgentCore container (ARM64 with x86_64 binary emulation)
# Pre-built Jolt Atlas binary is x86_64; runs via QEMU on ARM64 AgentCore runtime

# Stage 1: Python builder (ARM64)
FROM public.ecr.aws/docker/library/python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements-prod.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-prod.txt

# Stage 2: Runtime (ARM64)
FROM public.ecr.aws/docker/library/python:3.11-slim

# Install runtime deps + QEMU for x86_64 binary emulation
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    qemu-user \
    libc6-amd64-cross \
    libgcc-s1-amd64-cross \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/x86_64-linux-gnu/lib64 /lib64 \
    && ln -sf /usr/x86_64-linux-gnu/lib /lib/x86_64-linux-gnu

# Create non-root user
RUN useradd -m -u 1000 x402user && \
    mkdir -p /app/data /app/jolt-atlas /app/models && \
    chown -R x402user:x402user /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy pre-built x86_64 Jolt Atlas binary, ONNX model, and SRS file
COPY --chown=x402user:x402user jolt-atlas/jolt_claims_prover /app/jolt-atlas/jolt_claims_prover.x86_64
COPY --chown=x402user:x402user models/claim_classifier.onnx /app/models/claim_classifier.onnx
COPY --chown=x402user:x402user dory_srs_22_variables.srs /app/dory_srs_22_variables.srs

# Create a wrapper script that runs the x86_64 binary via QEMU
RUN printf '#!/bin/sh\nexec /usr/bin/qemu-x86_64 -L /usr/x86_64-linux-gnu /app/jolt-atlas/jolt_claims_prover.x86_64 "$@"\n' \
    > /app/jolt-atlas/jolt_claims_prover && \
    chmod +x /app/jolt-atlas/jolt_claims_prover /app/jolt-atlas/jolt_claims_prover.x86_64

# Copy application code (excluding jolt binary which was already set up with QEMU wrapper)
COPY --chown=x402user:x402user . .

# Restore the QEMU wrapper (COPY . . overwrites it with the raw x86_64 binary)
RUN printf '#!/bin/sh\nexec /usr/bin/qemu-x86_64 -L /usr/x86_64-linux-gnu /app/jolt-atlas/jolt_claims_prover.x86_64 "$@"\n' \
    > /app/jolt-atlas/jolt_claims_prover && \
    chmod +x /app/jolt-atlas/jolt_claims_prover

RUN mkdir -p data logs && \
    chown -R x402user:x402user data logs

USER x402user

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENV=production \
    JOLT_BINARY_PATH=./jolt-atlas/jolt_claims_prover \
    ONNX_MODEL_PATH=./models/claim_classifier.onnx \
    BASE_RPC_URL=https://mainnet.base.org \
    CHAIN_ID=8453 \
    FACILITATOR_URL=https://x402.org/facilitator

CMD ["python", "-u", "agentcore_agent.py"]
