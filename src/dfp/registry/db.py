"""The feature registry on Aurora PostgreSQL: tenants, API keys and versioned feature definitions.

Definitions are immutable: registering a changed spec creates a new version, so a decision logged
yesterday can always be traced to the exact window and aggregation it used. SQLAlchemy Core keeps the
same code running on SQLite in unit tests and on PostgreSQL in CI and production.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    insert,
    select,
)

metadata = MetaData()

tenants = Table(
    "tenants",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(200), nullable=False),
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("key_hash", String(64), primary_key=True),
    Column("tenant_id", String(64), ForeignKey("tenants.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

feature_definitions = Table(
    "feature_definitions",
    metadata,
    Column("name", String(100), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("kind", String(20), nullable=False),
    Column("spec", Text, nullable=False),
    Column("spec_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("name", "spec_hash", name="uq_feature_spec"),
)


def migrate(engine: Engine) -> None:
    metadata.create_all(engine)


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def add_tenant(engine: Engine, tenant_id: str, name: str, api_key: str) -> None:
    with engine.begin() as c:
        c.execute(insert(tenants).values(id=tenant_id, name=name))
        c.execute(insert(api_keys).values(key_hash=hash_key(api_key), tenant_id=tenant_id, created_at=datetime.now(UTC)))


def tenant_for_key(engine: Engine, api_key: str) -> str | None:
    """The tenant comes from the key, never from the request body."""
    with engine.connect() as c:
        row = c.execute(select(api_keys.c.tenant_id).where(api_keys.c.key_hash == hash_key(api_key))).first()
    return None if row is None else str(row[0])


def register(engine: Engine, name: str, kind: str, spec: dict[str, Any]) -> int:
    """Returns the version for this spec, creating a new one only if the spec changed."""
    body = json.dumps(spec, sort_keys=True)
    digest = hashlib.sha256(body.encode()).hexdigest()
    with engine.begin() as c:
        existing = c.execute(select(feature_definitions.c.version).where(feature_definitions.c.name == name, feature_definitions.c.spec_hash == digest)).first()
        if existing is not None:
            return int(existing[0])
        latest = c.execute(select(func.max(feature_definitions.c.version)).where(feature_definitions.c.name == name)).scalar()
        version = int(latest or 0) + 1
        c.execute(insert(feature_definitions).values(name=name, version=version, kind=kind, spec=body, spec_hash=digest, created_at=datetime.now(UTC)))
    return version


def active(engine: Engine) -> dict[str, tuple[int, str, dict[str, Any]]]:
    """Latest version of every feature: name -> (version, kind, spec)."""
    with engine.connect() as c:
        rows = c.execute(
            select(feature_definitions.c.name, feature_definitions.c.version, feature_definitions.c.kind, feature_definitions.c.spec).order_by(
                feature_definitions.c.name, feature_definitions.c.version
            )
        ).all()
    out: dict[str, tuple[int, str, dict[str, Any]]] = {}
    for name, version, kind, spec in rows:
        out[name] = (int(version), str(kind), json.loads(spec))
    return out
