"""Hybrid PDF extractor supporting digital text extraction and scanned vision fallback."""

import io
import logging
import re
from pathlib import Path
from typing import BinaryIO, List, Optional, TextIO, Union

import pypdf
import pypdfium2

from eagle.extraction.csv_extractor import ExtractionValidationError
from eagle.extraction.models import DocumentExtractionResult, RawExtractedTransaction
from eagle.extraction.normalizer import assemble_canonical_record, is_non_transaction_row
from eagle.extraction.vision_extractor import VisionExtractor
from eagle.models.canonical import CanonicalRecord

logger = logging.getLogger(__name__)


class PdfExtractor:
    """Extracts CanonicalRecords from digital or scanned PDF documents."""

    def __init__(self, vision_extractor: Optional[VisionExtractor] = None, max_pages: int = 5):
        self._vision_extractor = vision_extractor or VisionExtractor()
        self._max_pages = max_pages

    def extract(
        self,
        pdf_input: Union[str, Path, TextIO, BinaryIO, bytes],
        source_type: str = "AUTO",
        filename: str = "document.pdf",
    ) -> List[CanonicalRecord]:
        """Synchronous PDF extraction."""
        import asyncio
        return asyncio.run(self.extract_async(pdf_input, source_type, filename))

    async def extract_async(
        self,
        pdf_input: Union[str, Path, TextIO, BinaryIO, bytes],
        source_type: str = "AUTO",
        filename: str = "document.pdf",
    ) -> List[CanonicalRecord]:
        """Asynchronously extract CanonicalRecords from digital or scanned PDF."""
        result = await self.extract_preview_async(pdf_input, source_type, filename)
        effective_source = source_type if source_type in ("GATEWAY", "BANK") else "GATEWAY"

        records: List[CanonicalRecord] = []
        seen_ids: set[str] = set()

        for idx, raw in enumerate(result.raw_transactions, start=1):
            rec = assemble_canonical_record(raw, effective_source, filename, idx)
            if rec.record_id in seen_ids:
                continue
            seen_ids.add(rec.record_id)
            records.append(rec)

        if not records:
            raise ExtractionValidationError(
                f"PDF extraction produced no valid transaction records from '{filename}'."
            )

        return records

    async def extract_preview_async(
        self,
        pdf_input: Union[str, Path, TextIO, BinaryIO, bytes],
        source_type: str = "AUTO",
        filename: str = "document.pdf",
    ) -> DocumentExtractionResult:
        """Extract raw transactions, attempting digital text first with vision fallback."""
        pdf_bytes = self._read_bytes(pdf_input)
        if not pdf_bytes:
            raise ExtractionValidationError("PDF input is empty.")

        # 1. Digital Text Extraction Attempt
        digital_result = self._try_digital_text_extraction(pdf_bytes, filename)
        if digital_result and digital_result.raw_transactions:
            return digital_result

        # 2. Vision Fallback via Page Rasterization
        return await self._extract_via_vision_rasterization(pdf_bytes, filename)

    def _try_digital_text_extraction(self, pdf_bytes: bytes, filename: str) -> Optional[DocumentExtractionResult]:
        """Extract transaction lines directly from digital text streams."""
        try:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            total_pages = min(len(reader.pages), self._max_pages)
            raw_txns: List[RawExtractedTransaction] = []
            warnings: List[str] = []

            for page_idx in range(total_pages):
                page = reader.pages[page_idx]
                text = page.extract_text() or ""
                lines = [l.strip() for l in text.splitlines() if l.strip()]

                for line in lines:
                    if is_non_transaction_row(line):
                        continue

                    parsed_tx = self._parse_text_line_to_transaction(line)
                    if parsed_tx:
                        raw_txns.append(parsed_tx)

            if len(raw_txns) >= 1:
                # Deduplicate repeated carryover rows
                deduped = self._deduplicate_rows(raw_txns)
                return DocumentExtractionResult(
                    filename=filename,
                    file_type="PDF",
                    page_count=total_pages,
                    raw_transactions=deduped,
                    warnings=warnings,
                    extraction_method="DIGITAL_PDF",
                )
        except Exception as e:
            logger.debug("Digital PDF extraction failed for %s: %s", filename, e)

        return None

    def _parse_text_line_to_transaction(self, line: str) -> Optional[RawExtractedTransaction]:
        """Attempt regex table matching for common financial transaction line patterns."""
        # Pattern: Date (YYYY-MM-DD or DD/MM/YYYY or DD-MM-YYYY), Reference, Description/Merchant, Amount, [Optional Fee]
        # Example 1: 2025-01-15 PAY-10001 ACME Corp 5000.00 INR
        # Example 2: 15/01/2025 TXN-992 Payment to Globex 1,500.00
        date_pat = r"(\d{4}[-/.]\d{2}[-/.]\d{2}|\d{2}[-/.]\d{2}[-/.]\d{2,4}|\d{2}-[a-zA-Z]{3}-\d{4})"
        amt_pat = r"([₹$€£]?\s*[-+]?\(?[\d,]+\.\d{2}\)?\s*(?:CR|DR)?)"
        
        match = re.search(f"{date_pat}.*?{amt_pat}", line, re.IGNORECASE)
        if not match:
            return None

        date_str = match.group(1).strip()
        amt_str = match.group(2).strip()

        # Extract tokens between date and amount as reference / description
        start_idx = match.start(1) + len(date_str)
        end_idx = match.start(2)
        middle_text = line[start_idx:end_idx].strip()

        tokens = middle_text.split()
        ref = tokens[0] if tokens else None
        narration = " ".join(tokens[1:]) if len(tokens) > 1 else (tokens[0] if tokens else "Digital PDF Transaction")

        return RawExtractedTransaction(
            raw_reference=ref,
            transaction_date=date_str,
            amount=amt_str,
            currency="INR",
            counterparty=None,
            narration=narration,
            transaction_type="PAYMENT",
            confidence=0.95,
        )

    async def _extract_via_vision_rasterization(
        self,
        pdf_bytes: bytes,
        filename: str,
    ) -> DocumentExtractionResult:
        """Rasterize scanned PDF pages to PNG and query multimodal vision extractor."""
        try:
            pdf_doc = pypdfium2.PdfDocument(pdf_bytes)
        except Exception as e:
            raise ExtractionValidationError(f"Failed to open PDF document: {e}") from e

        total_pages = min(len(pdf_doc), self._max_pages)
        aggregated_txns: List[RawExtractedTransaction] = []
        all_warnings: List[str] = []

        for page_idx in range(total_pages):
            page = pdf_doc[page_idx]
            # Render page to PNG at 150 DPI (scale=2.0)
            bitmap = page.render(scale=2.0)
            pil_image = bitmap.to_pil()
            
            img_buf = io.BytesIO()
            pil_image.save(img_buf, format="PNG")
            png_bytes = img_buf.getvalue()

            page_name = f"{filename}_page_{page_idx + 1}.png"
            page_res = await self._vision_extractor.extract_preview_async(png_bytes, filename=page_name)
            aggregated_txns.extend(page_res.raw_transactions)
            all_warnings.extend(page_res.warnings)

        deduped = self._deduplicate_rows(aggregated_txns)

        return DocumentExtractionResult(
            filename=filename,
            file_type="PDF",
            page_count=total_pages,
            raw_transactions=deduped,
            warnings=all_warnings,
            extraction_method="SCANNED_PDF_VISION",
        )

    def _deduplicate_rows(self, txns: List[RawExtractedTransaction]) -> List[RawExtractedTransaction]:
        """Deduplicate identical rows spanning page boundaries without aggressive fuzzy deletion."""
        seen = set()
        deduped = []
        for t in txns:
            key = (t.transaction_date, t.amount, t.raw_reference, t.narration)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(t)
        return deduped

    def _read_bytes(self, pdf_input: Union[str, Path, TextIO, BinaryIO, bytes]) -> bytes:
        """Load input to bytes."""
        if isinstance(pdf_input, Path):
            if not pdf_input.exists():
                raise ExtractionValidationError(f"PDF file not found: {pdf_input}")
            return pdf_input.read_bytes()
        elif isinstance(pdf_input, str):
            p = Path(pdf_input)
            if p.is_file():
                return p.read_bytes()
            return pdf_input.encode("utf-8")
        elif isinstance(pdf_input, bytes):
            return pdf_input
        elif hasattr(pdf_input, "read"):
            content = pdf_input.read()
            return content if isinstance(content, bytes) else str(content).encode("utf-8")
        else:
            raise ExtractionValidationError(f"Unsupported PDF input type: {type(pdf_input)}")
