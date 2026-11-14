#!/usr/bin/env bash
# ==============================================================================
# All-in-One Media Downloader — Local Development Launcher
# Starts FastAPI backend (port 8000) and Vite frontend (port 5173) concurrently.
# Handles robust signal trapping (SIGINT, SIGTERM, EXIT) with zero orphaned processes.
# ==============================================================================

set -euo pipefail

# ANSI Color Codes
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Dynamic repository root directory resolution
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo -e "${BOLD}${GREEN}======================================================${NC}"
echo -e "${BOLD}${GREEN}   All-in-One Media Downloader — Dev Server Launcher   ${NC}"
echo -e "${BOLD}${GREEN}======================================================${NC}"

# ------------------------------------------------------------------------------
# 1. Prerequisite Checks
# ------------------------------------------------------------------------------
compare_version() {
    local cur="$1"
    local req="$2"
    local c_maj=$(echo "$cur" | cut -d. -f1)
    local c_min=$(echo "$cur" | cut -d. -f2)
    local r_maj=$(echo "$req" | cut -d. -f1)
    local r_min=$(echo "$req" | cut -d. -f2)
    if [ "$c_maj" -gt "$r_maj" ]; then return 0; fi
    if [ "$c_maj" -eq "$r_maj" ] && [ "${c_min:-0}" -ge "${r_min:-0}" ]; then return 0; fi
    return 1
}

MISSING=0

# Python 3.12+
if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Required tool 'python3' is not installed or not in PATH.${NC}" >&2
    echo -e "${YELLOW}        Installation hint: Install Python 3.12+ from https://www.python.org/downloads/ or via your system package manager.${NC}" >&2
    MISSING=1
else
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
    if ! compare_version "$PY_VER" "3.12"; then
        echo -e "${RED}[ERROR] Python version ${PY_VER} detected, but Python >= 3.12 is required.${NC}" >&2
        echo -e "${YELLOW}        Installation hint: Please upgrade Python to 3.12 or higher.${NC}" >&2
        MISSING=1
    fi
fi

# uv package manager (>= 0.4.x)
if ! command -v uv >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Required tool 'uv' is not installed or not in PATH.${NC}" >&2
    echo -e "${YELLOW}        Installation hint: curl -LsSf https://astral.sh/uv/install.sh | sh${NC}" >&2
    MISSING=1
else
    UV_RAW=$(uv --version 2>/dev/null | awk '{print $2}' || echo "0.0")
    if ! compare_version "$UV_RAW" "0.4"; then
        echo -e "${RED}[ERROR] uv version ${UV_RAW} detected, but uv >= 0.4.0 is required.${NC}" >&2
        echo -e "${YELLOW}        Installation hint: Run 'uv self update' or reinstall from https://astral.sh/uv${NC}" >&2
        MISSING=1
    fi
fi

# Bun runtime (>= 1.1.x)
if ! command -v bun >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Required tool 'bun' is not installed or not in PATH.${NC}" >&2
    echo -e "${YELLOW}        Installation hint: curl -fsSL https://bun.sh/install | bash${NC}" >&2
    MISSING=1
else
    BUN_RAW=$(bun --version 2>/dev/null || echo "0.0")
    if ! compare_version "$BUN_RAW" "1.1"; then
        echo -e "${RED}[ERROR] Bun version ${BUN_RAW} detected, but bun >= 1.1.0 is required.${NC}" >&2
        echo -e "${YELLOW}        Installation hint: Run 'bun upgrade' or reinstall from https://bun.sh${NC}" >&2
        MISSING=1
    fi
fi

# FFmpeg check (system binary or pyffmpeg bundled via backend uv dependencies)
if command -v ffmpeg >/dev/null 2>&1; then
    FF_RAW=$(ffmpeg -version 2>&1 | head -n1 | sed -nE 's/.*ffmpeg version ([0-9]+(\.[0-9]+)*).*/\1/p' || echo "0.0")
    FF_STATUS="System FFmpeg ($FF_RAW)"
else
    FF_STATUS="pyffmpeg (bundled via backend uv dependencies)"
fi

if [ "$MISSING" -ne 0 ]; then
    echo -e "\n${RED}[FATAL] Please resolve missing prerequisites before starting the development environment.${NC}" >&2
    exit 1
fi

echo -e "${GREEN}[dev] Prerequisites verified successfully:${NC}"
echo -e "      Python: ${PY_VER}"
echo -e "      uv:     ${UV_RAW}"
echo -e "      bun:    ${BUN_RAW}"
echo -e "      ffmpeg: ${FF_STATUS}"

