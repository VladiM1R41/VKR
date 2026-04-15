"""Project-specific exceptions for Layer 1."""


class JarvisError(Exception):
    """Base exception for the project."""


class ConfigurationError(JarvisError):
    """Raised when runtime configuration is invalid."""


class CollectorError(JarvisError):
    """Raised for source-level collector failures."""

