"""Unified extractor router for multi-format document ingestion."""

from pathlib import Path
from typing import BinaryIO, List, Optional, TextIO, Union

from eagle.extraction.csv_extractor import CsvExtractor, ExtractionValidationError
from eagle.extraction.json_extractor import JsonExtractor
from eagle.extraction.models import DocumentExtractionResult, RawExtractedTransaction
from eagle.extraction.pdf_extractor import PdfExtractor
from eagle.extraction.vision_extractor import VisionExtractor
from eagle.models.canonical import CanonicalRecord


class ExtractorRouter:
    """Detects file formats and routes ingestion to the appropriate specialized extractor."""

    def __init__(
        self,
        csv_extractor: Optional[CsvExtractor] = None,
        json_extractor: Optional[JsonExtractor] = None,
        pdf_extractor: Optional[PdfExtractor] = None,
        vision_extractor: Optional[VisionExtractor] = None,
    ):
        self.csv_extractor = csv_extractor or CsvExtractor()
        self.json_extractor = json_extractor or JsonExtractor()
        self.vision_extractor = vision_extractor or VisionExtractor()
        self.pdf_extractor = pdf_extractor or PdfExtractor(vision_extractor=self.vision_extractor)

    def detect_format(
        self,
        file_input: Union[str, Path, TextIO, BinaryIO, bytes],
        filename: str = "",
        content_type: Optional[str] = None,
    ) -> str:
        """Detect file format using magic bytes, MIME content_type, and extension fallback."""
        header_bytes = self._peek_bytes(file_input, num_bytes=32)

        # 1. Magic Bytes Sniffing
        if header_bytes.startswith(b"%PDF-"):
            return "PDF"
        if header_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "IMAGE"
        if header_bytes.startswith(b"\xff\xd8\xff"):
            return "IMAGE"
        if header_bytes.startswith(b"RIFF") and b"WEBP" in header_bytes:
            return "IMAGE"

        # Check JSON magic
        stripped = header_bytes.strip()
        if stripped.startswith(b"{") or stripped.startswith(b"["):
            return "JSON"

        # 2. Content-Type Header Sniffing
        if content_type:
            ct = content_type.lower().strip()
            if "pdf" in ct:
                return "PDF"
            if "image" in ct or ct in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
                return "IMAGE"
            if "json" in ct:
                return "JSON"
            if "csv" in ct or "text/csv" in ct:
                return "CSV"

        # 3. File Extension Fallback
        fn = filename.lower()
        if fn.endswith(".pdf"):
            return "PDF"
        if fn.endswith((".png", ".jpg", ".jpeg", ".webp")):
            return "IMAGE"
        if fn.endswith(".json"):
            return "JSON"
        if fn.endswith(".csv") or fn.endswith(".txt"):
            return "CSV"

        # Default fallback to CSV
        return "CSV"

    async def extract_async(
        self,
        file_input: Union[str, Path, TextIO, BinaryIO, bytes],
        source_type: str = "AUTO",
        filename: str = "document",
        content_type: Optional[str] = None,
    ) -> List[CanonicalRecord]:
        """Route and execute extraction asynchronously."""
        fmt = self.detect_format(file_input, filename, content_type)

        if fmt == "CSV":
            return self.csv_extractor.extract(file_input, source_type=source_type)
        elif fmt == "JSON":
            return self.json_extractor.extract(file_input, source_type=source_type)
        elif fmt == "PDF":
            return await self.pdf_extractor.extract_async(file_input, source_type=source_type, filename=filename)
        elif fmt == "IMAGE":
            return await self.vision_extractor.extract_async(file_input, source_type=source_type, filename=filename)
        else:
            raise ExtractionValidationError(f"Unsupported document format '{fmt}' for file '{filename}'.")

    def extract(
        self,
        file_input: Union[str, Path, TextIO, BinaryIO, bytes],
        source_type: str = "AUTO",
        filename: str = "document",
        content_type: Optional[str] = None,
    ) -> List[CanonicalRecord]:
        """Route and execute extraction synchronously."""
        import asyncio
        return asyncio.run(self.extract_async(file_input, source_type, filename, content_type))

    async def extract_preview_async(
        self,
        file_input: Union[str, Path, TextIO, BinaryIO, bytes],
        source_type: str = "AUTO",
        filename: str = "document",
        content_type: Optional[str] = None,
    ) -> DocumentExtractionResult:
        """Extract transactions as a preview result without CanonicalRecord instantiation."""
        fmt = self.detect_format(file_input, filename, content_type)

        if fmt == "PDF":
            return await self.pdf_extractor.extract_preview_async(file_input, source_type=source_type, filename=filename)
        elif fmt == "IMAGE":
            return await self.vision_extractor.extract_preview_async(file_input, source_type=source_type, filename=filename)
        elif fmt == "CSV":
            records = self.csv_extractor.extract(file_input, source_type=source_type)
            raws = [
                RawExtractedTransaction(
                    record_id=r.record_id,
                    raw_reference=r.source_reference,
                    transaction_date=r.transaction_date.isoformat(),
                    settlement_date=r.settlement_date.isoformat() if r.settlement_date else None,
                    amount=str(r.amount),
                    currency=r.currency,
                    counterparty=r.counterparty,
                    narration=r.source_reference,
                    transaction_type=r.transaction_type,
                    fee=str(r.fee_amount) if r.fee_amount is not None else None,
                    confidence=1.0,
                )
                for r in records
            ]
            return DocumentExtractionResult(
                filename=filename,
                file_type="CSV",
                page_count=1,
                raw_transactions=raws,
                warnings=[],
                extraction_method="CSV",
            )
        elif fmt == "JSON":
            records = self.json_extractor.extract(file_input, source_type=source_type)
            raws = [
                RawExtractedTransaction(
                    record_id=r.record_id,
                    raw_reference=r.source_reference,
                    transaction_date=r.transaction_date.isoformat(),
                    settlement_date=r.settlement_date.isoformat() if r.settlement_date else None,
                    amount=str(r.amount),
                    currency=r.currency,
                    counterparty=r.counterparty,
                    narration=r.source_reference,
                    transaction_type=r.transaction_type,
                    fee=str(r.fee_amount) if r.fee_amount is not None else None,
                    confidence=1.0,
                )
                for r in records
            ]
            return DocumentExtractionResult(
                filename=filename,
                file_type="JSON",
                page_count=1,
                raw_transactions=raws,
                warnings=[],
                extraction_method="JSON",
            )
        else:
            raise ExtractionValidationError(f"Unsupported document format '{fmt}' for file '{filename}'.")

    def _peek_bytes(
        self,
        file_input: Union[str, Path, TextIO, BinaryIO, bytes],
        num_bytes: int = 32,
    ) -> bytes:
        """Peek at initial bytes without consuming the stream."""
        if isinstance(file_input, bytes):
            return file_input[:num_bytes]
        elif isinstance(file_input, Path):
            if file_input.exists():
                with open(file_input, "rb") as f:
                    return f.read(num_bytes)
            return b""
        elif isinstance(file_input, str):
            p = Path(file_input)
            if p.is_file():
                with open(p, "rb") as f:
                    return f.read(num_bytes)
            return file_input.encode("utf-8")[:num_bytes]
        elif hasattr(file_input, "seek") and hasattr(file_input, "read"):
            pos = file_input.tell() if hasattr(file_input, "tell") else 0
            val = file_input.read(num_bytes)
            if hasattr(file_input, "seek"):
                file_input.seek(pos)
            return val if isinstance(val, bytes) else str(val).encode("utf-8")
        return b""
