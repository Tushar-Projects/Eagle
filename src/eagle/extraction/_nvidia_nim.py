"""NVIDIA NIM Multimodal Vision Provider for Eagle image and document extraction.

Communicates with the NVIDIA NIM API (OpenAI-compatible chat completions)
using multimodal vision models such as meta/llama-3.2-11b-vision-instruct.
"""

import base64
import json
import logging
from typing import Optional

import httpx

from eagle.core.config import settings
from eagle.extraction.csv_extractor import ExtractionValidationError
from eagle.extraction.models import DocumentExtractionResult, RawExtractedTransaction
from eagle.extraction.normalizer import is_non_transaction_row

logger = logging.getLogger(__name__)


def build_vision_prompt_instructions() -> str:
    """Shared financial vision extraction instructions."""
    return """You are an expert financial transaction extraction system.
Your task is to extract all individual transaction rows from the supplied financial statement, receipt, ledger, or screenshot table.

CRITICAL EXTRACTION RULES:
1. Treat the image as a financial transaction table/document. Read EVERY visible transaction row.
2. Read values directly from table cells horizontally across each row. Associate each value only with the column header for that row. Do not infer values from nearby rows or different rows.
3. DO NOT extract:
   - opening balances / balance b/f
   - closing balances / balance c/f
   - totals, subtotals, grand totals, page totals
   - column headers or table header rows
   - bank/merchant account metadata or statement headers
4. For each transaction row:
   - If a source record ID or reference ID is visible in the image (e.g. SRC-ORBIT-001, BANK-ORBIT-01, TXN-101), copy it character-for-character into "raw_reference". Do not generate a replacement ID.
   - Preserve transaction date when visible (YYYY-MM-DD, DD/MM/YYYY, or DD-MM-YYYY).
   - Preserve settlement date if visible, otherwise null.
   - Preserve numeric monetary amount exactly as shown (e.g. "18500", "7500.00", "11,000.00", "₹ 18,500").
   - Preserve currency code or symbol (e.g. "INR", "USD", "EUR", "₹", "$").
   - Preserve counterparty / merchant name exactly when visible.
   - Preserve narration / description / particulars.
   - Preserve transaction_type ("PAYMENT", "CREDIT", "DEBIT", "REFUND") if visible or inferred from debit/credit columns.
   - Preserve explicit fee amount if broken out, otherwise null.
   - Provide a confidence float between 0.0 and 1.0 representing visual extraction clarity.
5. NEVER invent missing fields. Return null when a field is genuinely unavailable. Do not merge separate rows or skip rows.
6. Return clean structured JSON only in the following schema:
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
Do not include any prose, markdown explanations, or commentary outside the JSON object."""


def strip_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    s = text.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


def parse_vision_json_response(content_str: str, filename: str, extraction_method: str = "MULTIMODAL_VISION") -> DocumentExtractionResult:
    """Parse and validate JSON response into a DocumentExtractionResult."""
    clean_text = strip_fences(content_str)
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

    raw_txns: list[RawExtractedTransaction] = []
    warnings: list[str] = []

    for idx, item in enumerate(raw_list, start=1):
        if not isinstance(item, dict):
            continue

        text_signature = f"{item.get('raw_reference', '')} {item.get('narration', '')} {item.get('counterparty', '')}".strip()
        if text_signature and is_non_transaction_row(text_signature):
            warnings.append(f"Row {idx} filtered: recognized as header or non-transaction balance.")
            continue

        try:
            raw_ref = (
                item.get("raw_reference")
                or item.get("reference")
                or item.get("record_id")
                or item.get("transaction_id")
                or item.get("payment_id")
                or item.get("bank_reference")
                or item.get("id")
            )
            raw_tx = RawExtractedTransaction(
                raw_reference=str(raw_ref).strip() if raw_ref is not None else None,
                transaction_date=str(item.get("transaction_date") or item.get("date") or item.get("created_at") or item.get("posting_date") or ""),
                settlement_date=str(item.get("settlement_date") or item.get("value_date")) if (item.get("settlement_date") or item.get("value_date")) else None,
                amount=str(item.get("amount") or item.get("settlement_amount") or item.get("gross_amount") or ""),
                currency=str(item.get("currency") or "INR"),
                counterparty=item.get("counterparty") or item.get("merchant_name") or item.get("party"),
                narration=item.get("narration") or item.get("description") or item.get("particulars"),
                transaction_type=item.get("transaction_type") or item.get("type"),
                fee=str(item.get("fee") or item.get("fee_amount")) if (item.get("fee") or item.get("fee_amount")) else None,
                confidence=float(item.get("confidence", 0.95)),
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
        extraction_method=extraction_method,
    )


