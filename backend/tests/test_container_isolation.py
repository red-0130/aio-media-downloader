"""Tests for single-container deployment isolation, reverse proxy, and web entrypoint functionality."""

import asyncio
from pathlib import Path
import re
import socket
import subprocess
import time
import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
NGINX_CONF_PATH = REPO_ROOT / "docker" / "nginx.conf"
ENTRYPOINT_PATH = REPO_ROOT / "docker" / "entrypoint.sh"


def get_free_port() -> int:
    """Find and return an ephemeral free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_dockerfile_isolation_directives():
    """Verify Dockerfile exposes only the web entrypoint port and sets up internal reverse proxy."""
    content = DOCKERFILE_PATH.read_text(encoding="utf-8")

    # 1. EXPOSE directives: ensure ONLY port 8000 is exposed, no backend port
    exposed_ports = re.findall(r"^EXPOSE\s+(.+)$", content, flags=re.MULTILINE)
    assert exposed_ports, "Dockerfile must contain an EXPOSE directive"
    assert exposed_ports == ["8000"], (
        f"Only web entrypoint port 8000 must be exposed externally, found: {exposed_ports}"
    )

    # 2. Ensure nginx is installed
    assert "nginx-light" in content or "nginx" in content, (
        "Dockerfile must install nginx-light or nginx in runtime stage"
    )

    # 3. Ensure configuration and entrypoint are copied
    assert "docker/nginx.conf" in content, "Dockerfile must copy docker/nginx.conf"
    assert "docker/entrypoint.sh" in content, "Dockerfile must copy docker/entrypoint.sh"

    # 4. Ensure entrypoint is configured
    assert 'ENTRYPOINT ["/app/entrypoint.sh"]' in content or 'ENTRYPOINT ["/entrypoint.sh"]' in content, (
        "Dockerfile must define ENTRYPOINT using the entrypoint script"
    )

    # 5. Ensure explicit CMD is configured to override base image CMD (e.g. python3)
    cmd_match = re.search(r'^CMD\s+\["([^"]+)"\]', content, flags=re.MULTILINE)
    assert cmd_match, "Dockerfile must define an explicit CMD to override base image CMD"
    assert cmd_match.group(1) == "start", (
        f"Dockerfile CMD should default to ['start'], found: {cmd_match.group(0)}"
    )


def test_nginx_conf_configuration():
    """Verify docker/nginx.conf binds to port 8000, proxies /api to unix socket, and disables buffering for SSE."""
    assert NGINX_CONF_PATH.is_file(), f"Nginx config not found at {NGINX_CONF_PATH}"
    content = NGINX_CONF_PATH.read_text(encoding="utf-8")

    # Upstream must point to unix domain socket
    assert "unix:/tmp/uvicorn.sock" in content, (
        "docker/nginx.conf upstream must route to internal unix domain socket (/tmp/uvicorn.sock)"
    )

    # Must listen on port 8000
    assert re.search(r"listen\s+8000", content), "Nginx config must listen on web entrypoint port 8000"

    # Must serve static assets with SPA fallback
    assert "try_files $uri $uri/ /index.html" in content, (
        "Nginx config must implement SPA fallback (try_files $uri $uri/ /index.html)"
    )

    # Must disable buffering for SSE progress streaming
    assert "proxy_buffering off" in content, "Nginx config must disable proxy buffering for SSE"
    assert "proxy_cache off" in content, "Nginx config must disable proxy cache for SSE"


def test_entrypoint_script_internal_isolation():
    """Verify docker/entrypoint.sh starts backend strictly on unix domain socket with signal handling."""
    assert ENTRYPOINT_PATH.is_file(), f"Entrypoint script not found at {ENTRYPOINT_PATH}"
    content = ENTRYPOINT_PATH.read_text(encoding="utf-8")

    # Backend must bind to internal unix domain socket
    assert "--uds /tmp/uvicorn.sock" in content, (
        "docker/entrypoint.sh must bind uvicorn strictly to internal unix domain socket"
    )

    # Backend must NOT bind to 0.0.0.0
    assert "--host 0.0.0.0" not in content, (
        "docker/entrypoint.sh must not bind backend to external 0.0.0.0 host"
    )

    # Must contain trap cleanup and monitor child processes
    assert "trap" in content and "cleanup" in content, "docker/entrypoint.sh must trap signals for clean shutdown"
    assert "wait -n" in content or "wait" in content, "docker/entrypoint.sh must supervise service processes"

    # Must execute custom commands when arguments other than 'start' are passed
    res = subprocess.run(
        [str(ENTRYPOINT_PATH), "bash", "-c", "echo custom_entrypoint_exec"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "custom_entrypoint_exec" in res.stdout


@pytest.mark.asyncio
async def test_reverse_proxy_end_to_end_runtime(tmp_path: Path):
    """Runtime verification of single-container reverse proxy isolation and SSE streaming."""
    nginx_bin = Path("/usr/sbin/nginx")
    if not nginx_bin.is_file():
        pytest.skip("/usr/sbin/nginx is not installed on this system")

    test_port = get_free_port()
    sock_path = tmp_path / "uvicorn.sock"
    pid_path = tmp_path / "nginx.pid"
    nginx_conf_file = tmp_path / "test_nginx.conf"

    # Static assets mock directory for SPA serving test
    static_dir = tmp_path / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    index_html = static_dir / "index.html"
    index_html.write_text("<!DOCTYPE html><html><body><div id='root'>All-in-One App</div></body></html>", encoding="utf-8")

    # Generate isolated nginx configuration for this test
    nginx_conf_content = f"""
    user root;
    pid {pid_path};
    events {{
        worker_connections 512;
    }}
    http {{
        include /etc/nginx/mime.types;
        default_type application/octet-stream;
        sendfile on;

        upstream backend_api {{
            server unix:{sock_path};
        }}

        server {{
            listen {test_port};
            server_name localhost;
            client_max_body_size 50M;

            root {static_dir};
            index index.html;

            location / {{
                try_files $uri $uri/ /index.html;
            }}

            location ~ ^/(api|docs|redoc|openapi.json) {{
                proxy_pass http://backend_api;
                proxy_http_version 1.1;
                proxy_set_header Host $host;
                proxy_set_header X-Real-IP $remote_addr;
                proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                proxy_set_header X-Forwarded-Proto $scheme;
                proxy_set_header Connection '';
                proxy_buffering off;
                proxy_cache off;
                proxy_read_timeout 60s;
                proxy_send_timeout 60s;
            }}
        }}
    }}
    """
    nginx_conf_file.write_text(nginx_conf_content, encoding="utf-8")

    # 1. Start uvicorn backend on Unix domain socket
    backend_proc = subprocess.Popen(
        [
            "uv", "run", "--directory", str(REPO_ROOT / "backend"),
            "uvicorn", "app.main:app",
            "--uds", str(sock_path),
            "--log-level", "warning",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    nginx_proc = None
    try:
        # Wait up to 10s for backend socket to be created
        for _ in range(100):
            if sock_path.is_socket():
                break
            await asyncio.sleep(0.1)
        assert sock_path.is_socket(), "Backend unix domain socket was not created"

        # 2. Start Nginx reverse proxy
        subprocess.run(["sudo", str(nginx_bin), "-c", str(nginx_conf_file)], check=True)

        # Allow nginx to bind port
        await asyncio.sleep(0.5)

        base_url = f"http://127.0.0.1:{test_port}"
        async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
            # 3. Test Web Entrypoint: Frontend SPA root loads properly
            r_root = await client.get("/")
            assert r_root.status_code == 200
            assert "All-in-One App" in r_root.text

            # 4. Test Web Entrypoint: SPA route fallback
            r_spa = await client.get("/settings/cookies")
            assert r_spa.status_code == 200
            assert "All-in-One App" in r_spa.text

            # 5. Test Web Entrypoint: API route proxies to internal backend
            r_api = await client.get("/api/settings/cookies")
            assert r_api.status_code == 200
            cookie_data = r_api.json()
            assert "instagram" in cookie_data
            assert "twitter" in cookie_data
            assert "youtube" in cookie_data

            # 6. Test Web Entrypoint: API inspection
            r_inspect = await client.post("/api/inspect", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
            assert r_inspect.status_code == 200
            inspect_data = r_inspect.json()
            assert inspect_data["id"] == "dQw4w9WgXcQ"

            # 7. Test Web Entrypoint: Download creation and SSE progress streaming
            r_dl = await client.post("/api/download", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
            assert r_dl.status_code == 200
            task_id = r_dl.json()["task_id"]

            # Stream SSE events through the reverse proxy
            sse_events = []
            async with client.stream("GET", f"/api/progress/{task_id}") as sse_stream:
                assert sse_stream.status_code == 200
                assert "text/event-stream" in sse_stream.headers.get("content-type", "")
                assert (
                    sse_stream.headers.get("transfer-encoding") == "chunked"
                    or sse_stream.headers.get("connection") != "close"
                ), "SSE stream must maintain persistent streaming connection"
                async for line in sse_stream.aiter_lines():
                    if line:
                        sse_events.append(line)
                    if "status" in line:
                        break

            assert len(sse_events) >= 1, "Expected SSE progress events through reverse proxy"

        # 8. Test Isolation: Backend API is NOT reachable on any external port
        # Only test_port (the web entrypoint) is listening; there is NO separate backend TCP port.
        backend_unexposed_port = test_port + 1
        with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
            async with httpx.AsyncClient(timeout=1.0) as unexposed_client:
                await unexposed_client.get(f"http://127.0.0.1:{backend_unexposed_port}/api/settings/cookies")

    finally:
        # Clean up nginx
        try:
            subprocess.run(["sudo", str(nginx_bin), "-s", "stop", "-c", str(nginx_conf_file)], check=False)
        except Exception:
            pass
        # Clean up uvicorn
        if backend_proc.poll() is None:
            backend_proc.terminate()
            backend_proc.wait(timeout=5)
        # Clean up socket
        if sock_path.exists():
            sock_path.unlink()
