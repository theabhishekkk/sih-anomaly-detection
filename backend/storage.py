from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

if __package__:
    from .settings import normalize_database_url
else:
    from settings import normalize_database_url

DEFAULT_DB_PATH = Path(
    os.getenv("SIH_DB_PATH", str(Path(__file__).resolve().parent / "data" / "sih.db"))
)
_CONFIGURED_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DEFAULT_DATABASE_URL = (
    normalize_database_url(_CONFIGURED_DATABASE_URL)
    if _CONFIGURED_DATABASE_URL
    else ""
)
metadata = MetaData()
calibration = Table(
    "calibration",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
screening = Table(
    "screening",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
decisions = Table(
    "decisions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("device_id", String(255), nullable=False, index=True),
    Column("action", String(32), nullable=False),
    Column("inspector", String(255), nullable=False),
    Column("reason", Text, nullable=False),
    Column("evidence", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)
SNAPSHOTS = {"calibration": calibration, "screening": screening}


def _database_url(db_path: str | Path | None) -> str:
    if isinstance(db_path, str) and "://" in db_path:
        return normalize_database_url(db_path)
    if db_path is None and DEFAULT_DATABASE_URL:
        return DEFAULT_DATABASE_URL
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{path.as_posix()}"


@lru_cache(maxsize=16)
def _engine(database_url: str) -> Engine:
    options: dict[str, Any] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        options.update(pool_size=3, max_overflow=2, pool_recycle=1800)
    return create_engine(database_url, **options)


def initialize(db_path: str | Path | None = None) -> None:
    metadata.create_all(_engine(_database_url(db_path)))


def check_database(db_path: str | Path | None = None) -> bool:
    with _engine(_database_url(db_path)).connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1


def _timestamp() -> datetime:
    return datetime.now(timezone.utc)


def save_snapshot(
    db_path: str | Path | None, table_name: str, payload: dict[str, Any]
) -> str:
    table = SNAPSHOTS.get(table_name)
    if table is None:
        raise ValueError("Unsupported snapshot table.")
    created_at = _timestamp()
    serialized = json.dumps(payload, allow_nan=False)
    engine = _engine(_database_url(db_path))
    with engine.begin() as connection:
        insert_statement = (
            postgresql_insert(table)
            if engine.dialect.name == "postgresql"
            else sqlite_insert(table)
        )
        connection.execute(
            insert_statement.values(
                id=1, payload=serialized, created_at=created_at
            )
            .on_conflict_do_update(
                index_elements=[table.c.id],
                set_={"payload": serialized, "created_at": created_at},
            )
        )
    return created_at.isoformat()


def load_snapshot(
    db_path: str | Path | None, table_name: str
) -> dict[str, Any] | None:
    table = SNAPSHOTS.get(table_name)
    if table is None:
        raise ValueError("Unsupported snapshot table.")
    engine = _engine(_database_url(db_path))
    with engine.connect() as connection:
        row = connection.execute(
            select(table.c.payload, table.c.created_at).where(table.c.id == 1)
        ).first()
    if row is None:
        return None
    return {"data": json.loads(row.payload), "created_at": row.created_at.isoformat()}


def save_decision(
    db_path: str | Path | None,
    *,
    device_id: str,
    action: str,
    inspector: str,
    reason: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    created_at = _timestamp()
    engine = _engine(_database_url(db_path))
    with engine.begin() as connection:
        result = connection.execute(
            decisions.insert().values(
                device_id=device_id,
                action=action,
                inspector=inspector,
                reason=reason,
                evidence=json.dumps(evidence, allow_nan=False),
                created_at=created_at,
            )
        )
        decision_id = result.inserted_primary_key[0]
    return {
        "id": decision_id,
        "device_id": device_id,
        "action": action,
        "inspector": inspector,
        "reason": reason,
        "evidence": evidence,
        "created_at": created_at.isoformat(),
    }


def list_decisions(
    db_path: str | Path | None, limit: int = 100
) -> list[dict[str, Any]]:
    engine = _engine(_database_url(db_path))
    with engine.connect() as connection:
        rows = connection.execute(
            select(decisions)
            .order_by(decisions.c.id.desc())
            .limit(limit)
        ).mappings()
        return [
            {
                "id": row["id"],
                "device_id": row["device_id"],
                "action": row["action"],
                "inspector": row["inspector"],
                "reason": row["reason"],
                "evidence": json.loads(row["evidence"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]
