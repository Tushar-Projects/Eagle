"""CSV exporter for serializing reconciliation results."""

import csv
import io
import json
from typing import List

from eagle.models.reconciliation import ReconciliationResult


def export_results_to_csv(
    results: List[ReconciliationResult],
    provenance: str = "DETERMINISTIC_AND_AI",
) -> str:
    """Serialize ReconciliationResult objects into a standard CSV string.

    Args:
        results: List of ReconciliationResult instances.
        provenance: Default provenance tag if not stored per result.

    Returns:
        CSV string content with standard header and row serialization.
    """
    output = io.StringIO()
    fieldnames = [
        "relationship_id",
        "source_record_ids",
        "target_record_ids",
        "relationship_type",
        "outcome",
        "exception_type",
        "severity",
        "flag_for_review",
        "reconciled_amount",
        "provenance",
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()

    for r in results:
        writer.writerow(
            {
                "relationship_id": r.relationship_id,
                "source_record_ids": json.dumps(r.source_record_ids),
                "target_record_ids": json.dumps(r.target_record_ids),
                "relationship_type": (
                    r.relationship_type.value
                    if hasattr(r.relationship_type, "value")
                    else str(r.relationship_type)
                ),
                "outcome": (
                    r.outcome.value
                    if hasattr(r.outcome, "value")
                    else str(r.outcome)
                ),
                "exception_type": (
                    r.exception_type.value
                    if r.exception_type and hasattr(r.exception_type, "value")
                    else (str(r.exception_type) if r.exception_type else "")
                ),
                "severity": (
                    r.severity.value
                    if r.severity and hasattr(r.severity, "value")
                    else (str(r.severity) if r.severity else "")
                ),
                "flag_for_review": "TRUE" if r.flag_for_review else "FALSE",
                "reconciled_amount": (
                    str(r.reconciled_amount)
                    if r.reconciled_amount is not None
                    else "0.00"
                ),
                "provenance": provenance,
            }
        )

    return output.getvalue()
