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

SUPPORTED_PLATFORMS = ("instagram", "twitter", "youtube", "tiktok")

KEY_COOKIES_BY_PLATFORM = {
    "instagram": ["sessionid"],
    "twitter": ["auth_token", "ct0"],
    "youtube": ["SID", "__Secure-1PSID", "LOGIN_INFO"],
    "tiktok": ["sessionid", "sessionid_ss", "sid_tt", "sid_guard"],
}


def sanitize_platform(platform: str) -> str:
    """Sanitize platform name against directory traversal."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", platform).lower()
    if not cleaned:
        raise ValueError(f"Invalid platform name: '{platform}'")
    return cleaned


def normalize_platform(platform: str) -> str:
    """Normalize platform name and aliases to canonical platform identifier."""
    cleaned = sanitize_platform(platform)
    if cleaned in ("twitter", "x"):
        return "twitter"
    if cleaned in ("instagram", "ig"):
        return "instagram"
    if cleaned in ("youtube", "yt"):
        return "youtube"
    if cleaned in ("tiktok", "tt"):
        return "tiktok"
    return cleaned


_runtime_default_cookie_paths: dict[str, Path] = {}


def set_default_cookie_path(platform: str, path: Path | str | None) -> None:
    """Set or remove runtime default cookie path for a platform."""
    plat = normalize_platform(platform)
    if path is None:
        _runtime_default_cookie_paths.pop(plat, None)
    else:
        p = Path(path).resolve()
        _runtime_default_cookie_paths[plat] = p


def reset_runtime_default_cookies() -> None:
    """Reset all runtime configured default cookie paths."""
    _runtime_default_cookie_paths.clear()


def validate_netscape_file(file_path: Path | str) -> tuple[bool, int, str | None]:
    """Validate whether a file on disk contains valid Netscape HTTP cookies.

    Returns: (is_valid, cookie_count, error_message)
    """
    p = Path(file_path)
    if not p.exists():
        return False, 0, f"Cookie file does not exist: {file_path}"
    if not p.is_file():
        return False, 0, f"Cookie path is not a regular file: {file_path}"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        return verify_netscape_content(content)
    except Exception as e:
        return False, 0, f"Failed to read cookie file: {e}"


def _find_candidate_cookie_path(platform: str) -> Path:
    """Find candidate cookie file path for a platform across runtime overrides, env vars, and storage dirs."""
    plat = normalize_platform(platform)

    # 1. Runtime override
    if plat in _runtime_default_cookie_paths:
        return _runtime_default_cookie_paths[plat]

    # 2. Platform environment variable
    env_attr = f"{plat.upper()}_COOKIES_FILE"
    env_val = getattr(settings, env_attr, None) or os.getenv(env_attr) or os.getenv(f"{plat.upper()}_COOKIE_FILE")
    if env_val:
        return Path(env_val).resolve()

    if plat == "twitter":
        x_val = getattr(settings, "TWITTER_COOKIES_FILE", None) or os.getenv("X_COOKIES_FILE") or os.getenv("X_COOKIE_FILE")
        if x_val:
            return Path(x_val).resolve()

    # 3. Default and primary cookies directories
    settings.ensure_directories()
    candidates = [
        settings.DEFAULT_COOKIES_DIR / f"{plat}.txt",
        settings.COOKIES_DIR / f"{plat}.txt",
    ]
    if plat == "twitter":
        candidates.extend([
            settings.DEFAULT_COOKIES_DIR / "x.txt",
            settings.COOKIES_DIR / "x.txt",
        ])
    elif plat == "tiktok":
        candidates.extend([
            settings.DEFAULT_COOKIES_DIR / "tt.txt",
            settings.COOKIES_DIR / "tt.txt",
        ])
    elif plat == "instagram":
        candidates.extend([
            settings.DEFAULT_COOKIES_DIR / "ig.txt",
            settings.COOKIES_DIR / "ig.txt",
        ])
    elif plat == "youtube":
        candidates.extend([
            settings.DEFAULT_COOKIES_DIR / "yt.txt",
            settings.COOKIES_DIR / "yt.txt",
        ])

    for cand in candidates:
        if cand.exists():
            return cand.resolve()

    return (settings.COOKIES_DIR / f"{plat}.txt").resolve()


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
    platform_clean = normalize_platform(platform)
    settings.ensure_directories()
    target = (settings.COOKIES_DIR / f"{platform_clean}.txt").resolve()
    if not target.is_relative_to(settings.COOKIES_DIR.resolve()):
        raise ValueError(f"Path traversal detected in platform name: '{platform}'")
    return target


def check_cookie_status(platform: str, path: Path | None = None) -> CookieStatus:
    """Inspect cookie file for a platform and evaluate validity and expiration."""
    try:
        platform_clean = normalize_platform(platform)
        if path is None:
            path = _find_candidate_cookie_path(platform_clean)
    except Exception as e:
        return CookieStatus(
            platform=platform,
            exists=False,
            valid=False,
            expires_at=None,
            cookie_count=0,
            details=f"Invalid platform: {e}",
        )

    if path is None or not path.exists():
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

    # Netscape format verification
    is_valid_format, cookie_count, err = verify_netscape_content(content)
    if not is_valid_format or cookie_count == 0:
        return CookieStatus(
            platform=platform_clean,
            exists=True,
            valid=False,
            expires_at=None,
            cookie_count=0,
            details=err or "Cookie file is empty or corrupted",
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
    platform_clean = normalize_platform(platform)
    is_valid, count, err = verify_netscape_content(content)
    if not is_valid:
        raise ValueError(err or "Invalid cookie content format")
    if count == 0:
        raise ValueError(err or "No valid Netscape cookie entries found")

    settings.ensure_directories()
    path = get_cookie_file_path(platform_clean)

    # Ensure file starts with Netscape header if missing
    clean_content = content.strip()
    if not clean_content.startswith("# Netscape HTTP Cookie File") and not clean_content.startswith(
        "# HTTP Cookie File"
    ):
        clean_content = "# Netscape HTTP Cookie File\n" + clean_content

    _runtime_default_cookie_paths.pop(platform_clean, None)

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
    plat = normalize_platform(platform)
    _runtime_default_cookie_paths.pop(plat, None)
    deleted = False
    try:
        path = get_cookie_file_path(plat)
        if path.exists():
            path.unlink()
            deleted = True
    except Exception:
        pass
    return deleted


def get_all_cookie_statuses() -> dict[str, CookieStatus]:
    """Return cookie status for all supported platforms."""
    return {p: check_cookie_status(p) for p in SUPPORTED_PLATFORMS}


def get_default_cookie_path(platform: str) -> Path | None:
    """Return path to default cookie file if it exists and is valid Netscape format, else None."""
    try:
        plat = normalize_platform(platform)
        status = check_cookie_status(plat)
        if status.exists and status.valid:
            cand = _find_candidate_cookie_path(plat)
            if cand and cand.exists():
                return cand
    except Exception:
        pass
    return None


def get_cookie_path_for_platform(platform: str) -> Path | None:
    """Return path to cookie file if exists and is valid, else None.

    Delegates to get_default_cookie_path.
    """
    return get_default_cookie_path(platform)


def load_default_cookie(platform: str) -> str | None:
    """Load and return text content of default cookie file for a platform if valid, else None."""
    path = get_default_cookie_path(platform)
    if not path or not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def load_default_cookie_file(platform: str, file_path: Path | str) -> CookieStatus:
    """Load, validate, and store a default cookie file for a platform."""
    plat = normalize_platform(platform)
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        raise ValueError(f"Cookie file not found: {file_path}")
    content = p.read_text(encoding="utf-8", errors="replace")
    return save_cookies(plat, content)


def configure_default_cookie(platform: str, path_or_content: str | Path) -> CookieStatus:
    """Configure default cookie for platform from a file path or Netscape cookie content string."""
    plat = normalize_platform(platform)
    if isinstance(path_or_content, Path) or (
        isinstance(path_or_content, str)
        and "\n" not in path_or_content
        and (Path(path_or_content).exists() or "/" in path_or_content or "\\" in path_or_content)
    ):
        file_path = Path(path_or_content)
        if not file_path.exists() or not file_path.is_file():
            raise ValueError(f"Cookie file does not exist: {file_path}")
        is_valid, count, err = validate_netscape_file(file_path)
        if not is_valid or count == 0:
            raise ValueError(err or f"Invalid Netscape cookie file at {file_path}")
        set_default_cookie_path(plat, file_path)
        return check_cookie_status(plat)
    else:
        return save_cookies(plat, str(path_or_content))


def resolve_active_cookie_path(
    platform: str,
    client_cookies: dict[str, str | None] | str | None = None,
) -> Path | None:
    """Non-context helper to resolve default cookie path when no client cookies are provided."""
    return get_default_cookie_path(platform)


@contextlib.asynccontextmanager
async def resolve_cookies_context(
    platform: str,
    client_cookies: dict[str, str | None] | str | None = None,
    task_dir: Path | None = None,
) -> AsyncIterator[Path | None]:
    """Resolve cookie file path: client session cookie if provided and valid, else default cookie.

    Yields Path to cookie file, or None if no valid cookies are configured.
    Temporary files created for client session cookies are safely placed in system tempdir
    with restricted user-only permissions (0o600) and cleanly unlinked on context exit,
    completely isolated from downloads directory and server cookie files.
    """
    plat = normalize_platform(platform)
    cookie_content: str | None = None
    if isinstance(client_cookies, dict):
        raw = client_cookies.get(platform)
        if raw and isinstance(raw, str) and raw.strip():
            cookie_content = raw
        if not cookie_content:
            raw_plat = client_cookies.get(plat)
            if raw_plat and isinstance(raw_plat, str) and raw_plat.strip():
                cookie_content = raw_plat
        if not cookie_content:
            for k, v in client_cookies.items():
                if isinstance(k, str) and normalize_platform(k) == plat:
                    if v and isinstance(v, str) and v.strip():
                        cookie_content = v
                        break
    elif isinstance(client_cookies, str):
        if client_cookies.strip():
            cookie_content = client_cookies

    if cookie_content and cookie_content.strip():
        # Precedence Tier 1: Client session cookies provided
        is_valid, count, err = verify_netscape_content(cookie_content)
        if not is_valid:
            raise ValueError(f"Invalid client cookie format: {err}")

        clean_content = cookie_content.strip()
        if not clean_content.startswith("# Netscape HTTP Cookie File") and not clean_content.startswith(
            "# HTTP Cookie File"
        ):
            clean_content = "# Netscape HTTP Cookie File\n" + clean_content

        # Always place temporary auth cookie files in secure system tempdir, never inside task_dir
        temp_file = tempfile.NamedTemporaryFile(
            "w",
            dir=None,
            prefix=f"client_cookies_{plat}_",
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
        # Precedence Tier 2 & 3: Fall back to default cookie file, or None if missing/invalid/expired
        yield get_default_cookie_path(plat)

