"""QA LLM provider interface and implementations for grounded Q&A synthesis."""

from abc import ABC, abstractmethod
import logging
from typing import Callable, Optional

import httpx

from eagle.core.config import Settings

logger = logging.getLogger(__name__)


class QAProvider(ABC):
    """Abstract interface for natural language answer synthesis from grounded context."""

    @abstractmethod
    async def generate_answer(self, prompt: str, system_instruction: str) -> str:
        """Generate a grounded natural language response given prompt and system instruction."""
        pass


class LlamaServerQAProvider(QAProvider):
    """Integrates with externally managed llama-server (OpenAI-compatible /v1/chat/completions)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def generate_answer(self, prompt: str, system_instruction: str) -> str:
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices", [])
                if choices and "message" in choices[0]:
                    return choices[0]["message"]["content"].strip()
                return "Unable to parse response from llama-server."
            except Exception as e:
                logger.warning("llama-server QA request failed: %s", e)
                raise RuntimeError(f"llama-server Q&A generation failed: {e}") from e


class MockQAProvider(QAProvider):
    """Deterministic mock QA provider for hermetic testing and offline validation."""

    def __init__(self, handler: Optional[Callable[[str, str], str]] = None):
        self._handler = handler
        self.call_history: list[dict] = []

    async def generate_answer(self, prompt: str, system_instruction: str) -> str:
        self.call_history.append({"prompt": prompt, "system_instruction": system_instruction})
        if self._handler:
            return self._handler(prompt, system_instruction)

        # Grounded response synthesis based on context contents
        question_part = prompt
        if "OPERATOR QUESTION:" in prompt:
            question_part = prompt.split("OPERATOR QUESTION:")[1].split("ANSWER:")[0]
        q_lower = question_part.lower()

        if "match rate" in q_lower:
            # Extract match rate from context if present
            for line in prompt.splitlines():
                if "Match Rate:" in line:
                    return f"Based on Eagle's records, {line.strip()}."
            return "Based on Eagle's records, the match rate information is detailed in the run summary."

        if "exception" in q_lower:
            exceptions = []
            for line in prompt.splitlines():
                if "Outcome: EXCEPTION" in line or "Exceptions:" in line or "Exception Type:" in line:
                    exceptions.append(line.strip())
            if exceptions:
                return "Eagle recorded the following exceptions: " + "; ".join(exceptions[:3]) + "."
            return "Based on Eagle's records, exceptions were identified during the reconciliation run."

        if "rule" in q_lower:
            for line in prompt.splitlines():
                if "Learned Reconciliation Rule:" in line or "Counterparty Pattern:" in line:
                    return f"Eagle synthesized and activated the learned reconciliation rule: {line.strip()}."
            return "Learned rules were generated from operator corrections to reconcile recurring patterns."

        if "bank-c06" in q_lower or "bank" in q_lower or "gtw" in q_lower:
            for line in prompt.splitlines():
                if "Record ID:" in line:
                    return f"According to Eagle's operational logs, {line.strip()}."
            return "The transaction was processed according to Eagle's deterministic matching and candidate selection logic."

        if "rerun" in q_lower or "improve" in q_lower:
            for line in prompt.splitlines():
                if "Learned Reconciliation Rule:" in line or "Rule" in line or "Match Rate:" in line:
                    return f"The rerun improved reconciliation because {line.strip()} was applied."
            return "The rerun applied learned rules from operator corrections, resolving previous exceptions."

        return "Based on Eagle's stored operational records, the requested details are documented in the retrieved evidence."



def get_qa_provider(settings: Settings) -> QAProvider:
    """Factory creating appropriate QAProvider based on configuration."""
    provider_type = settings.AI_PROVIDER.lower() if settings.AI_PROVIDER else "mock"
    if provider_type == "llama_server":
        return LlamaServerQAProvider(base_url=settings.LLAMA_SERVER_URL, timeout=float(settings.AI_TIMEOUT_SECONDS))
    return MockQAProvider()
