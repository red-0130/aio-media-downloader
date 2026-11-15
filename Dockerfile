# ==============================================================================
# Stage 1: Build Frontend SPA with Bun
# ==============================================================================
FROM docker.io/oven/bun:1-slim AS frontend-builder

WORKDIR /app/frontend

# Cache frontend dependencies
COPY frontend/package.json frontend/bun.lock* ./
RUN bun install --frozen-lockfile

# Copy frontend source code and compile production Vite bundle
COPY frontend/ ./
RUN bun run build

# ==============================================================================
# Stage 2: Production Python Runtime with FFmpeg & FastAPI
# ==============================================================================
FROM docker.io/library/python:3.12-slim AS runtime

# Install system dependencies (ca-certificates, curl, nginx-light)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    nginx-light \
    && rm -rf /var/lib/apt/lists/*

# Copy uv package manager binaries from official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy Bun runtime binary from frontend-builder stage for yt-dlp JS challenges
COPY --from=frontend-builder /usr/local/bin/bun /usr/local/bin/bun

WORKDIR /app

# Cache backend dependencies
COPY backend/pyproject.toml backend/uv.lock backend/README.md /app/backend/
RUN uv sync --frozen --no-dev --directory /app/backend

# Copy backend application source code
COPY backend/ /app/backend/

# Copy compiled frontend static assets from Stage 1 into backend static directory
COPY --from=frontend-builder /app/frontend/dist /app/backend/app/static

# Configure Nginx reverse proxy to isolate backend API internally
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /etc/nginx/sites-enabled/* \
    && ln -sf /dev/stdout /var/log/nginx/access.log \
    && ln -sf /dev/stderr /var/log/nginx/error.log

# Copy entrypoint script for internal backend isolation and process supervision
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create storage directories with write permissions for volume mounts
RUN mkdir -p /app/cookies /app/downloads \
    && chmod -R 777 /app/cookies /app/downloads

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    STORAGE_TTL_MINUTES=60 \
    PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONPATH="/app/backend" \
    BASE_DIR="/app" \
    COOKIES_DIR="/app/cookies" \
    DOWNLOADS_DIR="/app/downloads"

# Only the public web entrypoint port is exposed externally
EXPOSE 8000

# Healthcheck verifying HTTP service responsiveness via web entrypoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Start internal backend (bound to Unix socket) and web entrypoint reverse proxy
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["start"]
