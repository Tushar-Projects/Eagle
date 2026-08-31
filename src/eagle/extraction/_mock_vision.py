"""Deterministic offline mock vision provider for testing the extraction pipeline."""

from eagle.extraction.models import DocumentExtractionResult, RawExtractedTransaction


class MockVisionProvider:
    """Mock vision extraction provider returning deterministic RawExtractedTransaction items."""

    def __init__(self, preset_transactions: list[RawExtractedTransaction] | None = None):
        self._preset_transactions = preset_transactions

    async def extract_transactions_async(
        self,
        image_bytes: bytes,
        filename: str = "document.png",
    ) -> DocumentExtractionResult:
        """Extract transactions deterministically from image bytes."""
        if self._preset_transactions is not None:
            txns = self._preset_transactions
        else:
            # Default generic synthetic extraction fixture
            txns = [
                RawExtractedTransaction(
                    raw_reference="TXN-MOCK-001",
                    transaction_date="2025-01-15",
                    settlement_date="2025-01-16",
                    amount="2500.00",
                    currency="INR",
                    counterparty="Mock Merchant",
                    narration="Payment for goods",
                    transaction_type="PAYMENT",
                    fee="25.00",
                    confidence=0.95,
                ),
                RawExtractedTransaction(
                    raw_reference="TXN-MOCK-002",
                    transaction_date="2025-01-16",
                    settlement_date="2025-01-16",
                    amount="4750.50",
                    currency="INR",
                    counterparty="Acme Corp",
                    narration="Direct settlement",
                    transaction_type="PAYMENT",
                    fee=None,
                    confidence=0.90,
                ),
            ]

        return DocumentExtractionResult(
            filename=filename,
            file_type="IMAGE",
            page_count=1,
            raw_transactions=txns,
            warnings=[],
            extraction_method="MOCK_VISION",
        )

    def extract_transactions(
        self,
        image_bytes: bytes,
        filename: str = "document.png",
    ) -> DocumentExtractionResult:
        """Synchronous wrapper."""
        import asyncio
        return asyncio.run(self.extract_transactions_async(image_bytes, filename))
