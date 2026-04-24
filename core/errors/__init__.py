"""NoMan error hierarchy."""


class NoManError(Exception):
    """Base exception for all NoMan errors."""

    pass


# ── Configuration Errors ──
class ConfigError(NoManError):
    """Invalid or missing configuration."""

    pass


class ProviderConfigError(ConfigError):
    """Model provider configuration is invalid."""

    pass


# ── Security Errors ──
class SecurityError(NoManError):
    """Security policy violation."""

    pass


class SandboxViolation(SecurityError):
    """Attempted operation outside allowed boundaries."""

    pass


class PathTraversalError(SandboxViolation):
    """Resolved path escapes the sandbox root."""

    pass


class NetworkViolation(SandboxViolation):
    """Network request violates sandbox policy."""

    pass


class ToolSignatureError(SecurityError):
    """Tool signature verification failed."""

    pass


class SelfModificationError(SecurityError):
    """Agent attempted unauthorized self-modification."""

    pass


# ── Model / Adapter Errors ──
class ModelError(NoManError):
    """LLM provider or adapter failure."""

    pass


class RateLimitError(ModelError):
    """Rate limit exceeded for provider or internal quota."""

    pass


class ProviderUnavailableError(ModelError):
    """Configured provider is unreachable."""

    pass


class CapabilityError(ModelError):
    """Model lacks a required capability."""

    pass


# ── Tool / Orchestrator Errors ──
class ToolError(NoManError):
    """Tool execution failure."""

    pass


class ToolNotFoundError(ToolError):
    """Requested tool is not registered."""

    pass


class ToolValidationError(ToolError):
    """Tool arguments failed validation."""

    pass


class CircuitBreakerOpenError(ToolError):
    """Circuit breaker is open for this subsystem."""

    pass


# ── Memory Errors ──
class MemoryError(NoManError):
    """Memory subsystem failure."""

    pass


class MemoryCorruptionError(MemoryError):
    """Database corruption detected."""

    pass


# ── Context Errors ──
class ContextError(NoManError):
    """Context management failure."""

    pass


class BudgetExceededError(ContextError):
    """Token budget exceeded for this turn."""


class QuotaExceeded(ContextError):
    """Quota or rate limit exceeded."""

    pass
