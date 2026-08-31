"""Multimodal vision extractor for financial images (PNG, JPG, JPEG).

Communicates with the externally managed llama-server HTTP API using
OpenAI-compatible multimodal chat completions (/v1/chat/completions).
"""

import base64
import json
import logging
import re
from pathlib import Path
from typing import BinaryIO, List, Optional, TextIO, Union

import httpx

from eagle.core.config import settings
from eagle.extraction._mock_vision import MockVisionProvider
from eagle.extraction.csv_extractor import ExtractionValidationError
from eagle.extraction.models import DocumentExtractionResult, RawExtractedTransaction
from eagle.extraction.normalizer import assemble_canonical_record, is_non_transaction_row
from eagle.models.canonical import CanonicalRecord

logger = logging.getLogger(__name__)


def build_vision_system_prompt() -> str:
    return """You are an expert financial transaction extraction system.
Your task is to extract all individual transaction rows from the supplied financial statement, receipt, or ledger image.

CRITICAL EXTRACTION RULES:
1. Extract ONLY actual financial transactions.
2. DO NOT extract:
   - opening balances / balance b/f
   - closing balances / balance c/f
   - totals, subtotals, grand totals, page totals
   - column headers or table header rows
   - bank/merchant account metadata or statement headers
3. For each transaction row, extract:
   - raw_reference: transaction ID, reference number, cheque number, or invoice reference
   - transaction_date: transaction or creation date in YYYY-MM-DD or DD/MM/YYYY format
   - settlement_date: settlement or value date if visible, otherwise null
   - amount: exact numerical monetary amount with decimal (e.g. "5000.00", "1250.50")
   - currency: currency code or symbol (e.g. "INR", "USD", "EUR")
   - counterparty: name of merchant, customer, or recipient if visible
   - narration: description, payment remark, or particulars
   - transaction_type: "PAYMENT", "CREDIT", "DEBIT", or "REFUND"
   - fee: explicit fee amount if broken out, otherwise null
   - confidence: float between 0.0 and 1.0 representing visual extraction clarity
4. Output valid JSON in the exact schema:
{
  "transactions": [
    {
      "raw_reference": "...",
      "transaction_date": "...",
      "settlement_date": null,
      "amount": "...",
      "currency": "INR",
      "counterparty": "...",
      "narration": "...",
      "transaction_type": "...",
      "fee": null,
      "confidence": 0.95
    }
  ]
}
Do not include any prose outside the JSON object."""


