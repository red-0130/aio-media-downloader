"""API route handler for media metadata inspection."""

from fastapi import APIRouter, HTTPException, status
from app.models.inspect import InspectRequest, InspectResponse
from app.services import cookie_manager, proxy_manager, router as media_router, security
from app.services.ytdlp_service import (
    AuthRequiredError,
    ExtractionError,
    RateLimitError,
)

router = APIRouter()


@router.post("/inspect", response_model=InspectResponse)
async def inspect_media(request: InspectRequest):
    """Probe target URL for available media qualities, items, and formats."""
    url = request.url
    if not url or not isinstance(url, str) or not url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL cannot be empty",
        )

    clean_url = url.strip()
    if not security.is_safe_url(clean_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or disallowed URL (SSRF protection): {url}",
        )

    # Validate client proxy if provided, else fall back to server configuration
    effective_proxy = (
        request.proxy.strip()
        if (request.proxy and request.proxy.strip())
        else proxy_manager.get_proxy()
    )
    if effective_proxy:
        try:
            proxy_manager.validate_proxy_url(effective_proxy)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    # Pre-validate client session cookies format if provided
    if request.cookies:
        if isinstance(request.cookies, str):
            if request.cookies.strip():
                is_valid, _, err = cookie_manager.verify_netscape_content(request.cookies)
                if not is_valid:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid client cookie format: {err}",
                    )
        elif isinstance(request.cookies, dict):
            for plat, val in request.cookies.items():
                if val and isinstance(val, str) and val.strip():
                    is_valid, _, err = cookie_manager.verify_netscape_content(val)
                    if not is_valid:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Invalid client cookie format for platform '{plat}': {err}",
                        )

    try:
        return await media_router.inspect(
            clean_url, proxy=effective_proxy, cookies=request.cookies
        )
    except AuthRequiredError as e:
        clean_msg = str(e).strip()
        if not clean_msg.startswith("Authentication required"):
            clean_msg = f"Authentication required: {clean_msg}"
        if "Settings" not in clean_msg:
            clean_msg = f"{clean_msg}. Please provide cookies in Settings."
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=clean_msg,
        )
    except RateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {e}. Please wait or configure proxy.",
        )
    except (ExtractionError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inspection failed: {e}",
        )
