"""Responsabilidade: implementa o modulo app/models/database.py."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base SQLAlchemy para modelos locais."""


class SyncCheckpointModel(Base):
    __tablename__ = "sync_checkpoint"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)


class SyncRunLogModel(Base):
    __tablename__ = "sync_run_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    direction: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[str] = mapped_column(String(64), nullable=False)
    finished_at: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    processed_counts: Mapped[str] = mapped_column(Text, nullable=False)
    warnings: Mapped[str] = mapped_column(Text, nullable=False)
    extra: Mapped[str] = mapped_column(Text, nullable=False)


class SyncLogModel(Base):
    __tablename__ = "sync_log"

    sync_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    course_id: Mapped[int] = mapped_column(Integer, nullable=False)
    records_processed: Mapped[int] = mapped_column(Integer, nullable=False)
    records_created: Mapped[int] = mapped_column(Integer, nullable=False)
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False)
    records_failed: Mapped[int] = mapped_column(Integer, nullable=False)
    errors: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class ErrorLogModel(Base):
    __tablename__ = "error_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    client_ip: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)


def build_engine(db_path: str):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", future=True)


class SyncStateStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_checkpoint (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """,
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_run_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    direction TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    status TEXT NOT NULL,
                    processed_counts TEXT NOT NULL,
                    warnings TEXT NOT NULL,
                    extra TEXT NOT NULL
                )
                """,
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_log (
                    sync_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entity TEXT NOT NULL,
                    course_id INTEGER NOT NULL,
                    records_processed INTEGER NOT NULL,
                    records_created INTEGER NOT NULL,
                    records_updated INTEGER NOT NULL,
                    records_failed INTEGER NOT NULL,
                    errors TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    status TEXT NOT NULL
                )
                """,
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS error_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    client_ip TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    error_code TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT NOT NULL
                )
                """,
            )
            conn.commit()

    def get_datetime(self, key: str) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM sync_checkpoint WHERE key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        return datetime.fromisoformat(row[0])

    def set_datetime(self, key: str, value: datetime | None = None) -> datetime:
        now = value or datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_checkpoint (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, now.isoformat(), datetime.now(UTC).isoformat()),
            )
            conn.commit()
        return now

    def add_sync_log(
        self,
        direction: str,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        processed_counts: dict[str, Any],
        warnings: list[str],
        extra: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_run_log (
                    direction,
                    started_at,
                    finished_at,
                    duration_seconds,
                    status,
                    processed_counts,
                    warnings,
                    extra
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    direction,
                    started_at.isoformat(),
                    finished_at.isoformat(),
                    (finished_at - started_at).total_seconds(),
                    status,
                    json.dumps(processed_counts, ensure_ascii=False),
                    json.dumps(warnings, ensure_ascii=False),
                    json.dumps(extra, ensure_ascii=False),
                ),
            )
            conn.commit()

    def recent_sync_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, direction, started_at, finished_at, duration_seconds,
                       status, processed_counts, warnings, extra
                FROM sync_run_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        logs = []
        for row in rows:
            logs.append(
                {
                    "id": row[0],
                    "direction": row[1],
                    "started_at": row[2],
                    "finished_at": row[3],
                    "duration_seconds": row[4],
                    "status": row[5],
                    "processed_counts": json.loads(row[6]),
                    "warnings": json.loads(row[7]),
                    "extra": json.loads(row[8]),
                },
            )
        return logs

    def add_entity_sync_log(self, entry: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sync_log (
                    sync_id,
                    timestamp,
                    direction,
                    entity,
                    course_id,
                    records_processed,
                    records_created,
                    records_updated,
                    records_failed,
                    errors,
                    duration_seconds,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["sync_id"],
                    entry["timestamp"],
                    entry["direction"],
                    entry["entity"],
                    int(entry["course_id"]),
                    int(entry["records_processed"]),
                    int(entry["records_created"]),
                    int(entry["records_updated"]),
                    int(entry["records_failed"]),
                    json.dumps(entry.get("errors", []), ensure_ascii=False),
                    float(entry["duration_seconds"]),
                    entry["status"],
                ),
            )
            conn.commit()

    def list_entity_sync_logs(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT sync_id, timestamp, direction, entity, course_id,
                   records_processed, records_created, records_updated,
                   records_failed, errors, duration_seconds, status
            FROM sync_log
            WHERE 1 = 1
        """
        params: list[Any] = []
        if date_from:
            query += " AND timestamp >= ?"
            params.append(date_from)
        if date_to:
            query += " AND timestamp <= ?"
            params.append(date_to)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        result = []
        for row in rows:
            result.append(
                {
                    "sync_id": row[0],
                    "timestamp": row[1],
                    "direction": row[2],
                    "entity": row[3],
                    "course_id": row[4],
                    "records_processed": row[5],
                    "records_created": row[6],
                    "records_updated": row[7],
                    "records_failed": row[8],
                    "errors": json.loads(row[9]),
                    "duration_seconds": row[10],
                    "status": row[11],
                },
            )
        return result

    def get_entity_sync_log(self, sync_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT sync_id, timestamp, direction, entity, course_id,
                       records_processed, records_created, records_updated,
                       records_failed, errors, duration_seconds, status
                FROM sync_log
                WHERE sync_id = ?
                """,
                (sync_id,),
            ).fetchone()

        if not row:
            return None
        return {
            "sync_id": row[0],
            "timestamp": row[1],
            "direction": row[2],
            "entity": row[3],
            "course_id": row[4],
            "records_processed": row[5],
            "records_created": row[6],
            "records_updated": row[7],
            "records_failed": row[8],
            "errors": json.loads(row[9]),
            "duration_seconds": row[10],
            "status": row[11],
        }

    def add_error_log(self, entry: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO error_log (
                    timestamp,
                    request_id,
                    method,
                    path,
                    client_ip,
                    status_code,
                    error_code,
                    message,
                    details
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(entry["timestamp"]),
                    str(entry["request_id"]),
                    str(entry["method"]),
                    str(entry["path"]),
                    str(entry["client_ip"]),
                    int(entry["status_code"]),
                    str(entry["error_code"]),
                    str(entry["message"]),
                    json.dumps(entry.get("details", {}), ensure_ascii=False),
                ),
            )
            conn.commit()

