"""Tests for fail-loud-framework."""

import time
import pytest
from pydantic import BaseModel

from fail_loud import (
    FailLoud, ValidatedOutput, ConfidenceGate, CircuitBreaker,
    AuditLog, HumanReviewQueue, FailureRecord, ReviewItem,
)
from fail_loud.exceptions import ValidationError, LowConfidenceError, CircuitOpenError


# --- Schemas ---

class OutputSchema(BaseModel):
    answer: str
    score: float


# --- Test ValidatedOutput ---

class TestValidatedOutput:
    def test_valid_dict(self):
        @FailLoud()
        class Agent:
            @ValidatedOutput(schema=OutputSchema)
            def generate(self):
                return {"answer": "hello", "score": 0.9}
        a = Agent()
        result = a.generate()
        assert isinstance(result, OutputSchema)
        assert result.answer == "hello"

    def test_invalid_dict_raises(self):
        @FailLoud()
        class Agent:
            @ValidatedOutput(schema=OutputSchema, on_fail="raise")
            def generate(self):
                return {"wrong": "data"}
        a = Agent()
        with pytest.raises(ValidationError):
            a.generate()

    def test_invalid_dict_log_returns_none(self):
        @FailLoud()
        class Agent:
            @ValidatedOutput(schema=OutputSchema, on_fail="log")
            def generate(self):
                return {"wrong": "data"}
        a = Agent()
        assert a.generate() is None

    def test_logs_failure_to_audit(self):
        audit = AuditLog()
        @FailLoud(audit_log=audit)
        class Agent:
            @ValidatedOutput(schema=OutputSchema, on_fail="raise")
            def generate(self):
                return {"bad": True}
        a = Agent()
        with pytest.raises(ValidationError):
            a.generate()
        assert audit.count() == 1
        record = audit.query()[0]
        assert record.agent == "Agent"
        assert record.error_type == "ValidationError"


# --- Test ConfidenceGate ---

class TestConfidenceGate:
    def test_high_confidence_passes(self):
        @FailLoud()
        class Agent:
            @ConfidenceGate(threshold=0.8)
            def answer(self):
                return {"confidence": 0.95, "text": "sure"}
        a = Agent()
        result = a.answer()
        assert result["confidence"] == 0.95

    def test_low_confidence_raises(self):
        @FailLoud()
        class Agent:
            @ConfidenceGate(threshold=0.8, on_low="raise")
            def answer(self):
                return {"confidence": 0.5, "text": "maybe"}
        a = Agent()
        with pytest.raises(LowConfidenceError) as exc_info:
            a.answer()
        assert exc_info.value.confidence == 0.5
        assert exc_info.value.threshold == 0.8

    def test_missing_confidence_raises(self):
        @FailLoud()
        class Agent:
            @ConfidenceGate(threshold=0.8)
            def answer(self):
                return {"text": "no confidence"}
        a = Agent()
        with pytest.raises(LowConfidenceError):
            a.answer()

    def test_low_confidence_human_review(self):
        review = HumanReviewQueue()
        @FailLoud(review_queue=review)
        class Agent:
            @ConfidenceGate(threshold=0.9, on_low="human_review")
            def answer(self):
                return {"confidence": 0.7, "text": "unsure"}
        a = Agent()
        result = a.answer()
        assert result["confidence"] == 0.7
        assert review.count_pending() == 1


# --- Test CircuitBreaker ---

class TestCircuitBreaker:
    def test_success_resets(self):
        @FailLoud()
        class Agent:
            @CircuitBreaker(failure_threshold=2, timeout=1)
            def call_api(self):
                return "ok"
        a = Agent()
        assert a.call_api() == "ok"

    def test_opens_after_threshold(self):
        call_count = {"n": 0}
        @FailLoud()
        class Agent:
            @CircuitBreaker(failure_threshold=2, timeout=60)
            def call_api(self):
                call_count["n"] += 1
                raise ConnectionError("fail")
        a = Agent()
        with pytest.raises(ConnectionError):
            a.call_api()
        with pytest.raises(ConnectionError):
            a.call_api()
        # Circuit now open
        with pytest.raises(CircuitOpenError):
            a.call_api()
        assert call_count["n"] == 2  # Third call blocked by circuit

    def test_half_open_after_timeout(self):
        attempts = {"n": 0}
        @FailLoud()
        class Agent:
            @CircuitBreaker(failure_threshold=1, timeout=0.1)
            def call_api(self):
                attempts["n"] += 1
                if attempts["n"] <= 1:
                    raise ConnectionError("fail")
                return "recovered"
        a = Agent()
        with pytest.raises(ConnectionError):
            a.call_api()
        # Circuit open, wait for timeout
        time.sleep(0.15)
        assert a.call_api() == "recovered"


# --- Test AuditLog ---

class TestAuditLog:
    def test_log_and_query(self):
        log = AuditLog()
        r = FailureRecord(agent="TestAgent", action="do_thing", input_data={"x": 1}, error="boom")
        rid = log.log(r)
        assert log.count() == 1
        fetched = log.get(rid)
        assert fetched.agent == "TestAgent"
        assert fetched.error == "boom"

    def test_query_filter(self):
        log = AuditLog()
        log.log(FailureRecord(agent="A", action="x", input_data={}))
        log.log(FailureRecord(agent="B", action="y", input_data={}))
        assert len(log.query(agent="A")) == 1


# --- Test HumanReviewQueue ---

class TestHumanReviewQueue:
    def test_submit_and_resolve(self):
        q = HumanReviewQueue()
        item = ReviewItem(agent="A", action="check", input_data="q", output_data="a", reason="low conf")
        q.submit(item)
        assert q.count_pending() == 1
        q.resolve(item.id, "approved", "looks good")
        assert q.count_pending() == 0
        resolved = q.get(item.id)
        assert resolved.status == "approved"

    def test_reject(self):
        q = HumanReviewQueue()
        item = ReviewItem(agent="B", action="gen", input_data="i", output_data="o", reason="bad")
        q.submit(item)
        q.resolve(item.id, "rejected", "nope")
        assert q.get(item.id).status == "rejected"


# --- Test FailLoud class decorator ---

class TestFailLoudDecorator:
    def test_injects_audit_and_review(self):
        @FailLoud(strict=True)
        class Agent:
            pass
        a = Agent()
        assert hasattr(a, "_fail_loud_audit")
        assert hasattr(a, "_fail_loud_review")
        assert a._fail_loud_strict is True
