"""FastAPI surface: the two endpoints the judge harness calls.

Status-code policy follows the problem statement rather than FastAPI's
defaults: a structurally invalid request is a 400, not the framework's 422.
Every failure leaves through one of the handlers below so that no stack trace,
prompt, provider body, or credential can reach a response.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.contracts import EnergyRequest, ErrorCategory, GridWiseError
from app.observability import configure_logging, get_logger, redact
from app.pipeline import run

logger = get_logger(__name__)

# Only a malformed or structurally invalid request is the caller's fault.
# Everything else is ours and must not leak detail.
_STATUS_BY_CATEGORY = {
    ErrorCategory.invalid_request: status.HTTP_400_BAD_REQUEST,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    # Import here so a provider construction failure surfaces at startup.
    from app.interpretation.provider import LLMProvider

    app.state.settings = settings
    app.state.provider = LLMProvider(settings)
    logger.info("gridwise ready %s", settings.describe())
    try:
        yield
    finally:
        await app.state.provider.aclose()


app = FastAPI(title="GridWise", version="1.0.0", lifespan=lifespan)


def _error(code: int, category: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": category, "detail": redact(detail)})


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Malformed JSON and schema violations are 400, not FastAPI's default 422."""
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    detail = f"{location or 'body'}: {first.get('msg', 'invalid request')}"
    return _error(status.HTTP_400_BAD_REQUEST, ErrorCategory.invalid_request.value, detail)


@app.exception_handler(GridWiseError)
async def on_gridwise_error(request: Request, exc: GridWiseError) -> JSONResponse:
    code = _STATUS_BY_CATEGORY.get(exc.category, status.HTTP_500_INTERNAL_SERVER_ERROR)
    if code >= 500:
        logger.error("category=%s %s", exc.category.value, redact(exc.message))
    return _error(code, exc.category.value, exc.message)


@app.exception_handler(Exception)
async def on_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Last resort. The class name is safe to log; the payload is not."""
    logger.exception("unhandled %s", type(exc).__name__)
    return _error(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "internal error while processing the request",
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Readiness only: no model call, no network I/O, no solver work."""
    return {"status": "ok"}


@app.post("/optimize-energy")
async def optimize_energy(payload: EnergyRequest, request: Request) -> JSONResponse:
    response, _trace = await run(payload, request.app.state.settings, request.app.state.provider)
    return JSONResponse(content=response.model_dump(mode="json"))
