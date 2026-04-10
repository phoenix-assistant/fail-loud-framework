# fail-loud-framework

**Middleware that enforces visible, traceable failures over silent fake data in AI agent systems.**

[![PyPI](https://img.shields.io/pypi/v/fail-loud-framework)](https://pypi.org/project/fail-loud-framework/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Philosophy

AI agents fail silently. They hallucinate, return garbage with high confidence, and cascade bad data downstream. **Fail-loud** enforces a simple principle:

> **If an agent isn't sure, it must say so. If output is invalid, it must fail visibly. Every failure must be traceable.**

No silent fallbacks. No fake data. No "best effort" that poisons downstream systems.

## Installation

```bash
pip install fail-loud-framework
```

## Quick Start

```python
from pydantic import BaseModel
from fail_loud import FailLoud, ValidatedOutput, ConfidenceGate, CircuitBreaker

class ResponseSchema(BaseModel):
    answer: str
    score: float

@FailLoud(strict=True)
class MyAgent:
    @ValidatedOutput(schema=ResponseSchema, on_fail="raise")
    def generate(self, prompt: str):
        return {"answer": "The capital is Paris", "score": 0.95}

    @ConfidenceGate(threshold=0.85, on_low="human_review")
    def answer(self, question: str):
        return {"confidence": 0.72, "text": "Maybe Berlin?"}

    @CircuitBreaker(failure_threshold=3, timeout=60)
    def call_api(self, endpoint: str):
        return requests.get(endpoint).json()
```

## Core Components

### `@FailLoud` — Class Decorator

Injects audit log and human-review queue into your agent class.

```python
from fail_loud import FailLoud, AuditLog, HumanReviewQueue

audit = AuditLog("failures.db")       # SQLite-backed
review = HumanReviewQueue("review.db") # SQLite-backed

@FailLoud(strict=True, audit_log=audit, review_queue=review)
class MyAgent:
    ...
```

### `@ValidatedOutput` — Schema Validation Gate

Validates method return values against Pydantic models. Invalid output either raises or logs.

```python
@ValidatedOutput(schema=MySchema, on_fail="raise")  # or on_fail="log"
def generate(self, prompt: str):
    ...
```

### `@ConfidenceGate` — Confidence Threshold

Requires outputs to include a `confidence` field. Low-confidence results either raise or route to human review.

```python
@ConfidenceGate(threshold=0.85, on_low="human_review")  # or on_low="raise"
def answer(self, question: str):
    return {"confidence": 0.72, "text": "unsure"}
```

### `@CircuitBreaker` — Stop Cascading Failures

Opens after N consecutive failures, blocks calls for a timeout period, then allows a half-open retry.

```python
@CircuitBreaker(failure_threshold=3, timeout=60)
def call_api(self, endpoint: str):
    ...
```

## Audit Log

Every failure is logged to SQLite with full context:

```python
from fail_loud import AuditLog

log = AuditLog("failures.db")
failures = log.query(agent="MyAgent", limit=10)
for f in failures:
    print(f"{f.timestamp} | {f.agent}.{f.action} | {f.error_type}: {f.error}")
```

Fields: `id`, `agent`, `action`, `input_data`, `output_data`, `error`, `error_type`, `timestamp`, `metadata`

## Human Review Queue

Low-confidence or ambiguous outputs get queued for human review:

```python
from fail_loud import HumanReviewQueue

queue = HumanReviewQueue("review.db")
for item in queue.pending():
    print(f"{item.agent}.{item.action}: {item.reason} (confidence: {item.confidence})")
    queue.resolve(item.id, "approved", notes="Looks correct")
```

## Exceptions

| Exception | When |
|-----------|------|
| `ValidationError` | Output fails schema validation |
| `LowConfidenceError` | Confidence below threshold |
| `CircuitOpenError` | Circuit breaker is open |

All inherit from `FailLoudError`.

## Development

```bash
git clone https://github.com/phoenix-assistant/fail-loud-framework
cd fail-loud-framework
pip install -e ".[dev]"
pytest
```

## License

MIT
