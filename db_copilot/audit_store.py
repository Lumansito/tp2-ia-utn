"""
Auditoria y cola de aprobacion humana (HITL) persistentes en SQLite.

La version anterior guardaba esto en diccionarios de Python en memoria: se
perdia al reiniciar Streamlit y se compartia entre todas las sesiones de
todos los usuarios de la app (dos pestanas del navegador se pisaban entre
si). Este modulo lo persiste en un archivo local (`data/audit.sqlite`) y
separa los registros por `thread_id` (una sesion de Streamlit o de notebook).
"""

import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from db_copilot.config import AUDIT_DB_PATH

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(AUDIT_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                thread_id TEXT,
                action_id TEXT,
                sql TEXT,
                classification TEXT,
                status TEXT,
                rows INTEGER,
                warning TEXT,
                operator TEXT,
                error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_writes (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                sql TEXT,
                classification TEXT,
                warning TEXT,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TEXT,
                resolved_at TEXT,
                operator TEXT
            )
            """
        )
        conn.commit()


_init_db()


def log_event(
    thread_id: Optional[str] = None,
    action_id: Optional[str] = None,
    sql: Optional[str] = None,
    classification: Optional[str] = None,
    status: Optional[str] = None,
    rows: Optional[int] = None,
    warning: Optional[str] = None,
    operator: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_log
                (timestamp, thread_id, action_id, sql, classification, status, rows, warning, operator, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (datetime.now().isoformat(), thread_id, action_id, sql, classification, status, rows, warning, operator, error),
        )
        conn.commit()


def get_audit_log(thread_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        if thread_id:
            cur = conn.execute(
                "SELECT * FROM audit_log WHERE thread_id = ? ORDER BY id DESC LIMIT ?",
                (thread_id, limit),
            )
        else:
            cur = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in cur.fetchall()]


def add_pending_write(
    action_id: str,
    thread_id: str,
    sql: str,
    classification: str = "WRITE",
    warning: Optional[str] = None,
) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO pending_writes (id, thread_id, sql, classification, warning, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
            """,
            (action_id, thread_id, sql, classification, warning, datetime.now().isoformat()),
        )
        conn.commit()


def get_pending_write(action_id: str) -> Optional[Dict[str, Any]]:
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT * FROM pending_writes WHERE id = ?", (action_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_pending_writes(thread_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        if thread_id:
            cur = conn.execute(
                "SELECT * FROM pending_writes WHERE status = 'PENDING' AND thread_id = ? ORDER BY created_at",
                (thread_id,),
            )
        else:
            cur = conn.execute("SELECT * FROM pending_writes WHERE status = 'PENDING' ORDER BY created_at")
        return [dict(row) for row in cur.fetchall()]


def resolve_pending_write(action_id: str, status: str, operator: Optional[str] = None) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE pending_writes SET status = ?, resolved_at = ?, operator = ? WHERE id = ?",
            (status, datetime.now().isoformat(), operator, action_id),
        )
        conn.commit()
