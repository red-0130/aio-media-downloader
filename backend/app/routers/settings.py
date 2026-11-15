"""API route handler for cookie storage and SOCKS5 proxy runtime settings."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.models.cookies import CookieStatus, CookieUpdateRequest
from app.models.proxy import ProxyConfig, ProxyUpdateRequest
from app.services import cookie_manager, proxy_manager

router = APIRouter()
MAX_COOKIE_FILE_SIZE = 5 * 1024 * 1024  # 5 MB (5,242,880 bytes)


def _validate_platform(platform: str) -> str:
    """Validate platform name against traversal and supported platform list."""
    if not platform or not isinstance(platform, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Platform name cannot be empty",
        )
    if ".." in platform or "/" in platform or "\\" in platform:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path traversal or invalid characters detected in platform: '{platform}'",
        )
    try:
        clean = cookie_manager.normalize_platform(platform)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    if clean not in cookie_manager.SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported platform '{platform}'. Supported: {cookie_manager.SUPPORTED_PLATFORMS}",
        )
    return clean


@router.get("/cookies", response_model=dict[str, CookieStatus])
async def get_all_cookies():
    """Return status of cookie files for all supported platforms."""
    return cookie_manager.get_all_cookie_statuses()


@router.post("/cookies")
async def save_pasted_cookies(body: CookieUpdateRequest):
    """Save pasted Netscape cookies for a specific platform."""
    plat = _validate_platform(body.platform)
    if len(body.content.encode("utf-8")) > MAX_COOKIE_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Pasted cookie content exceeds maximum allowed size of 5MB",
        )
    try:
        status_res = cookie_manager.save_cookies(plat, body.content)
        return {"status": "saved", "platform": plat, "cookie_status": status_res}
    except HTTPException:
        raise
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@router.post("/cookies/upload")
async def upload_cookie_file(
    platform: str = Form(..., description="Target platform (instagram, twitter, youtube, tiktok)"),
    file: UploadFile = File(..., description="Netscape cookie file"),
):
    """Upload a Netscape cookies.txt file for a specific platform."""
    plat = _validate_platform(platform)
    try:
        if file.size is not None and file.size > MAX_COOKIE_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Uploaded cookie file exceeds maximum allowed size of 5MB",
            )

        chunks: list[bytes] = []
        total_bytes = 0
        chunk_size = 64 * 1024

        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > MAX_COOKIE_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="Uploaded cookie file exceeds maximum allowed size of 5MB",
                )
            chunks.append(chunk)

        raw_bytes = b"".join(chunks)
        content = raw_bytes.decode("utf-8", errors="replace")
        if not content.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded cookie file is empty",
            )
        status_res = cookie_manager.save_cookies(plat, content)
        return {"status": "uploaded", "platform": plat, "cookie_status": status_res}
    except HTTPException:
        raise
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@router.delete("/cookies/{platform}")
async def delete_platform_cookies(platform: str):
    """Remove cookie file for a specific platform."""
    plat = _validate_platform(platform)
    deleted = cookie_manager.delete_cookies(plat)
    return {"status": "deleted" if deleted else "not_found", "platform": plat}


@router.get("/proxy", response_model=ProxyConfig)
async def get_proxy_configuration():
    """Retrieve current effective SOCKS5 / HTTP proxy configuration."""
    return proxy_manager.get_proxy_config(client_facing=True)


@router.post("/proxy", response_model=ProxyConfig)
async def set_proxy_configuration(body: ProxyUpdateRequest):
    """Update runtime SOCKS5 / HTTP proxy configuration."""
    try:
        proxy_manager.set_proxy(body.proxy)
        return proxy_manager.get_proxy_config(client_facing=True)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))
