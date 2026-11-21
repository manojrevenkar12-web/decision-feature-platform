"""Where minute buckets and hour tiles live: a dict for tests and the simulation, DynamoDB in
production. Both implement the same two calls, and the same tests run against both."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Protocol

from dfp.features.tiles import Bucket

MINUTE, HOUR = "m", "h"


def sort_key(kind: str, index: int) -> str:
    return f"{kind}#{index:010d}"


class BucketStore(Protocol):
    def apply(self, event_id: str, pk: str, minute: int, hour: int, amount_cents: int, declined: bool, merchant: int, now: float) -> bool:
        """Adds one event to its minute bucket and hour tile. Returns False if `event_id` was
        already applied (dedupe), in which case nothing changes. Must be atomic."""
        ...

    def apply_unchecked(self, pk: str, minute: int, hour: int, amount_cents: int, declined: bool, merchant: int) -> None:
        """Adds without dedupe; only the ablation designs use it."""
        ...

    def read(self, pk: str, kind: str, lo: int, hi: int) -> list[Bucket]: ...


class InMemoryBucketStore:
    def __init__(self, idempotency_ttl_s: float = 48 * 3600) -> None:
        self.rows: dict[str, dict[str, dict[int, Bucket]]] = defaultdict(lambda: {MINUTE: {}, HOUR: {}})
        self.seen: dict[str, float] = {}
        self.ttl = idempotency_ttl_s
        self.items_read = 0

    def apply(self, event_id: str, pk: str, minute: int, hour: int, amount_cents: int, declined: bool, merchant: int, now: float) -> bool:
        expires = self.seen.get(event_id)
        if expires is not None and expires > now:
            return False
        self.seen[event_id] = now + self.ttl
        self.apply_unchecked(pk, minute, hour, amount_cents, declined, merchant)
        return True

    def apply_unchecked(self, pk: str, minute: int, hour: int, amount_cents: int, declined: bool, merchant: int) -> None:
        row = self.rows[pk]
        row[MINUTE].setdefault(minute, Bucket()).add(amount_cents, declined, merchant)
        row[HOUR].setdefault(hour, Bucket()).add(amount_cents, declined, merchant)

    def read(self, pk: str, kind: str, lo: int, hi: int) -> list[Bucket]:
        row = self.rows.get(pk)
        if row is None:
            return []
        part = row[kind]
        if hi - lo + 1 <= len(part):
            out = [part[i] for i in range(lo, hi + 1) if i in part]
        else:
            out = [b for i, b in part.items() if lo <= i <= hi]
        self.items_read += len(out)
        return out

    def evict_before(self, minute: int, hour: int) -> None:
        for row in self.rows.values():
            for k in [k for k in row[MINUTE] if k < minute]:
                del row[MINUTE][k]
            for k in [k for k in row[HOUR] if k < hour]:
                del row[HOUR][k]


class DynamoBucketStore:
    """Two tables: `buckets` (pk, sk) and `idempotency` (event_id, expires_at as the TTL attribute).

    `apply` is one TransactWriteItems call: claim the event id (fails if a live claim exists) and add
    to both buckets, so a redelivered batch can never count an event twice and a crash between the
    claim and the update cannot lose one.
    """

    def __init__(self, client: Any, buckets_table: str, idempotency_table: str, idempotency_ttl_s: float = 48 * 3600, retention_s: float = 8 * 86400) -> None:
        self.client = client
        self.buckets = buckets_table
        self.idem = idempotency_table
        self.ttl = idempotency_ttl_s
        self.retention = retention_s

    def _update(self, pk: str, kind: str, index: int, amount_cents: int, declined: bool, merchant: int, expires_at: int) -> dict[str, Any]:
        return {
            "Update": {
                "TableName": self.buckets,
                "Key": {"pk": {"S": pk}, "sk": {"S": sort_key(kind, index)}},
                "UpdateExpression": "ADD n :one, amount_cents :amt, declined :dec, merchants :m SET expires_at = :exp",
                "ExpressionAttributeValues": {
                    ":one": {"N": "1"},
                    ":amt": {"N": str(amount_cents)},
                    ":dec": {"N": str(int(declined))},
                    ":m": {"NS": [str(merchant)]},
                    ":exp": {"N": str(expires_at)},
                },
            }
        }

    def apply(self, event_id: str, pk: str, minute: int, hour: int, amount_cents: int, declined: bool, merchant: int, now: float) -> bool:
        exp = int(minute * 60 + self.retention)
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self.idem,
                            "Item": {"event_id": {"S": event_id}, "expires_at": {"N": str(int(now + self.ttl))}},
                            "ConditionExpression": "attribute_not_exists(event_id) OR expires_at < :now",
                            "ExpressionAttributeValues": {":now": {"N": str(int(now))}},
                        }
                    },
                    self._update(pk, MINUTE, minute, amount_cents, declined, merchant, exp),
                    self._update(pk, HOUR, hour, amount_cents, declined, merchant, exp),
                ]
            )
        except self.client.exceptions.TransactionCanceledException as e:
            reasons = e.response.get("CancellationReasons", [])
            if reasons and reasons[0].get("Code") == "ConditionalCheckFailed":
                return False
            raise
        return True

    def apply_unchecked(self, pk: str, minute: int, hour: int, amount_cents: int, declined: bool, merchant: int) -> None:
        exp = int(minute * 60 + self.retention)
        self.client.transact_write_items(
            TransactItems=[
                self._update(pk, MINUTE, minute, amount_cents, declined, merchant, exp),
                self._update(pk, HOUR, hour, amount_cents, declined, merchant, exp),
            ]
        )

    def read(self, pk: str, kind: str, lo: int, hi: int) -> list[Bucket]:
        out: list[Bucket] = []
        kwargs: dict[str, Any] = {
            "TableName": self.buckets,
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :lo AND :hi",
            "ExpressionAttributeValues": {":pk": {"S": pk}, ":lo": {"S": sort_key(kind, lo)}, ":hi": {"S": sort_key(kind, hi)}},
            "ConsistentRead": True,
        }
        while True:
            page = self.client.query(**kwargs)
            for it in page["Items"]:
                out.append(
                    Bucket(
                        count=int(it["n"]["N"]),
                        amount_cents=int(it["amount_cents"]["N"]),
                        declined=int(it["declined"]["N"]),
                        merchants={int(x) for x in it["merchants"]["NS"]},
                    )
                )
            if "LastEvaluatedKey" not in page:
                return out
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
