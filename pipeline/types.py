from dataclasses import dataclass, field
from typing import Any


@dataclass
class Record:
    id: str
    source: str
    timestamp: str
    attributes: dict[str, Any]


@dataclass
class AttributeValue:
    value: Any
    source_record_id: str
    source: str
    timestamp: str


@dataclass
class ResolvedAttribute:
    values: list[AttributeValue]
    picked: AttributeValue | None
    conflict: bool


@dataclass
class Cluster:
    cluster_id: str
    member_record_ids: list[str]
    records: list[Record]
    attributes: dict[str, ResolvedAttribute]
    confidence: float
    match_reasons: list[str] = field(default_factory=list)
    status: str = "singleton"
    review_reason: str | None = None
