"""Data Transfer Objects (DTOs) for the document and vision extraction pipeline.

These models represent intermediate extraction outputs before deterministic validation,
normalization, and assembly into CanonicalRecord domain instances.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class RawExtractedTransaction(BaseModel):
    """A raw financial transaction row extracted from a document or image."""
    raw_reference: Optional[str] = None
    transaction_date: str
    settlement_date: Optional[str] = None
    amount: str
    currency: str = "INR"
    counterparty: Optional[str] = None
    narration: Optional[str] = None
    transaction_type: Optional[str] = None  # e.g., "PAYMENT", "CREDIT", "DEBIT", "REFUND"
    fee: Optional[str] = None
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class DocumentExtractionResult(BaseModel):
    """The structured extraction outcome for an entire document or batch."""
    filename: str
    file_type: str
    page_count: int = 1
    raw_transactions: List[RawExtractedTransaction] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    extraction_method: str = "AUTO"  # "CSV", "JSON", "DIGITAL_PDF", "VISION_IMAGE", "VISION_PDF"
