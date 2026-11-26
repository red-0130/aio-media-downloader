"""Shared async subprocess runner, error classification, and proxy secret redaction."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable
import inspect
import re
import urllib.parse

from app.config import settings


class ExtractionError(Exception):
    """Generic media extraction failure."""


class AuthRequiredError(ExtractionError):
    """Authentication required to access media (login wall, private post)."""


class RateLimitError(ExtractionError):
    """Platform rate limit reached (HTTP 429)."""


def _scrub_full_proxy(text: str, proxy_url: str) -> str:
    """Replace full proxy URL, netloc, and password occurrences with redaction markers."""
    text = text.replace(proxy_url, "[REDACTED_PROXY]")
    try:
        parsed = urllib.parse.urlsplit(proxy_url)
        if parsed.netloc and parsed.netloc in text:
            text = text.replace(parsed.netloc, "[REDACTED_PROXY]")
        if parsed.password and parsed.password in text:
            text = text.replace(parsed.password, "[REDACTED]")
    except Exception:
        pass
    return text


def redact_proxy_secrets(
    text: str,
    extra_proxies: Iterable[str | None] = (),
) -> str:
    """Scrub configured SOCKS5_PROXY, caller-supplied proxies, and inline URL credentials."""
    if not text:
        return text

    if settings.SOCKS5_PROXY:
        text = _scrub_full_proxy(text, settings.SOCKS5_PROXY)

    for raw_proxy in extra_proxies:
        if not raw_proxy or not raw_proxy.strip():
            continue
        proxy_url = raw_proxy.strip()
        if settings.SOCKS5_PROXY and proxy_url == settings.SOCKS5_PROXY:
            continue
        try:
            parsed = urllib.parse.urlsplit(proxy_url)
        except Exception:
            text = text.replace(proxy_url, "[REDACTED_PROXY]")
            continue

        if "@" in parsed.netloc and (parsed.username is not None or parsed.password is not None):
            # Preserve scheme://user:[REDACTED]@host format for runtime/request proxies
            user_part = parsed.username or ""
            host_part = parsed.netloc.rsplit("@", 1)[1]
            scrubbed_netloc = f"{user_part}:[REDACTED]@{host_part}"
            scrubbed_proxy = proxy_url.replace(parsed.netloc, scrubbed_netloc, 1)
            text = text.replace(proxy_url, scrubbed_proxy)
            if parsed.netloc in text:
                text = text.replace(parsed.netloc, scrubbed_netloc)
        else:
            text = _scrub_full_proxy(text, proxy_url)

    return re.sub(r"://([^\s/@:]*):([^\s/@]*)@", r"://\1:[REDACTED]@", text)


def classify_error(
    stderr_text: str,
    extra_proxies: Iterable[str | None] = (),
) -> ExtractionError:
    """Analyze stderr or extractor output and return appropriate specialized exception."""
    stderr_text = redact_proxy_secrets(stderr_text, extra_proxies=extra_proxies)
    text_lower = stderr_text.lower()

    # 1. Age-restricted or private media (strictly requires user account cookies)
    if any(
        term in text_lower
        for term in (
            "confirm your age",
            "age-restricted",
            "sign in to confirm your age",
            "private video",
            "this video is private",
            "private account",
            "this account is private",
            "members-only",
        )
    ):
        return AuthRequiredError(
            f"Authentication required: Age-restricted or private content. Please supply authenticated cookies in Settings. ({stderr_text.strip()})"
        )

    # 2. Platform Bot / Login walls
    if any(
        term in text_lower
        for term in (
            "sign in to confirm",
            "sign in to",
            "login required",
            "login_required",
            "login page",
            "redirect to login",
            "accounts/login",
            "checkpoint_required",
            "protected tweets",
            "registered users",
            "requires authentication",
            "authentication required",
            "could not authenticate you",
            "http error 401",
            "http error 403",
            "'unavailable'",
        )
    ):
        return AuthRequiredError(
            f"Authentication required: Bot verification or login required. Try alternate player clients or provide cookies in Settings. ({stderr_text.strip()})"
        )

    if any(
        term in text_lower
        for term in (
            "http error 429",
            "too many requests",
            "rate limit",
            "rate-limited",
            "exceeded the rate-limit",
        )
    ):
        return RateLimitError(
            f"Rate limited by platform. Please wait or configure a proxy in Settings. ({stderr_text.strip()})"
        )

    return ExtractionError(f"Extraction failed: {stderr_text.strip()}")


async def run_subprocess(
    cmd: list[str],
    *,
    on_stdout_line: Callable[[str], Awaitable[None] | None] | None = None,
) -> tuple[int, str, str]:
    """Execute a subprocess safely with guaranteed kill-and-wait cleanup on cancel/error."""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_task: asyncio.Task | None = None
    stderr_lines: list[str] = []
    try:
        if on_stdout_line is None:
            stdout_b, stderr_b = await process.communicate()
            returncode = process.returncode if process.returncode is not None else 0
            return (
                returncode,
                stdout_b.decode("utf-8", errors="replace"),
                stderr_b.decode("utf-8", errors="replace"),
            )

        async def _read_stderr() -> None:
            if process.stderr:
                while line_b := await process.stderr.readline():
                    stderr_lines.append(line_b.decode("utf-8", errors="replace"))

        stderr_task = asyncio.create_task(_read_stderr())
        if process.stdout:
            while line_b := await process.stdout.readline():
                res = on_stdout_line(line_b.decode("utf-8", errors="replace").strip())
                if inspect.isawaitable(res):
                    await res

        await process.wait()
        await stderr_task
        returncode = process.returncode if process.returncode is not None else 0
        return returncode, "", "".join(stderr_lines)
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            except Exception:
                pass
            try:
                await asyncio.shield(process.wait())
            except (asyncio.CancelledError, Exception):
                pass
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()
            try:
                await stderr_task
            except (asyncio.CancelledError, Exception):
                pass
