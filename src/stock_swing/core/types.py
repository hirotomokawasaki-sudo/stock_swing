from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RawEnvelope:
    source: str
    endpoint: str
    fetched_at: datetime
    request_params: dict[str, Any]
    payload: dict[str, Any]


@dataclass
class CanonicalRecord:
    record_id: str
    schema_version: str
    source: str
    source_type: str
    symbol: str | None
    event_type: str
    event_time: datetime
    as_of: str
    ingested_at: datetime
    timezone: str
    payload_version: str | None
    quality_flags: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionRecord:
    decision_id: str
    schema_version: str
    generated_at: datetime
    mode: str
    strategy_id: str
    strategy_version_id: str
    symbol: str
    action: str
    confidence: float
    signal_strength: float
    risk_state: str
    deny_reasons: list[str]
    requires_operator_approval: bool
    time_horizon: str
    evidence: dict[str, Any]
    proposed_order: dict[str, Any] | None
    # F5: AI telemetry
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    context_pack: str | None = None
    prompt_version: str | None = None
    run_id: str | None = None
    experiment_id: str | None = None
    skip_reason: str | None = None
    deny_reason: str | None = None
    block_reason: str | None = None
