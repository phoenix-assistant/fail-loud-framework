"""Exceptions for fail-loud-framework."""

from __future__ import annotations


class FailLoudError(Exception):
    """Base exception for all fail-loud errors."""
    pass


class ValidationError(FailLoudError):
    """Output failed schema validation."""
    def __init__(self, message: str, output=None, errors=None):
        super().__init__(message)
        self.output = output
        self.validation_errors = errors


class LowConfidenceError(FailLoudError):
    """Confidence below threshold."""
    def __init__(self, message: str, confidence: float, threshold: float):
        super().__init__(message)
        self.confidence = confidence
        self.threshold = threshold


class CircuitOpenError(FailLoudError):
    """Circuit breaker is open — calls are blocked."""
    def __init__(self, message: str, failures: int, timeout: float):
        super().__init__(message)
        self.failures = failures
        self.timeout = timeout
