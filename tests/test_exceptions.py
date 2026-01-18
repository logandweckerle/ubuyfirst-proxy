import pytest
from services.exceptions import ProxyException, ValidationError, AnalysisError


def test_proxy_exception_initialization():
    exc = ProxyException("Test Error")
    assert exc.message == "Test Error"
    assert exc.code == "PROXY_ERROR"


def test_analysis_error_initialization():
    exc = AnalysisError("Analysis failed")
    assert exc.message == "Analysis failed"
    assert exc.code == "ANALYSIS_ERROR"


def test_validation_error_initialization():
    exc = ValidationError("Validation failed", field="price")
    assert exc.message == "Validation failed"
    assert exc.details["field"] == "price"


def test_proxy_exception_to_dict():
    exc = ProxyException("Test Error", details={"info": "test detail"})
    result = exc.to_dict()
    assert result == {
        "error": "PROXY_ERROR",
        "message": "Test Error",
        "details": {"info": "test detail"}
    }
