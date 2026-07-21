# syntax=docker/dockerfile:1

# *** Stage 1: Build environment ***
FROM python:3.14.6-slim-trixie AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:python3.14-trixie-slim /usr/local/bin /bin/

# Silence warnings about unable to link files since the
# cache and sync target are on separate file systems.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app

WORKDIR /build

# 1. Only copy files required for dependency resolution
COPY pyproject.toml uv.lock README.md /build/

# 2. Sync dependencies ONLY (this layer remains cached if code changes)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# 3. Copy the actual application source code
COPY src /build/src

# 4. Sync the project into the environment (non-editable for production)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


# *** Stage 2: Final runtime ***
FROM python:3.14.6-slim-trixie

WORKDIR /app

# Copy the pre-built virtual environment from the builder stage
COPY --from=builder /app /app

# Ensure the virtual environment's binaries are preferred in the PATH
ENV PATH="/app/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright \
    PYTHONUNBUFFERED=True

# Install the browser used for Princeton DataSpace downloads.
RUN playwright install --with-deps chromium

# Set labels
LABEL org.opencontainers.image.authors="Jeffry Lew"
LABEL org.opencontainers.image.base.name="python:3.14.6-slim-trixie"
LABEL org.opencontainers.image.description="Back-end image for opendissertation.com"
LABEL org.opencontainers.image.source="https://github.com/OpenDissertation/od_backend/blob/main/Dockerfile"
LABEL org.opencontainers.image.title="backend"
LABEL org.opencontainers.image.vendor="OpenDissertation"

LABEL org.opencontainers.image.version="0.2.0"

CMD ["sh", "-c", "uvicorn od_backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
