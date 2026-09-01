"""Deterministic document formatting for Eagle's RAG knowledge base."""

from decimal import Decimal
import json
from typing import Dict, List, Optional

from eagle.models.canonical import CanonicalRecord
from eagle.models.reconciliation import ReconciliationResult
from eagle.rag.models import RagDocument
from eagle.rules.models import OperatorCorrection, ReconciliationRule


SIGNIFICANT_AUDIT_EVENTS = {
    "RULE_CREATED",
    "RULE_ACTIVATED",
    "RULE_DEACTIVATED",
    "RULE_APPLICATION_COMPLETED",
    "RULE_APPLICATION_REJECTED",
    "OPERATOR_CORRECTION_CREATED",
    "RERUN_EXECUTED",
    "RUN_COMPLETED",
    "RUN_FAILED",
}


class DocumentBuilder:
    """Transforms SQLite operational entities into structured, human-readable RAG documents."""

    @staticmethod
    def build_run_document(run: dict, metrics: Optional[dict] = None) -> RagDocument:
        """Create a human-readable document for a reconciliation run."""
        run_id = run["run_id"]
        status = run.get("status", "UNKNOWN")
        created_at = run.get("created_at", "")
        completed_at = run.get("completed_at", "")
        ai_provider = run.get("ai_provider", "mock")

        m = metrics or {}
        match_rate = m.get("match_rate", 0.0)
        vw_match_rate = m.get("value_weighted_match_rate", 0.0)
        matched_count = m.get("matched_count", run.get("matched_count", 0))
        exception_count = m.get("exception_count", run.get("exception_count", 0))
        missing_count = m.get("missing_count", run.get("missing_count", 0))
        unresolved_count = m.get("unresolved_count", run.get("unresolved_count", 0))
        reconciled_amt = m.get("total_reconciled_amount", "0.00")

        is_rerun = "-RERUN-" in run_id
        parent_run_id = run_id.split("-RERUN-")[0] if is_rerun else ""

        text_lines = [
            f"# Reconciliation Run: {run_id}",
            f"Status: {status}",
            f"Created At: {created_at}",
            f"Completed At: {completed_at or 'In Progress'}",
            f"AI Provider: {ai_provider}",
            f"Is Rerun: {'Yes' if is_rerun else 'No'}",
        ]
        if is_rerun:
            text_lines.append(f"Parent Run ID: {parent_run_id}")

        text_lines.extend([
            "",
            "## Record Counts",
            f"- Total Ingested: {run.get('total_records', 0)}",
            f"- Gateway (Source) Records: {run.get('source_count', 0)}",
            f"- Bank (Target) Records: {run.get('target_count', 0)}",
            "",
            "## Reconciliation Performance",
            f"- Record-Weighted Match Rate: {match_rate}%",
            f"- Value-Weighted Match Rate: {vw_match_rate}%",
            f"- Matched Relationships: {matched_count}",
            f"- Exceptions: {exception_count}",
            f"- Missing Records: {missing_count}",
            f"- Unresolved Candidates: {unresolved_count}",
            f"- Total Reconciled Volume: INR {reconciled_amt}",
        ])

        return RagDocument(
            id=f"run:{run_id}",
            text="\n".join(text_lines),
            metadata={
                "document_type": "RUN",
                "run_id": run_id,
                "created_at": created_at,
                "status": status,
                "match_rate": float(match_rate),
                "value_weighted_match_rate": float(vw_match_rate),
                "matched_count": int(matched_count),
                "exception_count": int(exception_count),
                "unresolved_count": int(unresolved_count),
                "is_rerun": is_rerun,
                "parent_run_id": parent_run_id,
            },
        )

    @staticmethod
    def build_result_document(
        run_id: str,
        result: ReconciliationResult,
        source_records: Dict[str, CanonicalRecord],
        target_records: Dict[str, CanonicalRecord],
    ) -> RagDocument:
        """Create a human-readable document for a single ReconciliationResult."""
        rel_id = result.relationship_id
        outcome_str = result.outcome.value if hasattr(result.outcome, "value") else str(result.outcome)
        rel_type_str = result.relationship_type.value if hasattr(result.relationship_type, "value") else str(result.relationship_type)
        ex_str = (
            result.exception_type.value
            if result.exception_type and hasattr(result.exception_type, "value")
            else (str(result.exception_type) if result.exception_type else "None")
        )
        sev_str = (
            result.severity.value
            if result.severity and hasattr(result.severity, "value")
            else (str(result.severity) if result.severity else "None")
        )

        text_lines = [
            f"# Reconciliation Result: {rel_id}",
            f"Run ID: {run_id}",
            f"Relationship Type: {rel_type_str}",
            f"Outcome: {outcome_str}",
            f"Exception Type: {ex_str}",
            f"Severity: {sev_str}",
            f"Flagged for Review: {'Yes' if result.flag_for_review else 'No'}",
            f"Reconciled Amount: INR {result.reconciled_amount if result.reconciled_amount is not None else '0.00'}",
            "",
            "## Source Gateway Records:",
        ]

        if not result.source_record_ids:
            text_lines.append("  (None / Missing Source Record)")
        else:
            for sid in result.source_record_ids:
                s = source_records.get(sid)
                if s:
                    text_lines.append(
                        f"  - Record ID: {s.record_id} | Amount: INR {s.amount} {s.currency} | "
                        f"Date: {s.transaction_date} | Counterparty: {s.counterparty or 'N/A'} | "
                        f"Ref: {s.source_reference or 'N/A'}"
                    )
                else:
                    text_lines.append(f"  - Record ID: {sid}")

        text_lines.append("")
        text_lines.append("## Target Bank Records:")
        if not result.target_record_ids:
            text_lines.append("  (None / Missing Bank Record)")
        else:
            for tid in result.target_record_ids:
                t = target_records.get(tid)
                if t:
                    text_lines.append(
                        f"  - Record ID: {t.record_id} | Amount: INR {t.amount} {t.currency} | "
                        f"Settlement Date: {t.settlement_date} | Counterparty: {t.counterparty or 'N/A'} | "
                        f"Ref: {t.source_reference or 'N/A'}"
                    )
                else:
                    text_lines.append(f"  - Record ID: {tid}")

        return RagDocument(
            id=f"result:{run_id}:{rel_id}",
            text="\n".join(text_lines),
            metadata={
                "document_type": "RESULT",
                "run_id": run_id,
                "relationship_id": rel_id,
                "outcome": outcome_str,
                "exception_type": ex_str if ex_str != "None" else "",
                "relationship_type": rel_type_str,
                "reconciled_amount": str(result.reconciled_amount) if result.reconciled_amount is not None else "0.00",
                "source_record_ids": ",".join(result.source_record_ids),
                "target_record_ids": ",".join(result.target_record_ids),
            },
        )

    @staticmethod
    def build_correction_document(correction: OperatorCorrection) -> RagDocument:
        """Create a human-readable document for an OperatorCorrection."""
        text_lines = [
            f"# Operator Correction: {correction.correction_id}",
            f"Run ID: {correction.run_id}",
            f"Relationship ID: {correction.relationship_id}",
            f"Created At: {correction.created_at}",
            "",
            "## State Change",
            f"- Original Outcome: {correction.original_outcome} (Exception: {correction.original_exception_type or 'None'})",
            f"- Corrected Outcome: {correction.corrected_outcome} (Exception: {correction.corrected_exception_type or 'None'})",
            f"- Corrected Source Records: {', '.join(correction.corrected_source_ids) if correction.corrected_source_ids else 'None'}",
            f"- Corrected Target Records: {', '.join(correction.corrected_target_ids) if correction.corrected_target_ids else 'None'}",
            "",
            f"## Operator Rationale",
            correction.operator_reason,
        ]

        if correction.generated_rule_id:
            text_lines.append("")
            text_lines.append(f"## Generated Learned Rule ID: {correction.generated_rule_id}")

        return RagDocument(
            id=f"correction:{correction.correction_id}",
            text="\n".join(text_lines),
            metadata={
                "document_type": "CORRECTION",
                "run_id": correction.run_id,
                "correction_id": correction.correction_id,
                "relationship_id": correction.relationship_id,
                "corrected_outcome": correction.corrected_outcome,
                "corrected_exception_type": correction.corrected_exception_type or "",
                "generated_rule_id": correction.generated_rule_id or "",
                "created_at": correction.created_at,
            },
        )

    @staticmethod
    def build_rule_document(rule: ReconciliationRule) -> RagDocument:
        """Create a human-readable document for a ReconciliationRule."""
        text_lines = [
            f"# Learned Reconciliation Rule: {rule.rule_id}",
            f"Name: {rule.name}",
            f"Description: {rule.description}",
            f"Status: {'ACTIVE' if rule.is_active else 'INACTIVE'}",
            f"Confidence: {rule.confidence}",
            f"Created At: {rule.created_at}",
            "",
            "## Generalized Predicates",
            f"- Counterparty Pattern: {rule.source_counterparty_pattern or 'ANY'}",
            f"- Reference Prefix: {rule.reference_prefix or 'ANY'}",
            f"- Currency: {rule.currency or 'ANY'}",
            f"- Max Amount Difference: INR {rule.max_amount_difference if rule.max_amount_difference is not None else '0.00'}",
            f"- Max Settlement Delay: {rule.max_settlement_delay_days if rule.max_settlement_delay_days is not None else 'ANY'} days",
            "",
            "## Resulting Action & Classification",
            f"- Target Action: {rule.target_action}",
            f"- Resulting Outcome: {rule.resulting_outcome}",
            f"- Resulting Exception Type: {rule.resulting_exception_type or 'None'}",
        ]

        if rule.source_correction_id:
            text_lines.append(f"- Derived From Correction ID: {rule.source_correction_id}")

        return RagDocument(
            id=f"rule:{rule.rule_id}",
            text="\n".join(text_lines),
            metadata={
                "document_type": "RULE",
                "rule_id": rule.rule_id,
                "name": rule.name,
                "is_active": rule.is_active,
                "resulting_outcome": rule.resulting_outcome,
                "resulting_exception_type": rule.resulting_exception_type or "",
                "source_correction_id": rule.source_correction_id or "",
                "created_at": rule.created_at,
            },
        )

    @staticmethod
    def build_audit_document(run_id: str, audit_entry: dict) -> Optional[RagDocument]:
        """Create a document for a significant operational audit log event."""
        event_type = audit_entry.get("event_type", "")
        if event_type not in SIGNIFICANT_AUDIT_EVENTS:
            return None

        audit_id = audit_entry.get("id", "")
        timestamp = audit_entry.get("timestamp", "")
        details = audit_entry.get("details", {})
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except Exception:
                details = {"raw": details}

        text_lines = [
            f"# Operational Audit Event: {event_type}",
            f"Run ID: {run_id}",
            f"Timestamp: {timestamp}",
            "",
            "## Event Details",
        ]
        for k, v in details.items():
            text_lines.append(f"- {k}: {v}")

        return RagDocument(
            id=f"audit:{run_id}:{audit_id}",
            text="\n".join(text_lines),
            metadata={
                "document_type": "AUDIT",
                "run_id": run_id,
                "audit_id": str(audit_id),
                "event_type": event_type,
                "timestamp": timestamp,
            },
        )
