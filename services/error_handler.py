"""
Error Handling Middleware for ClaudeProxyV3

This module provides centralized error handling for the FastAPI application,
including exception handlers, logging, and standardized error responses.

Usage:
    from services.error_handler import setup_error_handlers

    app = FastAPI()
    setup_error_handlers(app)
"""

import logging
import traceback
from typing import Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware

from services.exceptions import (
    ProxyException,
    AnalysisError,
    ExternalServiceError,
    ValidationError,
    SellerError,
    BlockedSellerError,
    RateLimitError,
    ConfigurationError,
)

logger = logging.getLogger(__name__)


# ============================================================
# Error Response Helpers
# ============================================================

def create_error_response(
    error: ProxyException,
    status_code: int = 500,
    request: Optional[Request] = None,
) -> JSONResponse:
    """Create a standardized JSON error response."""
    response_data = error.to_dict()

    # Add request context if available
    if request:
        response_data["path"] = str(request.url.path)
        response_data["method"] = request.method

    return JSONResponse(
        status_code=status_code,
        content=response_data,
    )


def create_error_html(
    title: str,
    message: str,
    details: Optional[str] = None,
    recommendation: str = "PASS",
) -> str:
    """Create an HTML error response for the dashboard."""
    detail_html = f'<p style="color:#888;font-size:12px;">{details}</p>' if details else ''

    return f'''
    <div style="background:#1a1a2e;border-radius:12px;padding:20px;margin:10px;border-left:4px solid #ef4444;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
                <h3 style="color:#ef4444;margin:0;">{title}</h3>
                <p style="color:#e0e0e0;margin:10px 0;">{message}</p>
                {detail_html}
            </div>
            <div style="text-align:center;">
                <div style="font-size:24px;font-weight:bold;color:#ef4444;">{recommendation}</div>
                <div style="font-size:12px;color:#888;">Error Response</div>
            </div>
        </div>
    </div>
    '''


# ============================================================
# Exception Handlers
# ============================================================

async def handle_proxy_exception(
    request: Request,
    exc: ProxyException,
) -> JSONResponse:
    """Handle ProxyException and its subclasses."""

    # Determine status code based on exception type
    status_code = 500
    if isinstance(exc, ValidationError):
        status_code = 400
    elif isinstance(exc, BlockedSellerError):
        status_code = 403
    elif isinstance(exc, RateLimitError):
        status_code = 429
    elif isinstance(exc, ConfigurationError):
        status_code = 503
    elif isinstance(exc, ExternalServiceError):
        status_code = 502

    # Log the error
    log_level = logging.WARNING if status_code < 500 else logging.ERROR
    logger.log(
        log_level,
        f"[{exc.code}] {exc.message}",
        extra={"details": exc.details, "cause": str(exc.cause) if exc.cause else None},
    )

    return create_error_response(exc, status_code, request)


