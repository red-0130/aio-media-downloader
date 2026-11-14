"""Cookie management service for Netscape HTTP cookie files."""

import contextlib
import os
import re
import stat
import tempfile
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.cookies import CookieStatus

SUPPORTED_PLATFORMS = ("instagram", "twitter", "youtube")

KEY_COOKIES_BY_PLATFORM = {
    "instagram": ["sessionid"],
    "twitter": ["auth_token", "ct0"],
    "youtube": ["SID", "__Secure-1PSID", "LOGIN_INFO"],
}


def sanitize_platform(platform: str) -> str:
    """Sanitize platform name against directory traversal."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", platform).lower()
    if not cleaned:
        raise ValueError(f"Invalid platform name: '{platform}'")
    return cleaned


def _safe_timestamp_to_iso(ts: int | float | None) -> str | None:
    """Convert timestamp to ISO string handling milliseconds and overflow (> year 9999)."""
    if ts is None or ts <= 0:
        return None
    try:
        val = float(ts)
        if val > 100_000_000_000:
            val = val / 1000.0
        dt = datetime.fromtimestamp(val, tz=timezone.utc)
        return dt.isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def parse_netscape_cookies(content: str) -> list[dict[str, Any]]:
    """Parse Netscape HTTP Cookie File formatted text into list of cookie dicts."""
    cookies: list[dict[str, Any]] = []
    if not content:
        return cookies

    for line in content.splitlines():
        line = line.strip("\r\n")
        if not line.strip():
            continue

        # Handle #HttpOnly_ prefix
        is_http_only = False
        if line.startswith("#HttpOnly_"):
            is_http_only = True
            line = line[len("#HttpOnly_") :]
        elif line.startswith("#"):
            # Comment line
            continue

        # Netscape format has 7 tab- or whitespace-separated columns
        parts = line.split("\t")
        if len(parts) == 6:
            parts.append("")
        elif len(parts) < 6:
            # Fallback to whitespace split if tabs were replaced by spaces (preserving cookie value with spaces)
            parts = line.strip().split(None, 6)
            if len(parts) == 6:
                parts.append("")
            elif len(parts) < 7:
                continue

        try:
            domain = parts[0]
            include_subdomains = parts[1].upper() == "TRUE"
            path = parts[2]
            secure = parts[3].upper() == "TRUE"
            expiry = int(parts[4])
            name = parts[5]
            value = parts[6] if len(parts) > 6 else ""

            cookies.append(
                {
                    "domain": domain,
                    "include_subdomains": include_subdomains,
                    "path": path,
                    "secure": secure,
                    "expiry": expiry,
                    "name": name,
                    "value": value,
                    "http_only": is_http_only,
                }
            )
        except (ValueError, IndexError):
            continue

    return cookies


def verify_netscape_content(content: str) -> tuple[bool, int, str | None]:
    """Verify that content matches Netscape HTTP cookie format.

    Returns: (is_valid, cookie_count, error_message)
    """
    if not content or not content.strip():
        return False, 0, "Cookie content is empty"

    cookies = parse_netscape_cookies(content)
    if not cookies:
        # Check if there is at least header
        if "# Netscape HTTP Cookie File" in content or "# HTTP Cookie File" in content:
            return True, 0, "Valid header but no cookie entries found"
        return False, 0, "Invalid format: no valid Netscape cookie entries found"

    return True, len(cookies), None


def get_cookie_file_path(platform: str) -> Path:
    """Get the cookie file path for a given platform, ensuring safe resolution inside COOKIES_DIR."""
    platform_clean = sanitize_platform(platform)
    settings.ensure_directories()
    target = (settings.COOKIES_DIR / f"{platform_clean}.txt").resolve()
    if not target.is_relative_to(settings.COOKIES_DIR.resolve()):
        raise ValueError(f"Path traversal detected in platform name: '{platform}'")
    return target


def check_cookie_status(platform: str) -> CookieStatus:
    """Inspect cookie file for a platform and evaluate validity and expiration."""
    try:
        platform_clean = sanitize_platform(platform)
        path = get_cookie_file_path(platform_clean)
    except Exception as e:
        return CookieStatus(
            platform=platform,
            exists=False,
            valid=False,
            expires_at=None,
            cookie_count=0,
            details=f"Invalid platform: {e}",
        )

    if not path.exists():
        return CookieStatus(
            platform=platform_clean,
            exists=False,
            valid=False,
            expires_at=None,
            cookie_count=0,
            details="No cookie file found on disk",
        )

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return CookieStatus(
            platform=platform_clean,
            exists=True,
            valid=False,
            expires_at=None,
            cookie_count=0,
            details=f"Failed to read cookie file: {e}",
        )

    cookies = parse_netscape_cookies(content)
    if not cookies:
        return CookieStatus(
            platform=platform_clean,
            exists=True,
            valid=False,
            expires_at=None,
            cookie_count=0,
            details="Cookie file is empty or corrupted",
        )

    # Check expiration of key session cookies for platform
    key_names = KEY_COOKIES_BY_PLATFORM.get(platform_clean, [])
    now_ts = int(time.time())

    key_cookie_found = False
    earliest_key_expiry: int | None = None
    is_key_expired = False

    for cookie in cookies:
        if cookie["name"] in key_names:
            key_cookie_found = True
            expiry = cookie["expiry"]
            if expiry > 100_000_000_000:
                expiry = expiry // 1000
            if expiry > 0:
                if earliest_key_expiry is None or expiry < earliest_key_expiry:
                    earliest_key_expiry = expiry
                if expiry < now_ts:
                    is_key_expired = True

    # If key cookie found and expired
    if key_cookie_found and is_key_expired:
        expires_iso = _safe_timestamp_to_iso(earliest_key_expiry)
        return CookieStatus(
            platform=platform_clean,
            exists=True,
            valid=False,
            expires_at=expires_iso,
            cookie_count=len(cookies),
            details=f"Session cookie for {platform_clean} has expired",
        )

    # Key cookie found and valid
    if key_cookie_found and earliest_key_expiry:
        expires_iso = _safe_timestamp_to_iso(earliest_key_expiry)
        return CookieStatus(
            platform=platform_clean,
            exists=True,
            valid=True,
            expires_at=expires_iso,
            cookie_count=len(cookies),
            details=f"Valid session cookies found ({len(cookies)} total)",
        )

    # Generic cookies found (no specific key cookie found or key cookie has no expiry / session-only)
    return CookieStatus(
        platform=platform_clean,
        exists=True,
        valid=True,
        expires_at=None,
        cookie_count=len(cookies),
        details=f"Cookies loaded ({len(cookies)} total, no expiring key session cookie)",
    )


def save_cookies(platform: str, content: str) -> CookieStatus:
    """Save raw Netscape cookie content to platform cookie file."""
    platform_clean = sanitize_platform(platform)
    is_valid, count, err = verify_netscape_content(content)
    if not is_valid:
        raise ValueError(err or "Invalid cookie content format")

    settings.ensure_directories()
    path = get_cookie_file_path(platform_clean)

    # Ensure file starts with Netscape header if missing
    clean_content = content.strip()
    if not clean_content.startswith("# Netscape HTTP Cookie File") and not clean_content.startswith("# HTTP Cookie File"):
        clean_content = "# Netscape HTTP Cookie File\n" + clean_content

    existing_mode = path.stat().st_mode if path.exists() else None
    temp_file = tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8")
    try:
        if existing_mode is not None:
            try:
                os.chmod(temp_file.name, stat.S_IMODE(existing_mode))
            except OSError:
                pass
        temp_file.write(clean_content + "\n")
        temp_file.flush()
        temp_file.close()
        Path(temp_file.name).replace(path)
    except Exception:
        Path(temp_file.name).unlink(missing_ok=True)
        raise
    return check_cookie_status(platform_clean)


def delete_cookies(platform: str) -> bool:
    """Delete cookie file for platform."""
    try:
        path = get_cookie_file_path(platform)
        if path.exists():
            path.unlink()
            return True
    except Exception:
        pass
    return False


def get_all_cookie_statuses() -> dict[str, CookieStatus]:
    """Return cookie status for all supported platforms."""
    return {p: check_cookie_status(p) for p in SUPPORTED_PLATFORMS}


def get_cookie_path_for_platform(platform: str) -> Path | None:
    """Return path to cookie file if exists and is valid, else None."""
    try:
        status = check_cookie_status(platform)
        if status.exists and status.valid:
            return get_cookie_file_path(platform)
    except Exception:
        pass
    return None


@contextlib.asynccontextmanager
async def resolve_cookies_context(
    platform: str,
    client_cookies: dict[str, str | None] | str | None = None,
    task_dir: Path | None = None,
) -> AsyncIterator[Path | None]:
    """Resolve cookie file path: client session cookie if provided and valid, else server cookie.

    Yields Path to cookie file, or None if no valid cookies are configured.
    Temporary files created for client session cookies are safely placed in system tempdir
    with restricted user-only permissions (0o600) and cleanly unlinked on context exit,
    completely isolated from downloads directory and server cookie files.
    """
    cookie_content: str | None = None
    if isinstance(client_cookies, dict):
        raw = client_cookies.get(platform)
        if raw and isinstance(raw, str) and raw.strip():
            cookie_content = raw
        if not cookie_content:
            plat_lower = platform.lower()
            for k, v in client_cookies.items():
                if isinstance(k, str) and k.strip().lower() == plat_lower:
                    if v and isinstance(v, str) and v.strip():
                        cookie_content = v
                        break
            if not cookie_content and plat_lower in ("twitter", "x"):
                for k, v in client_cookies.items():
                    if isinstance(k, str) and k.strip().lower() in ("twitter", "x"):
                        if v and isinstance(v, str) and v.strip():
                            cookie_content = v
                            break
    elif isinstance(client_cookies, str):
        if client_cookies.strip():
            cookie_content = client_cookies

    if cookie_content and cookie_content.strip():
        # Validate format
        is_valid, count, err = verify_netscape_content(cookie_content)
        if not is_valid:
            raise ValueError(f"Invalid client cookie format: {err}")

        clean_content = cookie_content.strip()
        if not clean_content.startswith("# Netscape HTTP Cookie File") and not clean_content.startswith(
            "# HTTP Cookie File"
        ):
            clean_content = "# Netscape HTTP Cookie File\n" + clean_content

        try:
            platform_clean = sanitize_platform(platform)
        except Exception:
            platform_clean = "session"

        # Always place temporary auth cookie files in secure system tempdir, never inside task_dir
        temp_file = tempfile.NamedTemporaryFile(
            "w",
            dir=None,
            prefix=f"client_cookies_{platform_clean}_",
            suffix=".txt",
            delete=False,
            encoding="utf-8",
        )
        temp_path = Path(temp_file.name)
        try:
            try:
                os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            temp_file.write(clean_content + "\n")
            temp_file.flush()
            temp_file.close()
            yield temp_path
        finally:
            temp_path.unlink(missing_ok=True)
    else:
        # Fall back to server-level cookie
        yield get_cookie_path_for_platform(platform)

