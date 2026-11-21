"""The transaction event a lender sends to the stream."""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TxnEvent:
    event_id: str
    tenant: str
    entity: str
    event_time: float  # seconds since the epoch, when the transaction happened
    amount_cents: int
    merchant: int
    declined: bool

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TxnEvent:
        return cls(
            event_id=str(d["event_id"]),
            tenant=str(d["tenant"]),
            entity=str(d["entity"]),
            event_time=float(d["event_time"]),
            amount_cents=int(d["amount_cents"]),
            merchant=int(d["merchant"]),
            declined=bool(d["declined"]),
        )

    @classmethod
    def from_kinesis(cls, record: dict[str, Any]) -> TxnEvent:
        return cls.from_dict(json.loads(base64.b64decode(record["kinesis"]["data"])))
