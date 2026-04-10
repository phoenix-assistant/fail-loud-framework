"""Decorators: ValidatedOutput, ConfidenceGate, CircuitBreaker."""

from __future__ import annotations

import functools
import time
import threading
from typing import Any, Callable, Literal, Type

from pydantic import BaseModel, ValidationError as PydanticValidationError

from fail_loud.audit import AuditLog, FailureRecord
from fail_loud.review import HumanReviewQueue, ReviewItem
from fail_loud.exceptions import ValidationError, LowConfidenceError, CircuitOpenError


def _get_agent_name(args) -> str:
    """Extract agent class name from method args."""
    if args and hasattr(args[0], "__class__"):
        return args[0].__class__.__name__
    return "unknown"


def _get_audit_log(args) -> AuditLog | None:
    if args and hasattr(args[0], "_fail_loud_audit"):
        return args[0]._fail_loud_audit
    return None


def _get_review_queue(args) -> HumanReviewQueue | None:
    if args and hasattr(args[0], "_fail_loud_review"):
        return args[0]._fail_loud_review
    return None


class ValidatedOutput:
    """Decorator that validates method return value against a Pydantic schema.

    Args:
        schema: Pydantic BaseModel class to validate against.
        on_fail: "raise" to raise ValidationError, "log" to log and return None.
    """

    def __init__(self, schema: Type[BaseModel], on_fail: Literal["raise", "log"] = "raise"):
        self.schema = schema
        self.on_fail = on_fail

    def __call__(self, fn: Callable) -> Callable:
        schema = self.schema
        on_fail = self.on_fail

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)
            try:
                if isinstance(result, dict):
                    validated = schema.model_validate(result)
                elif isinstance(result, schema):
                    validated = result
                else:
                    validated = schema.model_validate(result)
                return validated
            except PydanticValidationError as e:
                agent = _get_agent_name(args)
                audit = _get_audit_log(args)
                record = FailureRecord(
                    agent=agent, action=fn.__name__,
                    input_data={"args": str(args[1:]), "kwargs": kwargs},
                    output_data=result, error=str(e), error_type="ValidationError",
                )
                if audit:
                    audit.log(record)
                if on_fail == "raise":
                    raise ValidationError(
                        f"Output validation failed for {agent}.{fn.__name__}: {e}",
                        output=result, errors=e.errors(),
                    ) from e
                return None

        return wrapper


class ConfidenceGate:
    """Decorator requiring return value to include a confidence score.

    The wrapped method must return a dict or object with a `confidence` field.

    Args:
        threshold: Minimum confidence (0.0–1.0).
        on_low: "raise" to raise LowConfidenceError, "human_review" to queue for review.
    """

    def __init__(self, threshold: float = 0.85, on_low: Literal["raise", "human_review"] = "raise"):
        self.threshold = threshold
        self.on_low = on_low

    def __call__(self, fn: Callable) -> Callable:
        threshold = self.threshold
        on_low = self.on_low

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)
            confidence = None
            if isinstance(result, dict):
                confidence = result.get("confidence")
            elif hasattr(result, "confidence"):
                confidence = result.confidence

            if confidence is None:
                agent = _get_agent_name(args)
                audit = _get_audit_log(args)
                record = FailureRecord(
                    agent=agent, action=fn.__name__,
                    input_data={"args": str(args[1:]), "kwargs": kwargs},
                    output_data=result,
                    error="No confidence score in output", error_type="MissingConfidence",
                )
                if audit:
                    audit.log(record)
                raise LowConfidenceError(
                    f"No confidence score returned by {agent}.{fn.__name__}",
                    confidence=0.0, threshold=threshold,
                )

            if confidence < threshold:
                agent = _get_agent_name(args)
                audit = _get_audit_log(args)
                record = FailureRecord(
                    agent=agent, action=fn.__name__,
                    input_data={"args": str(args[1:]), "kwargs": kwargs},
                    output_data=result,
                    error=f"Confidence {confidence} < {threshold}",
                    error_type="LowConfidence",
                )
                if audit:
                    audit.log(record)

                if on_low == "human_review":
                    queue = _get_review_queue(args)
                    if queue:
                        queue.submit(ReviewItem(
                            agent=agent, action=fn.__name__,
                            input_data={"args": str(args[1:]), "kwargs": kwargs},
                            output_data=result,
                            reason=f"Confidence {confidence} below threshold {threshold}",
                            confidence=confidence,
                        ))
                    return result

                raise LowConfidenceError(
                    f"Confidence {confidence} below threshold {threshold} for {agent}.{fn.__name__}",
                    confidence=confidence, threshold=threshold,
                )

            return result

        return wrapper


class CircuitBreaker:
    """Decorator implementing circuit breaker pattern.

    Args:
        failure_threshold: Number of consecutive failures before opening.
        timeout: Seconds to wait before half-open retry.
    """

    def __init__(self, failure_threshold: int = 3, timeout: float = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout

    def __call__(self, fn: Callable) -> Callable:
        failure_threshold = self.failure_threshold
        timeout = self.timeout
        lock = threading.Lock()
        state = {"failures": 0, "state": "closed", "last_failure": 0.0}

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with lock:
                if state["state"] == "open":
                    if time.time() - state["last_failure"] > timeout:
                        state["state"] = "half-open"
                    else:
                        agent = _get_agent_name(args)
                        audit = _get_audit_log(args)
                        if audit:
                            audit.log(FailureRecord(
                                agent=agent, action=fn.__name__,
                                input_data={"args": str(args[1:]), "kwargs": kwargs},
                                error="Circuit breaker open", error_type="CircuitOpen",
                            ))
                        raise CircuitOpenError(
                            f"Circuit breaker open for {agent}.{fn.__name__} "
                            f"({state['failures']} failures, timeout {timeout}s)",
                            failures=state["failures"], timeout=timeout,
                        )

            try:
                result = fn(*args, **kwargs)
                with lock:
                    state["failures"] = 0
                    state["state"] = "closed"
                return result
            except Exception as e:
                agent = _get_agent_name(args)
                audit = _get_audit_log(args)
                with lock:
                    state["failures"] += 1
                    state["last_failure"] = time.time()
                    if state["failures"] >= failure_threshold:
                        state["state"] = "open"
                if audit:
                    audit.log(FailureRecord(
                        agent=agent, action=fn.__name__,
                        input_data={"args": str(args[1:]), "kwargs": kwargs},
                        error=str(e), error_type=type(e).__name__,
                    ))
                raise

        wrapper._circuit_state = state
        return wrapper
