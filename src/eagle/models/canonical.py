"""Canonical record schema for the Eagle reconciliation system.

This module defines the shared canonical record representation used
across all input sources (payment gateway exports, bank statements, etc.).
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class CanonicalRecord(BaseModel):
    """Shared canonical record schema across all input sources.

    Extraction confidence is field-level, not record-level.
    Confidence values are confidence/risk signals,
    NOT calibrated probabilities.
    """

    # --- Required fields ---
    record_id: str
    transaction_id: str
    source: str
    source_reference: str
    amount: Decimal
    currency: str
    transaction_date: date
    settlement_date: date
    counterparty: str
    status: str
    transaction_type: str
    related_record_ids: list[str] = Field(default_factory=list)

    # --- Additional nullable fields ---
    gross_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    net_amount: Decimal | None = None

    # --- Field-level extraction confidence ---
    # Maps canonical field names to confidence scores in [0.0, 1.0].
    # These are confidence/risk signals, NOT calibrated probabilities.
    # Not coupled to any specific LLM provider.
    extraction_confidence: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_extraction_confidence(self) -> "CanonicalRecord":
        """Validate confidence keys and values.

        Keys must correspond to actual canonical field names.
        Values must be in [0.0, 1.0].
        """
        eligible = {
            name
            for name in CanonicalRecord.model_fields
            if name != "extraction_confidence"
        }
        for field_name, confidence in self.extraction_confidence.items():
            if field_name not in eligible:
                raise ValueError(
                    f"Extraction confidence key '{field_name}' is not a "
                    f"valid canonical field. Valid fields: "
                    f"{sorted(eligible)}"
                )
            if not (0.0 <= confidence <= 1.0):
                raise ValueError(
                    f"Extraction confidence for '{field_name}' must be "
                    f"between 0.0 and 1.0, got {confidence}"
                )
        return self

