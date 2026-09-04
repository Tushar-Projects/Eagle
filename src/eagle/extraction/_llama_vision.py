"""Local llama-server Vision Provider for Eagle image and document extraction."""

import base64
import logging
from typing import Optional

import httpx

from eagle.core.config import settings
from eagle.extraction._nvidia_nim import (
    build_vision_prompt_instructions,
    parse_vision_json_response,
)
from eagle.extraction.csv_extractor import ExtractionValidationError
from eagle.extraction.models import DocumentExtractionResult

logger = logging.getLogger(__name__)


class LlamaServerVisionProvider:
    """Local llama-server vision extraction provider using multimodal chat completions."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        self._base_url = (base_url or settings.LLAMA_SERVER_URL).rstrip("/")
        self._model = model or settings.AI_MODEL or "google_gemma-4-E2B-it-Q8_0"
        self._timeout = timeout or settings.AI_TIMEOUT_SECONDS

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
        """Extract transactions from image using local llama-server."""
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64_image}"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": build_vision_prompt_instructions()},
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

        url = f"{self._base_url}/v1/chat/completions" if not self._base_url.endswith("/v1/chat/completions") else self._base_url

        async with httpx.AsyncClient(timeout=float(self._timeout)) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ExtractionValidationError(
                    f"llama-server returned HTTP {e.response.status_code} during vision extraction: {e.response.text}"
                ) from e
            except Exception as e:
                raise ExtractionValidationError(
                    f"Failed to communicate with llama-server at {self._base_url} for vision extraction: {e}"
                ) from e

            try:
                data = resp.json()
            except Exception as e:
                raise ExtractionValidationError(f"Invalid JSON response returned by llama-server: {e}") from e

            if "choices" not in data or not data["choices"]:
                raise ExtractionValidationError("llama-server vision response missing 'choices'")

            content_str = data["choices"][0]["message"]["content"]
            return parse_vision_json_response(content_str, filename, extraction_method="MULTIMODAL_VISION")

    def extract_transactions(
        self,
        image_bytes: bytes,
        filename: str = "document.png",
        mime_type: str = "image/png",
    ) -> DocumentExtractionResult:
        """Synchronous wrapper."""
        import asyncio
        return asyncio.run(self.extract_transactions_async(image_bytes, filename, mime_type))