def resolve_chat_completions_url(base_url: str) -> str:
    """Normalize base URL to point directly to /chat/completions."""
    clean = base_url.rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    if clean.endswith("/v1"):
        return f"{clean}/chat/completions"
    return f"{clean}/v1/chat/completions"


class NvidiaNimVisionProvider:
    """NVIDIA NIM Multimodal Vision Provider using OpenAI-compatible chat completions."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        self._api_key = api_key if api_key is not None else settings.NVIDIA_NIM_API_KEY
        self._base_url = (base_url or settings.NVIDIA_NIM_BASE_URL).rstrip("/")
        self._model = model or settings.VISION_MODEL or "meta/llama-3.2-11b-vision-instruct"
        self._timeout = timeout or settings.VISION_TIMEOUT_SECONDS

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    async def extract_transactions_async(
        self,
        image_bytes: bytes,
        filename: str = "document.png",
        mime_type: str = "image/png",
    ) -> DocumentExtractionResult:
        """Extract transactions asynchronously using NVIDIA NIM multimodal vision."""
        if not self._api_key or not self._api_key.strip():
            raise ExtractionValidationError(
                "NVIDIA NIM API key is missing. Please set NVIDIA_NIM_API_KEY in your environment or .env file."
            )

        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64_image}"

        # NVIDIA Llama 3.2 Vision instructions are sent in the USER multimodal message
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": build_vision_prompt_instructions(),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                }
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        endpoint_url = resolve_chat_completions_url(self._base_url)
        headers = {
            "Authorization": f"Bearer {self._api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=float(self._timeout)) as client:
            try:
                resp = await client.post(endpoint_url, json=payload, headers=headers)
                resp.raise_for_status()
            except httpx.TimeoutException as e:
                raise ExtractionValidationError(
                    f"NVIDIA NIM vision extraction timed out after {self._timeout}s."
                ) from e
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                err_text = e.response.text
                if len(err_text) > 500:
                    err_text = err_text[:500] + "... (truncated)"
                raise ExtractionValidationError(
                    f"NVIDIA NIM returned HTTP {status_code} during vision extraction: {err_text}"
                ) from e
            except Exception as e:
                raise ExtractionValidationError(
                    f"Failed to communicate with NVIDIA NIM at {self._base_url}: {e}"
                ) from e

            try:
                data = resp.json()
            except Exception as e:
                raise ExtractionValidationError(f"Invalid JSON response returned by NVIDIA NIM: {e}") from e

            if "choices" not in data or not data["choices"]:
                raise ExtractionValidationError("NVIDIA NIM vision response missing 'choices'")

            choice = data["choices"][0]
            message = choice.get("message", {})
            content_str = message.get("content", "")
            if not content_str:
                raise ExtractionValidationError("NVIDIA NIM vision response returned empty content")

            import os
            if os.getenv("DEBUG_VISION_EXTRACTION") == "1":
                logger.info("[DEBUG_VISION_EXTRACTION] Raw model response content for '%s': %s", filename, content_str)

            result = parse_vision_json_response(content_str, filename, extraction_method="NVIDIA_NIM_VISION")

            if os.getenv("DEBUG_VISION_EXTRACTION") == "1":
                logger.info(
                    "[DEBUG_VISION_EXTRACTION] Parsed %d raw transactions for '%s': %s",
                    len(result.raw_transactions),
                    filename,
                    [t.model_dump() for t in result.raw_transactions],
                )

            return result

    def extract_transactions(
        self,
        image_bytes: bytes,
        filename: str = "document.png",
        mime_type: str = "image/png",
    ) -> DocumentExtractionResult:
        """Synchronous wrapper for extract_transactions_async."""
        import asyncio
        return asyncio.run(self.extract_transactions_async(image_bytes, filename, mime_type))