class VisionExtractor:
    """Extracts CanonicalRecords from images using multimodal LLM inference."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        provider_type: Optional[str] = None,
    ):
        self._base_url = (base_url or settings.LLAMA_SERVER_URL).rstrip("/")
        self._model = model or settings.AI_MODEL or "google_gemma-4-E2B-it-Q8_0"
        self._timeout = timeout or settings.AI_TIMEOUT_SECONDS
        self._provider_type = provider_type or settings.AI_PROVIDER
        self._mock_provider = MockVisionProvider()

    def extract(
        self,
        image_input: Union[str, Path, TextIO, BinaryIO, bytes],
        source_type: str = "AUTO",
        filename: str = "document.png",
    ) -> List[CanonicalRecord]:
        """Extract canonical records from an image synchronously."""
        import asyncio
        return asyncio.run(self.extract_async(image_input, source_type, filename))

    async def extract_async(
        self,
        image_input: Union[str, Path, TextIO, BinaryIO, bytes],
        source_type: str = "AUTO",
        filename: str = "document.png",
    ) -> List[CanonicalRecord]:
        """Asynchronously extract and assemble CanonicalRecords from image."""
        preview_res = await self.extract_preview_async(image_input, source_type, filename)
        
        effective_source = source_type if source_type in ("GATEWAY", "BANK") else "GATEWAY"
        records: List[CanonicalRecord] = []
        seen_ids: set[str] = set()

        for idx, raw in enumerate(preview_res.raw_transactions, start=1):
            rec = assemble_canonical_record(raw, effective_source, filename, idx)
            if rec.record_id in seen_ids:
                continue
            seen_ids.add(rec.record_id)
            records.append(rec)

        if not records:
            raise ExtractionValidationError(
                f"Vision extraction produced no valid transaction records from '{filename}'."
            )

        return records

    async def extract_preview_async(
        self,
        image_input: Union[str, Path, TextIO, BinaryIO, bytes],
        source_type: str = "AUTO",
        filename: str = "document.png",
    ) -> DocumentExtractionResult:
        """Extract raw transactions without committing to CanonicalRecord representation."""
        image_bytes, mime_type = self._load_image_bytes(image_input, filename)

        if self._provider_type == "mock":
            return await self._mock_provider.extract_transactions_async(image_bytes, filename)

        # Build base64 payload
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64_image}"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": build_vision_system_prompt()},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all transaction table rows from this financial image into structured JSON format."},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        async with httpx.AsyncClient(timeout=float(self._timeout)) as client:
            try:
                resp = await client.post(f"{self._base_url}/v1/chat/completions", json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ExtractionValidationError(
                    f"llama-server returned HTTP {e.response.status_code} during vision extraction: {e.response.text}"
                ) from e
            except Exception as e:
                raise ExtractionValidationError(
                    f"Failed to communicate with llama-server at {self._base_url} for vision extraction: {e}"
                ) from e

            data = resp.json()
            if "choices" not in data or not data["choices"]:
                raise ExtractionValidationError("llama-server vision response missing 'choices'")
            
            content_str = data["choices"][0]["message"]["content"]
            return self._parse_vision_response(content_str, filename)

    def _load_image_bytes(
        self,
        image_input: Union[str, Path, TextIO, BinaryIO, bytes],
        filename: str,
    ) -> tuple[bytes, str]:
        """Read image bytes and resolve MIME type."""
        img_bytes = b""
        if isinstance(image_input, Path):
            if not image_input.exists():
                raise ExtractionValidationError(f"File not found: {image_input}")
            img_bytes = image_input.read_bytes()
        elif isinstance(image_input, str):
            p = Path(image_input)
            if p.is_file():
                img_bytes = p.read_bytes()
            else:
                try:
                    img_bytes = base64.b64decode(image_input)
                except Exception:
                    raise ExtractionValidationError("Invalid image path or base64 string.")
        elif isinstance(image_input, bytes):
            img_bytes = image_input
        elif hasattr(image_input, "read"):
            val = image_input.read()
            img_bytes = val if isinstance(val, bytes) else str(val).encode("utf-8")
        else:
            raise ExtractionValidationError(f"Unsupported image input type: {type(image_input)}")

        if not img_bytes:
            raise ExtractionValidationError("Image input is empty.")

        ext = filename.lower().split(".")[-1] if "." in filename else "png"
        mime_map = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
        }
        mime_type = mime_map.get(ext, "image/png")
        return img_bytes, mime_type

    def _parse_vision_response(self, content_str: str, filename: str) -> DocumentExtractionResult:
        """Parse and validate JSON response from vision model."""
        clean_text = self._strip_fences(content_str)
        try:
            parsed = json.loads(clean_text)
        except Exception as e:
            raise ExtractionValidationError(f"Malformed JSON returned by vision extractor: {e}") from e

        raw_list: list[dict] = []
        if isinstance(parsed, dict):
            if "transactions" in parsed and isinstance(parsed["transactions"], list):
                raw_list = parsed["transactions"]
            elif "records" in parsed and isinstance(parsed["records"], list):
                raw_list = parsed["records"]
            elif "data" in parsed and isinstance(parsed["data"], list):
                raw_list = parsed["data"]
            else:
                raw_list = [parsed]
        elif isinstance(parsed, list):
            raw_list = parsed
        else:
            raise ExtractionValidationError(f"Unexpected vision output structure: {type(parsed).__name__}")

        raw_txns: List[RawExtractedTransaction] = []
        warnings: List[str] = []

        for idx, item in enumerate(raw_list, start=1):
            if not isinstance(item, dict):
                continue

            # Check if row is a header or balance summary
            text_signature = f"{item.get('raw_reference', '')} {item.get('narration', '')} {item.get('counterparty', '')}".strip()
            if text_signature and is_non_transaction_row(text_signature):
                warnings.append(f"Row {idx} filtered: recognized as header or non-transaction balance.")
                continue

            try:
                raw_tx = RawExtractedTransaction(
                    raw_reference=item.get("raw_reference") or item.get("reference") or item.get("id"),
                    transaction_date=str(item.get("transaction_date") or item.get("date") or ""),
                    settlement_date=str(item.get("settlement_date")) if item.get("settlement_date") else None,
                    amount=str(item.get("amount") or ""),
                    currency=str(item.get("currency") or "INR"),
                    counterparty=item.get("counterparty") or item.get("merchant_name"),
                    narration=item.get("narration") or item.get("description"),
                    transaction_type=item.get("transaction_type"),
                    fee=str(item.get("fee")) if item.get("fee") else None,
                    confidence=float(item.get("confidence", 0.8)),
                )
                raw_txns.append(raw_tx)
            except Exception as e:
                warnings.append(f"Row {idx} dropped: validation failed ({e})")

        return DocumentExtractionResult(
            filename=filename,
            file_type="IMAGE",
            page_count=1,
            raw_transactions=raw_txns,
            warnings=warnings,
            extraction_method="MULTIMODAL_VISION",
        )

    @staticmethod
    def _strip_fences(text: str) -> str:
        s = text.strip()
        if s.startswith("```"):
            lines = s.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        return s
