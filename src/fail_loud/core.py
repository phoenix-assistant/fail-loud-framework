"""FailLoud class decorator — wraps an agent class with fail-loud infrastructure."""

from __future__ import annotations

from fail_loud.audit import AuditLog
from fail_loud.review import HumanReviewQueue


class FailLoud:
    """Class decorator that injects audit log and review queue into an agent.

    Args:
        strict: If True, unhandled exceptions in decorated methods are always logged.
        audit_log: Optional AuditLog instance (defaults to in-memory).
        review_queue: Optional HumanReviewQueue instance (defaults to in-memory).
    """

    def __init__(
        self,
        strict: bool = False,
        audit_log: AuditLog | None = None,
        review_queue: HumanReviewQueue | None = None,
    ):
        self.strict = strict
        self.audit_log = audit_log or AuditLog()
        self.review_queue = review_queue or HumanReviewQueue()

    def __call__(self, cls):
        audit_log = self.audit_log
        review_queue = self.review_queue
        strict = self.strict

        original_init = cls.__init__ if hasattr(cls, "__init__") else None

        def new_init(self_inner, *args, **kwargs):
            self_inner._fail_loud_audit = audit_log
            self_inner._fail_loud_review = review_queue
            self_inner._fail_loud_strict = strict
            if original_init and original_init is not object.__init__:
                original_init(self_inner, *args, **kwargs)

        cls.__init__ = new_init
        cls._fail_loud_audit = audit_log
        cls._fail_loud_review = review_queue
        return cls
