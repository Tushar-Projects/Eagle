"""JSON exporter for serializing reconciliation results."""

import json
from typing import Any, Dict, List, Optional

from eagle.models.reconciliation import ReconciliationResult


def export_results_to_json(
    results: List[ReconciliationResult],
    run_metadata: Optional[Dict[str, Any]] = None,
    provenance: str = "DETERMINISTIC_AND_AI",
) -> str:
    """Serialize ReconciliationResult objects into a structured JSON string.

    Args:
        results: List of ReconciliationResult instances.
        run_metadata: Optional run summary metadata.
        provenance: Default provenance tag.

    Returns:
        Formatted JSON string.
    """
    items = []
    for r in results:
        items.append(
            {
                "relationship_id": r.relationship_id,
                "relationship_type": (
                    r.relationship_type.value
                    if hasattr(r.relationship_type, "value")
                    else str(r.relationship_type)
                ),
                "source_record_ids": r.source_record_ids,
                "target_record_ids": r.target_record_ids,
                "outcome": (
                    r.outcome.value
                    if hasattr(r.outcome, "value")
                    else str(r.outcome)
                ),
                "exception_type": (
                    r.exception_type.value
                    if r.exception_type and hasattr(r.exception_type, "value")
                    else (str(r.exception_type) if r.exception_type else None)
                ),
                "severity": (
                    r.severity.value
                    if r.severity and hasattr(r.severity, "value")
                    else (str(r.severity) if r.severity else None)
                ),
                "flag_for_review": r.flag_for_review,
                "reconciled_amount": (
                    str(r.reconciled_amount)
                    if r.reconciled_amount is not None
                    else None
                ),
                "provenance": provenance,
            }
        )

    payload = {
        "run": run_metadata or {},
        "total_results": len(items),
        "results": items,
    }

    return json.dumps(payload, indent=2)
