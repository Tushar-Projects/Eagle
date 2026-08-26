"""Anthropic Claude LLM provider implementation.

Requires: pip install anthropic
"""

from eagle.agents.provider import LLMProvider
from eagle.models.ai_contracts import (
    CandidateSelectionDecision,
    ClassificationCase,
    ExceptionClassificationDecision,
)

try:
    import anthropic
except ImportError:
    raise ImportError(
        "anthropic is required for the Claude provider. "
        "Install it with: pip install anthropic"
    )


class ClaudeProvider(LLMProvider):
    """Anthropic Claude provider implementation."""

    def __init__(self, api_key: str, model: str, timeout: int = 30):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model or "claude-sonnet-4-20250514"
        self._timeout = timeout

    async def classify_exception(
        self, case: ClassificationCase
    ) -> ExceptionClassificationDecision:
        prompt = self._build_exception_prompt(case)
        response = await self._call(prompt)
        return ExceptionClassificationDecision.model_validate_json(response)

    async def select_candidate(
        self, case: ClassificationCase
    ) -> CandidateSelectionDecision:
        prompt = self._build_candidate_prompt(case)
        response = await self._call(prompt)
        return CandidateSelectionDecision.model_validate_json(response)

    async def _call(self, prompt: str) -> str:
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _build_exception_prompt(self, case: ClassificationCase) -> str:
        # Reuse the same prompt-building logic as Gemini
        from eagle.agents._gemini import _build_system_prompt, _build_exception_evidence
        return _build_system_prompt() + "\n\n" + _build_exception_evidence(case)

    def _build_candidate_prompt(self, case: ClassificationCase) -> str:
        from eagle.agents._gemini import _build_system_prompt, _build_candidate_evidence
        return _build_system_prompt() + "\n\n" + _build_candidate_evidence(case)
