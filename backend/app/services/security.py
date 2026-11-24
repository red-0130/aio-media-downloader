"""Security utilities for SSRF protection and path traversal prevention."""

import asyncio
import ipaddress
import re
import socket
import urllib.parse
from pathlib import Path

TASK_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "[::1]",
    "169.254.169.254",  # AWS/GCP/Azure link-local metadata service
    "metadata.google.internal",
    "instance-data",
}


def _parse_posix_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """Parse alternate POSIX IPv4 representations (decimal integer, octal, hex, shortened)."""
    if not host or not isinstance(host, str):
        return None

    clean = host.strip().lower()
    parts = clean.split(".")
    if not (1 <= len(parts) <= 4):
        return None

    parsed_parts: list[int] = []
    for p in parts:
        if not p:
            return None
        try:
            if p.startswith("0x"):
                val = int(p, 16)
            elif len(p) > 1 and p.startswith("0") and all(c in "01234567" for c in p):
                val = int(p, 8)
            elif p.isdigit():
                val = int(p, 10)
            else:
                return None
            parsed_parts.append(val)
        except ValueError:
            return None

    # POSIX inet_aton component bit widths
    if len(parsed_parts) == 1:
        if 0 <= parsed_parts[0] <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(parsed_parts[0])
    elif len(parsed_parts) == 2:
        if 0 <= parsed_parts[0] <= 0xFF and 0 <= parsed_parts[1] <= 0xFFFFFF:
            return ipaddress.IPv4Address((parsed_parts[0] << 24) | parsed_parts[1])
    elif len(parsed_parts) == 3:
        if (
            0 <= parsed_parts[0] <= 0xFF
            and 0 <= parsed_parts[1] <= 0xFF
            and 0 <= parsed_parts[2] <= 0xFFFF
        ):
            return ipaddress.IPv4Address(
                (parsed_parts[0] << 24) | (parsed_parts[1] << 16) | parsed_parts[2]
            )
    elif len(parsed_parts) == 4:
        if all(0 <= x <= 0xFF for x in parsed_parts):
            return ipaddress.IPv4Address(
                (parsed_parts[0] << 24)
                | (parsed_parts[1] << 16)
                | (parsed_parts[2] << 8)
                | parsed_parts[3]
            )

    return None


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address belongs to loopback, private, link-local, or cloud metadata."""
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True

    # Check for IPv4 mapped in IPv6
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return _is_disallowed_ip(ip.ipv4_mapped)

    # Explicit AWS/cloud metadata check
    if str(ip) in ("169.254.169.254", "fd00:ec2::254"):
        return True

    # 0.0.0.0/8 source network
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.IPv4Network("0.0.0.0/8"):
        return True

    return False


def _extract_and_validate_hostname(url: str) -> tuple[bool, str | None]:
    """Validate preliminary URL syntax and hostname against internal/blocked rules."""
    if not url or not isinstance(url, str):
        return False, None

    url_str = url.strip()
    try:
        parsed = urllib.parse.urlsplit(url_str)
    except Exception:
        return False, None

    if parsed.scheme.lower() not in ("http", "https"):
        return False, None

    hostname = parsed.hostname
    if not hostname:
        return False, None

    hostname_lower = hostname.lower().strip("[]")

    if hostname_lower in BLOCKED_HOSTS:
        return False, None

    if (
        hostname_lower.endswith(".localhost")
        or hostname_lower.endswith(".local")
        or hostname_lower.endswith(".internal")
    ):
        return False, None

    # Check alternate POSIX IPv4 representations (integer, octal, hex, shortened)
    posix_ip = _parse_posix_ipv4(hostname_lower)
    if posix_ip is not None:
        if _is_disallowed_ip(posix_ip):
            return False, None

    # Check direct standard IP literal
    try:
        raw_ip = ipaddress.ip_address(hostname_lower)
        if _is_disallowed_ip(raw_ip):
            return False, None
    except ValueError:
        pass

    return True, hostname_lower


def _check_addr_info(addr_info: list) -> bool:
    """Validate resolved getaddrinfo IP records to protect against SSRF/DNS rebinding."""
    for item in addr_info:
        sockaddr = item[4]
        ip_str = sockaddr[0]
        try:
            resolved_ip = ipaddress.ip_address(ip_str)
            if _is_disallowed_ip(resolved_ip):
                return False
        except ValueError:
            continue
    return True


async def is_safe_url_async(url: str) -> bool:
    """Validate that a URL uses http/https and does not point to private or internal addresses asynchronously."""
    safe, hostname_lower = _extract_and_validate_hostname(url)
    if not safe or not hostname_lower:
        return False

    try:
        loop = asyncio.get_running_loop()
        addr_info = await loop.getaddrinfo(hostname_lower, None)
        return _check_addr_info(addr_info)
    except RuntimeError:
        addr_info = socket.getaddrinfo(hostname_lower, None)
        return _check_addr_info(addr_info)
    except (socket.gaierror, socket.herror, OSError):
        # Unresolvable domain; hostname is not an internal IP
        return True


async def validate_url_async(url: str) -> str:
    """Validate URL asynchronously and return it if safe; raise ValueError if unsafe."""
    if not await is_safe_url_async(url):
        raise ValueError(f"Invalid or disallowed URL: {url}")
    return url.strip()


def is_safe_url(url: str) -> bool:
    """Validate that a URL uses http/https and does not point to private or internal addresses."""
    safe, hostname_lower = _extract_and_validate_hostname(url)
    if not safe or not hostname_lower:
        return False

    try:
        addr_info = socket.getaddrinfo(hostname_lower, None)
        return _check_addr_info(addr_info)
    except (socket.gaierror, socket.herror, OSError):
        # Unresolvable domain; hostname is not an internal IP
        return True


def validate_url(url: str) -> str:
    """Validate URL and return it if safe; raise ValueError if unsafe."""
    if not is_safe_url(url):
        raise ValueError(f"Invalid or disallowed URL: {url}")
    return url.strip()


def validate_safe_path(base_dir: Path, target_path: Path | str) -> Path:
    """Ensure target path resolves strictly inside base_dir to prevent directory traversal.

    Raises ValueError if path traversal is detected.
    """
    resolved_base = Path(base_dir).resolve()
    target = Path(target_path)

    # If target is absolute, check relation to base_dir or resolve directly against base_dir
    if target.is_absolute():
        resolved_target = target.resolve()
    else:
        resolved_target = (resolved_base / target).resolve()

    try:
        resolved_target.relative_to(resolved_base)
    except ValueError:
        raise ValueError(f"Path traversal detected: {target_path} is outside {base_dir}")

    return resolved_target


def is_valid_task_id(task_id: str) -> bool:
    """Validate that task_id is a non-empty, safe alphanumeric/hyphen/underscore identifier."""
    if not task_id or not isinstance(task_id, str):
        return False
    clean = task_id.strip()
    if not clean or clean in (".", "..") or "/" in clean or "\\" in clean or "\0" in clean:
        return False
    return bool(TASK_ID_REGEX.match(clean))


def validate_task_id(task_id: str) -> str:
    """Validate task_id or raise ValueError."""
    if not is_valid_task_id(task_id):
        raise ValueError(f"Invalid or unsafe task ID: '{task_id}'")
    return task_id.strip()


