#!/usr/bin/env bash
set -euo pipefail

# If custom command was passed (e.g. docker run container <cmd>), execute it directly.
# Default command "start" or empty arguments starts the supervised services.
if [ "$#" -gt 0 ] && [ "$1" != "start" ]; then
    exec "$@"
fi

# Clean up any leftover unix domain socket
rm -f /tmp/uvicorn.sock

# Clean shutdown handler
cleanup() {
    local code="${1:-0}"
    echo "Shutting down All-in-One Downloader services..."
    if [ -n "${BACKEND_PID:-}" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill -TERM "$BACKEND_PID" 2>/dev/null || true
    fi
    if [ -n "${NGINX_PID:-}" ] && kill -0 "$NGINX_PID" 2>/dev/null; then
        kill -TERM "$NGINX_PID" 2>/dev/null || true
    fi
    wait 2>/dev/null || true
    rm -f /tmp/uvicorn.sock
    exit "$code"
}

trap 'cleanup 0' SIGTERM SIGINT SIGHUP

# 1. Start FastAPI backend with Uvicorn bound strictly to internal Unix domain socket
echo "Starting backend API bound to internal Unix domain socket..."
BACKEND_DIR="${BACKEND_DIR:-/app/backend}"
if [ ! -d "$BACKEND_DIR" ] && [ -d "./backend" ]; then
    BACKEND_DIR="./backend"
fi

uv run --directory "$BACKEND_DIR" uvicorn app.main:app \
    --uds /tmp/uvicorn.sock \
    --proxy-headers \
    --forwarded-allow-ips='*' &
BACKEND_PID=$!

# Wait for internal socket to become available
MAX_WAIT=30
WAITED=0
while [ ! -S /tmp/uvicorn.sock ]; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "ERROR: Backend process exited prematurely." >&2
        wait "$BACKEND_PID"
        exit 1
    fi
    sleep 0.1
    WAITED=$((WAITED + 1))
    if [ "$WAITED" -ge "$((MAX_WAIT * 10))" ]; then
        echo "ERROR: Timed out waiting for backend socket /tmp/uvicorn.sock." >&2
        exit 1
    fi
done

# Ensure socket permissions allow nginx (www-data) to read and write
chmod 0666 /tmp/uvicorn.sock

# 2. Start Nginx reverse proxy (public web entrypoint on port 8000)
echo "Starting Nginx reverse proxy on exposed web entrypoint port..."
/usr/sbin/nginx -g "daemon off;" &
NGINX_PID=$!

# 3. Monitor child processes; if either exits, shut down cleanly
set +e
wait -n "$BACKEND_PID" "$NGINX_PID"
EXIT_CODE=$?
echo "A service process terminated (exit code: $EXIT_CODE). Exiting container..."
cleanup "$EXIT_CODE"
exit "$EXIT_CODE"