# ------------------------------------------------------------------------------
# 2. Pre-flight Setup & Auto-Sync
# ------------------------------------------------------------------------------
# Ensure storage directories exist
mkdir -p "$ROOT_DIR/cookies" "$ROOT_DIR/downloads"

if [ ! -d "$ROOT_DIR/backend/.venv" ]; then
    echo -e "${CYAN}[dev] Initializing backend virtualenv with uv sync...${NC}"
    (cd "$ROOT_DIR/backend" && uv sync)
fi

if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
    echo -e "${MAGENTA}[dev] Installing frontend dependencies with bun install...${NC}"
    (cd "$ROOT_DIR/frontend" && bun install)
fi

# ------------------------------------------------------------------------------
# 3. Output Formatting Filter (Unbuffered Real-time Color-Coded Logs)
# ------------------------------------------------------------------------------
prefix_output() {
    local prefix="$1"
    while IFS= read -r line || [ -n "$line" ]; do
        printf "%b%s\n" "$prefix" "$line"
    done
}

# ------------------------------------------------------------------------------
# 4. Signal Trapping & Comprehensive Process Cleanup
# ------------------------------------------------------------------------------
BACKEND_PID=""
FRONTEND_PID=""
CLEANED_UP=0

kill_tree() {
    local pid="$1"
    local sig="${2:-TERM}"
    if [ -z "$pid" ]; then return 0; fi

    # Recursively find and terminate child processes
    local children
    children=$(pgrep -P "$pid" 2>/dev/null || true)
    for child in $children; do
        kill_tree "$child" "$sig"
    done

    # Send signal to the process group if possible, else directly to process
    kill "-$sig" "-$pid" 2>/dev/null || kill "-$sig" "$pid" 2>/dev/null || true
}

cleanup() {
    if [ "$CLEANED_UP" -eq 1 ]; then
        return 0
    fi
    CLEANED_UP=1
    trap - SIGINT SIGTERM EXIT

    echo -e "\n${BOLD}${CYAN}[dev]${NC} Gracefully shutting down development servers..."

    if [ -n "$BACKEND_PID" ]; then
        kill_tree "$BACKEND_PID" TERM
    fi
    if [ -n "$FRONTEND_PID" ]; then
        kill_tree "$FRONTEND_PID" TERM
    fi

    # Wait up to 2 seconds for graceful exit
    local timeout=20
    while [ $timeout -gt 0 ]; do
        local running=0
        if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
            running=1
        fi
        if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
            running=1
        fi
        if [ $running -eq 0 ]; then
            break
        fi
        sleep 0.1
        timeout=$((timeout - 1))
    done

    # Force kill any stubborn remnants
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill_tree "$BACKEND_PID" KILL
    fi
    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        kill_tree "$FRONTEND_PID" KILL
    fi

    echo -e "${BOLD}${GREEN}[dev]${NC} All services stopped successfully."
}

trap cleanup SIGINT SIGTERM EXIT

# ------------------------------------------------------------------------------
# 5. Launch Backend & Frontend Services
# ------------------------------------------------------------------------------
export PYTHONUNBUFFERED=1

echo -e "${CYAN}[backend]${NC}  Starting FastAPI on http://0.0.0.0:8000"
(
    cd "$ROOT_DIR/backend"
    exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
) > >(prefix_output "${CYAN}[backend]${NC} ") 2>&1 &
BACKEND_PID=$!

echo -e "${MAGENTA}[frontend]${NC} Starting Vite dev server on http://0.0.0.0:5173"
(
    cd "$ROOT_DIR/frontend"
    exec bun run dev --host 0.0.0.0 --port 5173
) > >(prefix_output "${MAGENTA}[frontend]${NC} ") 2>&1 &
FRONTEND_PID=$!

echo -e "\n${BOLD}${GREEN}======================================================${NC}"
echo -e "${BOLD}Dev servers running:${NC}"
echo -e "  - Backend API: ${CYAN}http://localhost:8000${NC} (Docs: ${CYAN}http://localhost:8000/docs${NC})"
echo -e "  - Frontend UI: ${MAGENTA}http://localhost:5173${NC}"
echo -e "Press ${BOLD}Ctrl+C${NC} to shut down both servers cleanly."
echo -e "${BOLD}${GREEN}======================================================${NC}\n"

# Wait for background services
wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
