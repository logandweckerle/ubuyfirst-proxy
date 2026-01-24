"""
Custom Exception Hierarchy for ClaudeProxyV3

This module provides a structured exception hierarchy for better error handling
and categorization throughout the application.

Usage:
    from services.exceptions import (
        ProxyException,
        AnalysisError,
        ExternalServiceError,
        ValidationError,
    )

    try:
        result = analyze_listing(data)
    except AnalysisError as e:
        logger.error(f"Analysis failed: {e}")
        return fallback_response()
"""

from typing import Optional, Dict, Any


class ProxyException(Exception):
    """
    Base exception for all ClaudeProxy errors.

    All custom exceptions should inherit from this class to enable
    unified error handling throughout the application.
    """

    def __init__(
        self,
        message: str,
        code: str = "PROXY_ERROR",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
        self.cause = cause

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        result = {
            "error": self.code,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result

    def __str__(self) -> str:
        if self.cause:
            return f"{self.message} (caused by: {self.cause})"
        return self.message


# ============================================================
# Analysis Errors
# ============================================================

class AnalysisError(ProxyException):
    """Base class for analysis-related errors."""

    def __init__(
        self,
        message: str,
        code: str = "ANALYSIS_ERROR",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message, code, details, cause)


class CategoryDetectionError(AnalysisError):
    """Failed to detect listing category."""

    def __init__(self, title: str, cause: Optional[Exception] = None):
        super().__init__(
            message=f"Could not detect category for listing: {title[:50]}",
            code="CATEGORY_DETECTION_ERROR",
            details={"title": title},
            cause=cause,
        )


class AIResponseError(AnalysisError):
    """AI model returned invalid or empty response."""

    def __init__(
        self,
        model: str,
        reason: str = "empty or invalid response",
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"AI model {model} returned {reason}",
            code="AI_RESPONSE_ERROR",
            details={"model": model, "reason": reason},
            cause=cause,
        )


class TierAnalysisError(AnalysisError):
    """Error during tier-based analysis."""

    def __init__(
        self,
        tier: int,
        model: str,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Tier {tier} analysis failed using {model}",
            code="TIER_ANALYSIS_ERROR",
            details={"tier": tier, "model": model},
            cause=cause,
        )


# ============================================================
# External Service Errors
# ============================================================

class ExternalServiceError(ProxyException):
    """Base class for external service errors."""

    def __init__(
        self,
        service: str,
        message: str,
        code: str = "EXTERNAL_SERVICE_ERROR",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        details["service"] = service
        super().__init__(message, code, details, cause)


class EbayAPIError(ExternalServiceError):
    """Error communicating with eBay API."""

    def __init__(
        self,
        message: str = "eBay API request failed",
        status_code: Optional[int] = None,
        cause: Optional[Exception] = None,
    ):
        details = {}
        if status_code:
            details["status_code"] = status_code
        super().__init__(
            service="ebay",
            message=message,
            code="EBAY_API_ERROR",
            details=details,
            cause=cause,
        )


class AnthropicAPIError(ExternalServiceError):
    """Error communicating with Anthropic API."""

    def __init__(
        self,
        message: str = "Anthropic API request failed",
        model: Optional[str] = None,
        cause: Optional[Exception] = None,
    ):
        details = {}
        if model:
            details["model"] = model
        super().__init__(
            service="anthropic",
            message=message,
            code="ANTHROPIC_API_ERROR",
            details=details,
            cause=cause,
        )


class OpenAIAPIError(ExternalServiceError):
    """Error communicating with OpenAI API."""

    def __init__(
        self,
        message: str = "OpenAI API request failed",
        model: Optional[str] = None,
        cause: Optional[Exception] = None,
    ):
        details = {}
        if model:
            details["model"] = model
        super().__init__(
            service="openai",
            message=message,
            code="OPENAI_API_ERROR",
            details=details,
            cause=cause,
        )


class PriceChartingError(ExternalServiceError):
    """Error with PriceCharting database or API."""

    def __init__(
        self,
        message: str = "PriceCharting lookup failed",
        product: Optional[str] = None,
        cause: Optional[Exception] = None,
    ):
        details = {}
        if product:
            details["product"] = product
        super().__init__(
            service="pricecharting",
            message=message,
            code="PRICECHARTING_ERROR",
            details=details,
            cause=cause,
        )


class DiscordWebhookError(ExternalServiceError):
    """Error sending Discord webhook."""

    def __init__(
        self,
        message: str = "Discord webhook failed",
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            service="discord",
            message=message,
            code="DISCORD_WEBHOOK_ERROR",
            cause=cause,
        )


# ============================================================
# Validation Errors
# ============================================================

class ValidationError(ProxyException):
    """Base class for validation errors."""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        code: str = "VALIDATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if field:
            details["field"] = field
        super().__init__(message, code, details, cause)


class InvalidListingError(ValidationError):
    """Listing data is invalid or incomplete."""

    def __init__(
        self,
        reason: str,
        missing_fields: Optional[list] = None,
    ):
        details = {"reason": reason}
        if missing_fields:
            details["missing_fields"] = missing_fields
        super().__init__(
            message=f"Invalid listing: {reason}",
            code="INVALID_LISTING",
            details=details,
        )


class InvalidPriceError(ValidationError):
    """Price value is invalid."""

    def __init__(self, price_value: Any, reason: str = "not a valid number"):
        super().__init__(
            message=f"Invalid price '{price_value}': {reason}",
            field="price",
            code="INVALID_PRICE",
            details={"value": str(price_value), "reason": reason},
        )


class InvalidWeightError(ValidationError):
    """Weight value is invalid."""

    def __init__(self, weight_value: Any, reason: str = "not a valid weight"):
        super().__init__(
            message=f"Invalid weight '{weight_value}': {reason}",
            field="weight",
            code="INVALID_WEIGHT",
            details={"value": str(weight_value), "reason": reason},
        )


# ============================================================
# Seller Errors
# ============================================================

class SellerError(ProxyException):
    """Base class for seller-related errors."""
    pass


class BlockedSellerError(SellerError):
    """Seller is on the blocked list."""

    def __init__(self, seller_name: str, reason: str = "blocked"):
        super().__init__(
            message=f"Seller '{seller_name}' is {reason}",
            code="BLOCKED_SELLER",
            details={"seller": seller_name, "reason": reason},
        )


class SpamSellerError(SellerError):
    """Seller detected as spam."""

    def __init__(self, seller_name: str, listing_count: int, window_seconds: int):
        super().__init__(
            message=f"Seller '{seller_name}' flagged as spam: {listing_count} listings in {window_seconds}s",
            code="SPAM_SELLER",
            details={
                "seller": seller_name,
                "listing_count": listing_count,
                "window_seconds": window_seconds,
            },
        )


# ============================================================
# Cache Errors
# ============================================================

class CacheError(ProxyException):
    """Base class for cache-related errors."""

    def __init__(
        self,
        message: str,
        code: str = "CACHE_ERROR",
        cause: Optional[Exception] = None,
    ):
        super().__init__(message, code, cause=cause)


class CacheMissError(CacheError):
    """Cache lookup returned no result."""

    def __init__(self, key: str):
        super().__init__(
            message=f"Cache miss for key: {key}",
            code="CACHE_MISS",
        )


# ============================================================
# Rate Limiting Errors
# ============================================================

class RateLimitError(ProxyException):
    """Rate limit exceeded."""

    def __init__(
        self,
        service: str,
        retry_after: Optional[int] = None,
    ):
        details = {"service": service}
        if retry_after:
            details["retry_after_seconds"] = retry_after
        super().__init__(
            message=f"Rate limit exceeded for {service}",
            code="RATE_LIMIT_EXCEEDED",
            details=details,
        )


class BudgetExceededError(RateLimitError):
    """API budget exceeded."""

    def __init__(
        self,
        service: str,
        current_spend: float,
        budget_limit: float,
    ):
        super().__init__(service=service)
        self.code = "BUDGET_EXCEEDED"
        self.message = f"{service} budget exceeded: ${current_spend:.2f} / ${budget_limit:.2f}"
        self.details = {
            "service": service,
            "current_spend": current_spend,
            "budget_limit": budget_limit,
        }


# ============================================================
# Configuration Errors
# ============================================================

class ConfigurationError(ProxyException):
    """Configuration is invalid or missing."""

    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
    ):
        details = {}
        if config_key:
            details["config_key"] = config_key
        super().__init__(
            message=message,
            code="CONFIGURATION_ERROR",
            details=details,
        )


class MissingAPIKeyError(ConfigurationError):
    """Required API key is missing."""

    def __init__(self, service: str):
        super().__init__(
            message=f"Missing API key for {service}",
            config_key=f"{service.upper()}_API_KEY",
        )
        self.code = "MISSING_API_KEY"
