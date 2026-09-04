"""Repository for persisting and querying reconciliation data."""

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import (
    ExceptionType,
    ReconciliationOutcome,
    RelationshipType,
    Severity,
)
from eagle.models.reconciliation import ReconciliationResult
from eagle.rules.models import OperatorCorrection, ReconciliationRule
from eagle.storage.database import Database


class Repository:
    """Data access layer for runs, records, results, candidates, and audit events."""

    def __init__(self, db: Database):
        self.db = db

    # -------------------------------------------------------------------------
    # Runs
    # -------------------------------------------------------------------------

    def create_run(
        self,
        run_id: str,
        status: str = "CREATED",
        ai_provider: str = "",
        total_records: int = 0,
        source_count: int = 0,
        target_count: int = 0,
    ) -> dict:
        """Create a new reconciliation run record."""
        now = datetime.now(timezone.utc).isoformat()
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, status, created_at, total_records,
                    source_count, target_count, ai_provider
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, status, now, total_records, source_count, target_count, ai_provider),
            )
        return self.get_run(run_id)

    def update_run(
        self,
        run_id: str,
        status: Optional[str] = None,
        completed_at: Optional[str] = None,
        total_records: Optional[int] = None,
        source_count: Optional[int] = None,
        target_count: Optional[int] = None,
        matched_count: Optional[int] = None,
        exception_count: Optional[int] = None,
        missing_count: Optional[int] = None,
        unresolved_count: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> Optional[dict]:
        """Update an existing reconciliation run's metrics and status."""
        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if completed_at is not None:
            updates.append("completed_at = ?")
            params.append(completed_at)
        if total_records is not None:
            updates.append("total_records = ?")
            params.append(total_records)
        if source_count is not None:
            updates.append("source_count = ?")
            params.append(source_count)
        if target_count is not None:
            updates.append("target_count = ?")
            params.append(target_count)
        if matched_count is not None:
            updates.append("matched_count = ?")
            params.append(matched_count)
        if exception_count is not None:
            updates.append("exception_count = ?")
            params.append(exception_count)
        if missing_count is not None:
            updates.append("missing_count = ?")
            params.append(missing_count)
        if unresolved_count is not None:
            updates.append("unresolved_count = ?")
            params.append(unresolved_count)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)

        if not updates:
            return self.get_run(run_id)

        params.append(run_id)
        query = f"UPDATE runs SET {', '.join(updates)} WHERE run_id = ?"

        with self.db.transaction() as conn:
            conn.execute(query, params)

        return self.get_run(run_id)

    def get_run(self, run_id: str) -> Optional[dict]:
        """Retrieve run metadata by run_id."""
        conn = self.db.get_connection()
        try:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            if not self.db._is_memory:
                conn.close()

    def list_runs(self, limit: int = 100, offset: int = 0) -> List[dict]:
        """List all reconciliation runs sorted by creation date descending."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self.db._is_memory:
                conn.close()

    # -------------------------------------------------------------------------
    # Canonical Records
    # -------------------------------------------------------------------------

    def save_records(self, run_id: str, records: List[CanonicalRecord]) -> None:
        """Persist ingested CanonicalRecords for a run."""
        if not records:
            return

        rows = []
        for r in records:
            rows.append(
                (
                    run_id,
                    r.record_id,
                    r.source,
                    str(r.amount),
                    r.currency,
                    r.transaction_date.isoformat(),
                    r.settlement_date.isoformat(),
                    r.counterparty,
                    r.source_reference,
                    r.status,
                    r.transaction_type,
                    str(r.gross_amount) if r.gross_amount is not None else None,
                    str(r.fee_amount) if r.fee_amount is not None else None,
                    str(r.net_amount) if r.net_amount is not None else None,
                    json.dumps(r.model_dump(mode="json")),
                )
            )

        with self.db.transaction() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO records (
                    run_id, record_id, source, amount, currency,
                    transaction_date, settlement_date, counterparty,
                    source_reference, status, transaction_type,
                    gross_amount, fee_amount, net_amount, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def get_records(self, run_id: str, source: Optional[str] = None) -> List[CanonicalRecord]:
        """Retrieve CanonicalRecords associated with a run."""
        conn = self.db.get_connection()
        try:
            if source:
                rows = conn.execute(
                    "SELECT raw_payload FROM records WHERE run_id = ? AND source = ?",
                    (run_id, source.upper()),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT raw_payload FROM records WHERE run_id = ?",
                    (run_id,),
                ).fetchall()

            records = []
            for r in rows:
                data = json.loads(r["raw_payload"])
                # Convert string dates and decimals
                data["amount"] = Decimal(str(data["amount"]))
                if data.get("gross_amount") is not None:
                    data["gross_amount"] = Decimal(str(data["gross_amount"]))
                if data.get("fee_amount") is not None:
                    data["fee_amount"] = Decimal(str(data["fee_amount"]))
                if data.get("net_amount") is not None:
                    data["net_amount"] = Decimal(str(data["net_amount"]))
                data["transaction_date"] = date.fromisoformat(data["transaction_date"])
                data["settlement_date"] = date.fromisoformat(data["settlement_date"])
                records.append(CanonicalRecord.model_validate(data))
            return records
        finally:
            if not self.db._is_memory:
                conn.close()

    # -------------------------------------------------------------------------
    # Reconciliation Results
    # -------------------------------------------------------------------------

    def save_results(
        self,
        run_id: str,
        results: List[ReconciliationResult],
        provenance: str = "DETERMINISTIC",
    ) -> None:
        """Persist final ReconciliationResult instances."""
        if not results:
            return

        rows = []
        for r in results:
            rows.append(
                (
                    run_id,
                    r.relationship_id,
                    r.relationship_type.value if hasattr(r.relationship_type, "value") else str(r.relationship_type),
                    r.outcome.value if hasattr(r.outcome, "value") else str(r.outcome),
                    r.exception_type.value if r.exception_type and hasattr(r.exception_type, "value") else (str(r.exception_type) if r.exception_type else None),
                    r.severity.value if r.severity and hasattr(r.severity, "value") else (str(r.severity) if r.severity else None),
                    1 if r.flag_for_review else 0,
                    str(r.reconciled_amount) if r.reconciled_amount is not None else None,
                    json.dumps(r.source_record_ids),
                    json.dumps(r.target_record_ids),
                    provenance,
                )
            )

        with self.db.transaction() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO reconciliation_results (
                    run_id, relationship_id, relationship_type, outcome,
                    exception_type, severity, flag_for_review, reconciled_amount,
                    source_record_ids, target_record_ids, provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def get_results(
        self,
        run_id: str,
        outcome: Optional[str] = None,
        exception_type: Optional[str] = None,
    ) -> List[ReconciliationResult]:
        """Retrieve ReconciliationResults for a run with optional filtering."""
        conn = self.db.get_connection()
        try:
            query = "SELECT * FROM reconciliation_results WHERE run_id = ?"
            params = [run_id]

            if outcome:
                query += " AND outcome = ?"
                params.append(outcome.upper())
            if exception_type:
                query += " AND exception_type = ?"
                params.append(exception_type.upper())

            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                results.append(
                    ReconciliationResult(
                        relationship_id=r["relationship_id"],
                        relationship_type=RelationshipType(r["relationship_type"]),
                        source_record_ids=json.loads(r["source_record_ids"]),
                        target_record_ids=json.loads(r["target_record_ids"]),
                        outcome=ReconciliationOutcome(r["outcome"]),
                        exception_type=ExceptionType(r["exception_type"]) if r["exception_type"] else None,
                        severity=Severity(r["severity"]) if r["severity"] else None,
                        flag_for_review=bool(r["flag_for_review"]),
                        reconciled_amount=Decimal(r["reconciled_amount"]) if r["reconciled_amount"] is not None else None,
                    )
                )
            return results
        finally:
            if not self.db._is_memory:
                conn.close()

    def get_exceptions(self, run_id: str) -> List[ReconciliationResult]:
        """Retrieve all relationships flagged as exceptions or with an exception_type."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT * FROM reconciliation_results
                WHERE run_id = ? AND (outcome = 'EXCEPTION' OR exception_type IS NOT NULL OR flag_for_review = 1)
                """,
                (run_id,),
            ).fetchall()
            results = []
            for r in rows:
                results.append(
                    ReconciliationResult(
                        relationship_id=r["relationship_id"],
                        relationship_type=RelationshipType(r["relationship_type"]),
                        source_record_ids=json.loads(r["source_record_ids"]),
                        target_record_ids=json.loads(r["target_record_ids"]),
                        outcome=ReconciliationOutcome(r["outcome"]),
                        exception_type=ExceptionType(r["exception_type"]) if r["exception_type"] else None,
                        severity=Severity(r["severity"]) if r["severity"] else None,
                        flag_for_review=bool(r["flag_for_review"]),
                        reconciled_amount=Decimal(r["reconciled_amount"]) if r["reconciled_amount"] is not None else None,
                    )
                )
            return results
        finally:
            if not self.db._is_memory:
                conn.close()

    def get_result(self, run_id: str, relationship_id: str) -> Optional[ReconciliationResult]:
        """Retrieve a specific ReconciliationResult by run_id and relationship_id."""
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM reconciliation_results WHERE run_id = ? AND relationship_id = ?",
                (run_id, relationship_id),
            ).fetchone()
            if not row:
                return None
            return ReconciliationResult(
                relationship_id=row["relationship_id"],
                relationship_type=RelationshipType(row["relationship_type"]),
                source_record_ids=json.loads(row["source_record_ids"]),
                target_record_ids=json.loads(row["target_record_ids"]),
                outcome=ReconciliationOutcome(row["outcome"]),
                exception_type=ExceptionType(row["exception_type"]) if row["exception_type"] else None,
                severity=Severity(row["severity"]) if row["severity"] else None,
                flag_for_review=bool(row["flag_for_review"]),
                reconciled_amount=Decimal(row["reconciled_amount"]) if row["reconciled_amount"] is not None else None,
            )
        finally:
            if not self.db._is_memory:
                conn.close()

    # -------------------------------------------------------------------------
    # Candidate Decisions
    # -------------------------------------------------------------------------

    def save_candidate_decisions(self, run_id: str, decisions: List[dict]) -> None:
        """Persist candidate alternatives, AI decisions, confidence, and validation status."""
        if not decisions:
            return

        rows = []
        for d in decisions:
            rows.append(
                (
                    run_id,
                    d.get("anchor_record_id", ""),
                    json.dumps(d.get("candidate_options", [])),
                    d.get("selected_candidate_index"),
                    d.get("ai_outcome"),
                    d.get("ai_exception_type"),
                    d.get("confidence"),
                    d.get("reasoning", ""),
                    d.get("validation_status", "PENDING"),
                    d.get("rejection_reason"),
                )
            )

        with self.db.transaction() as conn:
            conn.executemany(
                """
                INSERT INTO candidate_decisions (
                    run_id, anchor_record_id, candidate_options,
                    selected_candidate_index, ai_outcome, ai_exception_type,
                    confidence, reasoning, validation_status, rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def get_candidates(self, run_id: str) -> List[dict]:
        """Retrieve candidate decisions and validation verdicts for a run."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM candidate_decisions WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            candidates = []
            for r in rows:
                d = dict(r)
                d["candidate_options"] = json.loads(d["candidate_options"])
                candidates.append(d)
            return candidates
        finally:
            if not self.db._is_memory:
                conn.close()

    # -------------------------------------------------------------------------
    # Audit Logs
    # -------------------------------------------------------------------------

    def save_audit_event(
        self,
        run_id: str,
        event_type: str,
        details: Optional[dict] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        """Record an audit log entry for run lifecycle tracking."""
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        details_json = json.dumps(details) if details else None

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs (run_id, timestamp, event_type, details)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, ts, event_type, details_json),
            )

    def get_audit_logs(self, run_id: str) -> List[dict]:
        """Retrieve all audit events for a run in chronological order."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM audit_logs WHERE run_id = ? ORDER BY timestamp ASC, id ASC",
                (run_id,),
            ).fetchall()
            logs = []
            for r in rows:
                d = dict(r)
                if d.get("details"):
                    try:
                        d["details"] = json.loads(d["details"])
                    except Exception:
                        pass
                logs.append(d)
            return logs
        finally:
            if not self.db._is_memory:
                conn.close()

    # -------------------------------------------------------------------------
    # Operator Corrections
    # -------------------------------------------------------------------------

    def save_correction(self, correction: OperatorCorrection) -> None:
        """Persist an immutable operator correction."""
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO operator_corrections (
                    correction_id, run_id, relationship_id,
                    original_outcome, original_exception_type,
                    original_source_ids, original_target_ids,
                    corrected_outcome, corrected_exception_type,
                    corrected_source_ids, corrected_target_ids,
                    operator_reason, created_at, generated_rule_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    correction.correction_id,
                    correction.run_id,
                    correction.relationship_id,
                    correction.original_outcome,
                    correction.original_exception_type,
                    json.dumps(correction.original_source_ids),
                    json.dumps(correction.original_target_ids),
                    correction.corrected_outcome,
                    correction.corrected_exception_type,
                    json.dumps(correction.corrected_source_ids),
                    json.dumps(correction.corrected_target_ids),
                    correction.operator_reason,
                    correction.created_at,
                    correction.generated_rule_id,
                ),
            )

    def get_corrections(self, run_id: str) -> List[OperatorCorrection]:
        """Retrieve all operator corrections for a run in chronological order."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM operator_corrections WHERE run_id = ? ORDER BY created_at ASC, rowid ASC",
                (run_id,),
            ).fetchall()
            return [
                OperatorCorrection(
                    correction_id=r["correction_id"],
                    run_id=r["run_id"],
                    relationship_id=r["relationship_id"],
                    original_outcome=r["original_outcome"],
                    original_exception_type=r["original_exception_type"],
                    original_source_ids=json.loads(r["original_source_ids"]),
                    original_target_ids=json.loads(r["original_target_ids"]),
                    corrected_outcome=r["corrected_outcome"],
                    corrected_exception_type=r["corrected_exception_type"],
                    corrected_source_ids=json.loads(r["corrected_source_ids"]),
                    corrected_target_ids=json.loads(r["corrected_target_ids"]),
                    operator_reason=r["operator_reason"],
                    created_at=r["created_at"],
                    generated_rule_id=r["generated_rule_id"],
                )
                for r in rows
            ]
        finally:
            if not self.db._is_memory:
                conn.close()

    def get_correction(self, correction_id: str) -> Optional[OperatorCorrection]:
        """Retrieve a specific operator correction by ID."""
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM operator_corrections WHERE correction_id = ?",
                (correction_id,),
            ).fetchone()
            if not row:
                return None
            return OperatorCorrection(
                correction_id=row["correction_id"],
                run_id=row["run_id"],
                relationship_id=row["relationship_id"],
                original_outcome=row["original_outcome"],
                original_exception_type=row["original_exception_type"],
                original_source_ids=json.loads(row["original_source_ids"]),
                original_target_ids=json.loads(row["original_target_ids"]),
                corrected_outcome=row["corrected_outcome"],
                corrected_exception_type=row["corrected_exception_type"],
                corrected_source_ids=json.loads(row["corrected_source_ids"]),
                corrected_target_ids=json.loads(row["corrected_target_ids"]),
                operator_reason=row["operator_reason"],
                created_at=row["created_at"],
                generated_rule_id=row["generated_rule_id"],
            )
        finally:
            if not self.db._is_memory:
                conn.close()

    def get_corrections_for_relationship(
        self, run_id: str, relationship_id: str
    ) -> List[OperatorCorrection]:
        """Retrieve all corrections associated with a specific relationship."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT * FROM operator_corrections
                WHERE run_id = ? AND relationship_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (run_id, relationship_id),
            ).fetchall()
            return [
                OperatorCorrection(
                    correction_id=r["correction_id"],
                    run_id=r["run_id"],
                    relationship_id=r["relationship_id"],
                    original_outcome=r["original_outcome"],
                    original_exception_type=r["original_exception_type"],
                    original_source_ids=json.loads(r["original_source_ids"]),
                    original_target_ids=json.loads(r["original_target_ids"]),
                    corrected_outcome=r["corrected_outcome"],
                    corrected_exception_type=r["corrected_exception_type"],
                    corrected_source_ids=json.loads(r["corrected_source_ids"]),
                    corrected_target_ids=json.loads(r["corrected_target_ids"]),
                    operator_reason=r["operator_reason"],
                    created_at=r["created_at"],
                    generated_rule_id=r["generated_rule_id"],
                )
                for r in rows
            ]
        finally:
            if not self.db._is_memory:
                conn.close()

    # -------------------------------------------------------------------------
    # Reconciliation Rules
    # -------------------------------------------------------------------------

    def save_rule(self, rule: ReconciliationRule) -> None:
        """Persist a learned reconciliation rule."""
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reconciliation_rules (
                    rule_id, name, description,
                    source_counterparty_pattern, reference_prefix, currency,
                    max_amount_difference, max_settlement_delay_days,
                    target_action, resulting_outcome, resulting_exception_type,
                    confidence, is_active, created_at, source_correction_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.rule_id,
                    rule.name,
                    rule.description,
                    rule.source_counterparty_pattern,
                    rule.reference_prefix,
                    rule.currency,
                    str(rule.max_amount_difference) if rule.max_amount_difference is not None else None,
                    rule.max_settlement_delay_days,
                    rule.target_action,
                    rule.resulting_outcome,
                    rule.resulting_exception_type,
                    rule.confidence,
                    1 if rule.is_active else 0,
                    rule.created_at,
                    rule.source_correction_id,
                ),
            )

    def get_rule(self, rule_id: str) -> Optional[ReconciliationRule]:
        """Retrieve a rule by its ID."""
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM reconciliation_rules WHERE rule_id = ?",
                (rule_id,),
            ).fetchone()
            if not row:
                return None
            return ReconciliationRule(
                rule_id=row["rule_id"],
                name=row["name"],
                description=row["description"],
                source_counterparty_pattern=row["source_counterparty_pattern"],
                reference_prefix=row["reference_prefix"],
                currency=row["currency"],
                max_amount_difference=Decimal(row["max_amount_difference"]) if row["max_amount_difference"] is not None else None,
                max_settlement_delay_days=row["max_settlement_delay_days"],
                target_action=row["target_action"],
                resulting_outcome=row["resulting_outcome"],
                resulting_exception_type=row["resulting_exception_type"],
                confidence=row["confidence"],
                is_active=bool(row["is_active"]),
                created_at=row["created_at"],
                source_correction_id=row["source_correction_id"],
            )
        finally:
            if not self.db._is_memory:
                conn.close()

    def get_rules(self, active_only: bool = False) -> List[ReconciliationRule]:
        """Retrieve all reconciliation rules."""
        conn = self.db.get_connection()
        try:
            if active_only:
                rows = conn.execute(
                    "SELECT * FROM reconciliation_rules WHERE is_active = 1 ORDER BY confidence DESC, created_at ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM reconciliation_rules ORDER BY created_at DESC"
                ).fetchall()

            return [
                ReconciliationRule(
                    rule_id=row["rule_id"],
                    name=row["name"],
                    description=row["description"],
                    source_counterparty_pattern=row["source_counterparty_pattern"],
                    reference_prefix=row["reference_prefix"],
                    currency=row["currency"],
                    max_amount_difference=Decimal(row["max_amount_difference"]) if row["max_amount_difference"] is not None else None,
                    max_settlement_delay_days=row["max_settlement_delay_days"],
                    target_action=row["target_action"],
                    resulting_outcome=row["resulting_outcome"],
                    resulting_exception_type=row["resulting_exception_type"],
                    confidence=row["confidence"],
                    is_active=bool(row["is_active"]),
                    created_at=row["created_at"],
                    source_correction_id=row["source_correction_id"],
                )
                for row in rows
            ]
        finally:
            if not self.db._is_memory:
                conn.close()

    def update_rule_active_state(self, rule_id: str, is_active: bool) -> Optional[ReconciliationRule]:
        """Activate or deactivate a rule."""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE reconciliation_rules SET is_active = ? WHERE rule_id = ?",
                (1 if is_active else 0, rule_id),
            )
        return self.get_rule(rule_id)

    def delete_run(self, run_id: str) -> bool:
        """Delete a reconciliation run and its owned operational records.
        
        Preserves global learned rules, unrelated runs, and cross-run data.
        Returns True if deleted, False if run was not found.
        """
        run = self.get_run(run_id)
        if not run:
            return False

        with self.db.transaction() as conn:
            conn.execute("DELETE FROM records WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM reconciliation_results WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM candidate_decisions WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM operator_corrections WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM audit_logs WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

        return True

    def delete_rule(self, rule_id: str) -> bool:
        """Delete a learned reconciliation rule by rule_id.
        
        Preserves originating corrections, historical audit events, and runs.
        Returns True if deleted, False if rule was not found.
        """
        rule = self.get_rule(rule_id)
        if not rule:
            return False

        with self.db.transaction() as conn:
            conn.execute("DELETE FROM reconciliation_rules WHERE rule_id = ?", (rule_id,))

        return True



