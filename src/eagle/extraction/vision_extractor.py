"""Multimodal vision extractor for financial images (PNG, JPG, JPEG, WEBP).

Coordinates with vision providers (NVIDIA NIM, local llama-server, or mock)
to extract financial transaction tables and assemble validated CanonicalRecords.
"""

import base64
import logging
from pathlib import Path
from typing import Any, BinaryIO, List, Optional, TextIO, Union

from eagle.core.config import settings
from eagle.extraction._llama_vision import LlamaServerVisionProvider
from eagle.extraction._mock_vision import MockVisionProvider
from eagle.extraction._nvidia_nim import (
    NvidiaNimVisionProvider,
    build_vision_prompt_instructions,
    parse_vision_json_response,
    strip_fences,
)
from eagle.extraction.csv_extractor import ExtractionValidationError
from eagle.extraction.models import DocumentExtractionResult, RawExtractedTransaction
from eagle.extraction.normalizer import assemble_canonical_record
from eagle.models.canonical import CanonicalRecord

logger = logging.getLogger(__name__)


def build_vision_system_prompt() -> str:
    """Build the system prompt containing vision extraction rules."""
    return build_vision_prompt_instructions()


class VisionExtractor:
    """Extracts CanonicalRecords from images using multimodal vision inference."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        provider_type: Optional[str] = None,
        api_key: Optional[str] = None,
        provider: Optional[Any] = None,
    ):
        self._provider_type = provider_type or settings.VISION_PROVIDER or "llama_server"
        self._base_url = base_url
        self._model = model
        self._timeout = timeout
        self._api_key = api_key
        self._custom_provider = provider
        self._mock_provider = MockVisionProvider()

    @property
    def provider(self):
        """Resolve the active vision provider implementation."""
        if self._custom_provider is not None:
            return self._custom_provider

        ptype = (self._provider_type or "llama_server").lower().strip()
        if ptype == "mock":
            return self._mock_provider
        elif ptype == "nvidia_nim":
            return NvidiaNimVisionProvider(
                api_key=self._api_key if self._api_key is not None else settings.NVIDIA_NIM_API_KEY,
                base_url=self._base_url or settings.NVIDIA_NIM_BASE_URL,
                model=self._model or settings.VISION_MODEL,
                timeout=self._timeout or settings.VISION_TIMEOUT_SECONDS,
            )
        elif ptype == "llama_server":
            return LlamaServerVisionProvider(
                base_url=self._base_url or settings.LLAMA_SERVER_URL,
                model=self._model or settings.AI_MODEL or "google_gemma-4-E2B-it-Q8_0",
                timeout=self._timeout or settings.AI_TIMEOUT_SECONDS,
            )
        else:
            raise ExtractionValidationError(f"Unknown vision provider: '{self._provider_type}'")

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
        return await self.provider.extract_transactions_async(image_bytes, filename=filename, mime_type=mime_type)

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
        """Backwards-compatible helper for parsing JSON response."""
        return parse_vision_json_response(content_str, filename)

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Backwards-compatible helper for stripping markdown code fences."""
        return strip_fences(text)
