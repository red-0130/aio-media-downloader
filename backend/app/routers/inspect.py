"""API route handler for media metadata inspection."""

from fastapi import APIRouter, HTTPException, status

from app.models.inspect import InspectRequest, InspectResponse
from app.services import router as media_router
from app.services._exec import (
    AuthRequiredError,
    ExtractionError,
    RateLimitError,
    redact_proxy_secrets,
)

router = APIRouter()


@router.post("/inspect", response_model=InspectResponse)
async def inspect_media(request: InspectRequest):
    """Probe target URL for available media qualities, items, and formats."""
    try:
        ctx = await media_router.prepare_context(
            request.url,
            proxy=request.proxy,
            cookies=request.cookies,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    try:
        return await media_router.inspect(
            ctx.clean_url,
            proxy=ctx.effective_proxy,
            cookies=ctx.client_cookies,
            context=ctx,
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
            detail=redact_proxy_secrets(str(e), extra_proxies=(ctx.effective_proxy,)),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inspection failed: {redact_proxy_secrets(str(e), extra_proxies=(ctx.effective_proxy,))}",
        )
