# Multi-stage build for x402 Insurance API
# Production-ready Docker image with security best practices

# Stage 1: Builder
FROM public.ecr.aws/docker/library/python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install dependencies
COPY requirements-prod.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-prod.txt

# Stage 2: Runtime
FROM public.ecr.aws/docker/library/python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 x402user && \
    mkdir -p /app/data /app/zkengine && \
    chown -R x402user:x402user /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=x402user:x402user . .

# Create necessary directories with proper permissions
RUN mkdir -p data logs && \
    chown -R x402user:x402user data logs && \
    chmod +x /app/zkengine/fraud_detector || true

# Switch to non-root user
USER x402user

# Expose ports (8000 standard, 8080 AgentCore)
EXPOSE 8000
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENV=production \
    ZKENGINE_BINARY_PATH=./zkengine/fraud_detector \
    ZKENGINE_CWD=/app/zkengine

# Run the application
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "server:app"]
