"""Unit tests for the error hierarchy."""

from core.errors import (
    BudgetExceededError,
    CircuitBreakerOpenError,
    ConfigError,
    NoManError,
    PathTraversalError,
    ProviderConfigError,
    RateLimitError,
    SandboxViolation,
    SecurityError,
    SelfModificationError,
    ToolSignatureError,
)


def test_all_errors_inherit_noman():
    errors = [
        ConfigError(),
        ProviderConfigError(),
        SecurityError(),
        SandboxViolation(),
        PathTraversalError("x"),
        RateLimitError("rl"),
        ToolSignatureError("ts"),
        SelfModificationError("sm"),
        BudgetExceededError(),
        CircuitBreakerOpenError("cb"),
    ]
    for exc in errors:
        assert isinstance(exc, NoManError)


def test_error_messages():
    assert str(PathTraversalError("/etc")) == "/etc"
    assert str(RateLimitError("too fast")) == "too fast"
