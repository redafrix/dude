from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    request_text TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    approval_class TEXT NOT NULL,
                    status TEXT NOT NULL,
                    route_reason TEXT NOT NULL,
                    preferred_backend TEXT NOT NULL DEFAULT 'auto',
                    working_dir TEXT NOT NULL DEFAULT '.',
                    auto_approve INTEGER NOT NULL,
                    requires_approval INTEGER NOT NULL,
                    output_text TEXT,
                    error_text TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS actions (
                    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    executor TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    exit_code INTEGER,
                    stdout_text TEXT,
                    stderr_text TEXT,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
                )
                """
            )
            self._ensure_task_column(conn, "preferred_backend", "TEXT NOT NULL DEFAULT 'auto'")
            self._ensure_task_column(conn, "working_dir", "TEXT NOT NULL DEFAULT '.'")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_entries (
                    memory_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_task_id TEXT,
                    kind TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(source_task_id) REFERENCES tasks(task_id)
                )
                """
            )

    def _ensure_task_column(
        self,
        conn: sqlite3.Connection,
        column_name: str,
        column_sql: str,
    ) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if column_name not in existing:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {column_name} {column_sql}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_task(
        self,
        *,
        task_id: str,
        request_text: str,
        backend: str,
        approval_class: str,
        status: str,
        route_reason: str,
        preferred_backend: str,
        working_dir: str,
        auto_approve: bool,
        requires_approval: bool,
    ) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, created_at, updated_at, request_text, backend,
                    approval_class, status, route_reason, preferred_backend,
                    working_dir, auto_approve,
                    requires_approval, output_text, error_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    task_id,
                    now,
                    now,
                    request_text,
                    backend,
                    approval_class,
                    status,
                    route_reason,
                    preferred_backend,
                    working_dir,
                    int(auto_approve),
                    int(requires_approval),
                ),
            )

    def update_task(
        self,
        *,
        task_id: str,
        status: str,
        output_text: str | None = None,
        error_text: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET updated_at = ?, status = ?, output_text = ?, error_text = ?
                WHERE task_id = ?
                """,
                (_utc_now(), status, output_text, error_text, task_id),
            )

    def mark_task_approved(self, task_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET updated_at = ?, status = ?, auto_approve = 1
                WHERE task_id = ?
                """,
                (_utc_now(), "running", task_id),
            )

    def record_action(
        self,
        *,
        task_id: str,
        executor: str,
        command: list[str],
        exit_code: int | None,
        stdout_text: str,
        stderr_text: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO actions (
                    task_id, created_at, executor, command_json,
                    exit_code, stdout_text, stderr_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    _utc_now(),
                    executor,
                    json.dumps(command),
                    exit_code,
                    stdout_text,
                    stderr_text,
                ),
            )

    def create_memory_entry(
        self,
        *,
        kind: str,
        summary_text: str,
        detail: dict[str, Any],
        source_task_id: str | None = None,
        pinned: bool = False,
        memory_id: str | None = None,
    ) -> str:
        entry_id = memory_id or uuid4().hex
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_entries (
                    memory_id, created_at, updated_at, source_task_id,
                    kind, summary_text, detail_json, pinned
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    now,
                    now,
                    source_task_id,
                    kind,
                    summary_text,
                    json.dumps(detail),
                    int(pinned),
                ),
            )
        return entry_id

    def list_memory(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM memory_entries
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._row_to_memory(row) for row in rows]

    def delete_memory(self, memory_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM memory_entries WHERE memory_id = ?",
                (memory_id,),
            )
            return cursor.rowcount > 0

    def clear_memory(self, *, include_pinned: bool = False) -> int:
        with self._connect() as conn:
            if include_pinned:
                cursor = conn.execute("DELETE FROM memory_entries")
            else:
                cursor = conn.execute("DELETE FROM memory_entries WHERE pinned = 0")
            return cursor.rowcount

    def trim_memory(self, max_entries: int) -> int:
        if max_entries <= 0:
            return 0
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT memory_id
                FROM memory_entries
                WHERE pinned = 0
                ORDER BY updated_at DESC, created_at DESC
                """
            ).fetchall()
            stale = rows[max_entries:]
            deleted = 0
            for row in stale:
                cursor = conn.execute(
                    "DELETE FROM memory_entries WHERE memory_id = ?",
                    (row["memory_id"],),
                )
                deleted += cursor.rowcount
            return deleted

    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            task_rows = conn.execute(
                """
                SELECT *
                FROM tasks
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            results: list[dict[str, Any]] = []
            for row in task_rows:
                actions = conn.execute(
                    """
                    SELECT executor, command_json, exit_code, stdout_text, stderr_text, created_at
                    FROM actions
                    WHERE task_id = ?
                    ORDER BY action_id ASC
                    """,
                    (row["task_id"],),
                ).fetchall()
                results.append(
                    {
                        "task_id": row["task_id"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "request_text": row["request_text"],
                        "backend": row["backend"],
                        "approval_class": row["approval_class"],
                        "status": row["status"],
                        "route_reason": row["route_reason"],
                        "preferred_backend": row["preferred_backend"],
                        "working_dir": row["working_dir"],
                        "auto_approve": bool(row["auto_approve"]),
                        "requires_approval": bool(row["requires_approval"]),
                        "output_text": row["output_text"],
                        "error_text": row["error_text"],
                        "actions": [
                            {
                                "executor": action["executor"],
                                "command": json.loads(action["command_json"]),
                                "exit_code": action["exit_code"],
                                "stdout_text": action["stdout_text"],
                                "stderr_text": action["stderr_text"],
                                "created_at": action["created_at"],
                            }
                            for action in actions
                        ],
                    }
                )
            return results

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return self._row_to_task(row) if row is not None else None

    def get_latest_pending_task(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM tasks
                WHERE status = 'approval_required'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
            return self._row_to_task(row) if row is not None else None

    def _row_to_memory(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "memory_id": row["memory_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "source_task_id": row["source_task_id"],
            "kind": row["kind"],
            "summary_text": row["summary_text"],
            "detail": json.loads(row["detail_json"]),
            "pinned": bool(row["pinned"]),
        }

    def _row_to_task(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "request_text": row["request_text"],
            "backend": row["backend"],
            "approval_class": row["approval_class"],
            "status": row["status"],
            "route_reason": row["route_reason"],
            "preferred_backend": row["preferred_backend"],
            "working_dir": row["working_dir"],
            "auto_approve": bool(row["auto_approve"]),
            "requires_approval": bool(row["requires_approval"]),
            "output_text": row["output_text"],
            "error_text": row["error_text"],
        }
