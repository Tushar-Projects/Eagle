"""SQLite database connection and schema management."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Union


def normalize_db_path(db_path: str) -> str:
    """Normalize a database URI or path string to a standard sqlite path."""
    if not db_path:
        return ":memory:"
    
    cleaned = db_path.strip()
    if cleaned.startswith("sqlite:///"):
        cleaned = cleaned[len("sqlite:///"):]
    elif cleaned.startswith("sqlite://"):
        cleaned = cleaned[len("sqlite://"):]

    if cleaned in (":memory:", ""):
        return ":memory:"

    # Ensure parent directory exists for file-based DB
    p = Path(cleaned)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)

    return str(p.resolve()) if not cleaned.startswith(".") else cleaned


class Database:
    """Manages SQLite database connections, schema initialization, and transactions."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = normalize_db_path(db_path)
        self._is_memory = (self.db_path == ":memory:")
        self._memory_conn: sqlite3.Connection | None = None

        if self._is_memory:
            # Persistent memory connection for the lifetime of this instance
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row
            self._memory_conn.execute("PRAGMA foreign_keys = ON")

        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Create or return an active connection."""
        if self._is_memory and self._memory_conn is not None:
            return self._memory_conn

        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager providing an atomic transaction with automatic commit/rollback."""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if not self._is_memory:
                conn.close()

    def init_db(self) -> None:
        """Create database tables and indexes if they do not already exist."""
        conn = self.get_connection()
        try:
            with conn:
                conn.executescript(
                    """
                    PRAGMA foreign_keys = ON;

                    CREATE TABLE IF NOT EXISTS runs (
                        run_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        completed_at TEXT,
                        total_records INTEGER DEFAULT 0,
                        source_count INTEGER DEFAULT 0,
                        target_count INTEGER DEFAULT 0,
                        matched_count INTEGER DEFAULT 0,
                        exception_count INTEGER DEFAULT 0,
                        missing_count INTEGER DEFAULT 0,
                        unresolved_count INTEGER DEFAULT 0,
                        ai_provider TEXT DEFAULT '',
                        error_message TEXT
                    );

                    CREATE TABLE IF NOT EXISTS records (
                        run_id TEXT NOT NULL,
                        record_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        amount TEXT NOT NULL,
                        currency TEXT NOT NULL,
                        transaction_date TEXT NOT NULL,
                        settlement_date TEXT NOT NULL,
                        counterparty TEXT DEFAULT '',
                        source_reference TEXT DEFAULT '',
                        status TEXT DEFAULT 'COMPLETED',
                        transaction_type TEXT DEFAULT 'PAYMENT',
                        gross_amount TEXT,
                        fee_amount TEXT,
                        net_amount TEXT,
                        raw_payload TEXT,
                        PRIMARY KEY (run_id, record_id),
                        FOREIGN KEY (run_id) REFERENCES runs (run_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS reconciliation_results (
                        run_id TEXT NOT NULL,
                        relationship_id TEXT NOT NULL,
                        relationship_type TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        exception_type TEXT,
                        severity TEXT,
                        flag_for_review INTEGER DEFAULT 0,
                        reconciled_amount TEXT,
                        source_record_ids TEXT NOT NULL,
                        target_record_ids TEXT NOT NULL,
                        provenance TEXT DEFAULT 'DETERMINISTIC',
                        PRIMARY KEY (run_id, relationship_id),
                        FOREIGN KEY (run_id) REFERENCES runs (run_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS candidate_decisions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        anchor_record_id TEXT NOT NULL,
                        candidate_options TEXT NOT NULL,
                        selected_candidate_index INTEGER,
                        ai_outcome TEXT,
                        ai_exception_type TEXT,
                        confidence REAL,
                        reasoning TEXT,
                        validation_status TEXT NOT NULL,
                        rejection_reason TEXT,
                        FOREIGN KEY (run_id) REFERENCES runs (run_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        details TEXT,
                        FOREIGN KEY (run_id) REFERENCES runs (run_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS operator_corrections (
                        correction_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        relationship_id TEXT NOT NULL,
                        original_outcome TEXT NOT NULL,
                        original_exception_type TEXT,
                        original_source_ids TEXT NOT NULL,
                        original_target_ids TEXT NOT NULL,
                        corrected_outcome TEXT NOT NULL,
                        corrected_exception_type TEXT,
                        corrected_source_ids TEXT NOT NULL,
                        corrected_target_ids TEXT NOT NULL,
                        operator_reason TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        generated_rule_id TEXT,
                        FOREIGN KEY (run_id) REFERENCES runs (run_id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_records_run ON records (run_id);
                    CREATE INDEX IF NOT EXISTS idx_records_lookup ON records (run_id, record_id);
                    CREATE INDEX IF NOT EXISTS idx_results_run ON reconciliation_results (run_id);
                    CREATE INDEX IF NOT EXISTS idx_candidates_run ON candidate_decisions (run_id);
                    CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_logs (run_id);
                    CREATE INDEX IF NOT EXISTS idx_corrections_run ON operator_corrections (run_id);
                    CREATE INDEX IF NOT EXISTS idx_corrections_rel ON operator_corrections (run_id, relationship_id);

                    CREATE TABLE IF NOT EXISTS reconciliation_rules (
                        rule_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL,
                        source_counterparty_pattern TEXT,
                        reference_prefix TEXT,
                        currency TEXT,
                        max_amount_difference TEXT,
                        max_settlement_delay_days INTEGER,
                        target_action TEXT NOT NULL,
                        resulting_outcome TEXT NOT NULL,
                        resulting_exception_type TEXT,
                        confidence REAL DEFAULT 1.0,
                        is_active INTEGER DEFAULT 1,
                        created_at TEXT NOT NULL,
                        source_correction_id TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_rules_active ON reconciliation_rules (is_active);
                    CREATE INDEX IF NOT EXISTS idx_rules_counterparty ON reconciliation_rules (source_counterparty_pattern);
                    """
                )
        finally:
            if not self._is_memory:
                conn.close()

    def close(self) -> None:
        """Close persistent in-memory connection if active."""
        if self._is_memory and self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None