async def handle_generic_exception(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle unexpected exceptions."""

    # Log full traceback for debugging
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {exc}",
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
            "path": str(request.url.path),
        },
    )


# ============================================================
# Error Handling Middleware
# ============================================================

class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that catches exceptions and returns appropriate responses.

    This middleware:
    - Catches all ProxyException subclasses
    - Logs errors with appropriate severity
    - Returns JSON or HTML based on Accept header
    - Provides graceful degradation for analysis failures
    """

    def __init__(self, app: FastAPI, debug: bool = False):
        super().__init__(app)
        self.debug = debug

    async def dispatch(self, request: Request, call_next: Callable):
        try:
            response = await call_next(request)
            return response

        except ProxyException as exc:
            return await self._handle_proxy_error(request, exc)

        except Exception as exc:
            return await self._handle_unexpected_error(request, exc)

    async def _handle_proxy_error(
        self,
        request: Request,
        exc: ProxyException,
    ):
        """Handle known proxy exceptions."""

        # Determine response format
        accept = request.headers.get("accept", "")
        wants_html = "text/html" in accept and "application/json" not in accept

        # Determine status code
        status_code = self._get_status_code(exc)

        # Log appropriately
        self._log_error(exc, status_code)

        if wants_html:
            html = create_error_html(
                title=exc.code.replace("_", " ").title(),
                message=exc.message,
                details=str(exc.details) if self.debug and exc.details else None,
            )
            return HTMLResponse(content=html, status_code=status_code)

        return create_error_response(exc, status_code, request)

    async def _handle_unexpected_error(
        self,
        request: Request,
        exc: Exception,
    ):
        """Handle unexpected exceptions with graceful degradation."""

        # Log full traceback
        logger.error(
            f"Unhandled exception in {request.url.path}: {type(exc).__name__}: {exc}",
            exc_info=True,
        )

        # Check if this is an analysis request - provide fallback response
        if "/match_mydata" in str(request.url.path):
            return await self._create_fallback_analysis_response(request, exc)

        # Generic error response
        accept = request.headers.get("accept", "")
        wants_html = "text/html" in accept

        if wants_html:
            html = create_error_html(
                title="Internal Error",
                message="An unexpected error occurred. Please try again.",
                details=f"{type(exc).__name__}: {exc}" if self.debug else None,
            )
            return HTMLResponse(content=html, status_code=500)

        content = {
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
        }
        if self.debug:
            content["debug"] = {
                "exception": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }

        return JSONResponse(status_code=500, content=content)

    async def _create_fallback_analysis_response(
        self,
        request: Request,
        exc: Exception,
    ):
        """Create a fallback RESEARCH response when analysis fails."""

        fallback_result = {
            "Qualify": "No",
            "Recommendation": "RESEARCH",
            "reasoning": f"Analysis failed due to error: {type(exc).__name__}",
            "error": True,
            "error_type": type(exc).__name__,
        }

        # Check response type preference
        accept = request.headers.get("accept", "")
        query_params = dict(request.query_params)
        response_type = query_params.get("response_type", "html")

        if response_type == "json" or "application/json" in accept:
            return JSONResponse(content=fallback_result)

        html = create_error_html(
            title="Analysis Error",
            message=f"Could not complete analysis: {type(exc).__name__}",
            recommendation="RESEARCH",
        )
        return HTMLResponse(content=html)

    def _get_status_code(self, exc: ProxyException) -> int:
        """Determine HTTP status code for exception."""
        if isinstance(exc, ValidationError):
            return 400
        elif isinstance(exc, BlockedSellerError):
            return 403
        elif isinstance(exc, RateLimitError):
            return 429
        elif isinstance(exc, ConfigurationError):
            return 503
        elif isinstance(exc, ExternalServiceError):
            return 502
        elif isinstance(exc, AnalysisError):
            return 422
        return 500

    def _log_error(self, exc: ProxyException, status_code: int):
        """Log error with appropriate severity."""
        if status_code >= 500:
            logger.error(f"[{exc.code}] {exc.message}", extra={"details": exc.details})
        elif status_code >= 400:
            logger.warning(f"[{exc.code}] {exc.message}", extra={"details": exc.details})
        else:
            logger.info(f"[{exc.code}] {exc.message}")


# ============================================================
# Setup Function
# ============================================================

def setup_error_handlers(app: FastAPI, debug: bool = False):
    """
    Configure error handlers for the FastAPI application.

    Args:
        app: The FastAPI application instance
        debug: If True, include detailed error info in responses
    """

    # Add middleware
    app.add_middleware(ErrorHandlingMiddleware, debug=debug)

    # Register exception handlers for specific exception types
    @app.exception_handler(ProxyException)
    async def proxy_exception_handler(request: Request, exc: ProxyException):
        return await handle_proxy_exception(request, exc)

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        return await handle_generic_exception(request, exc)

    logger.info(f"[ERROR HANDLER] Configured (debug={debug})")
