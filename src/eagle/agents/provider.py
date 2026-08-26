"""LLM provider abstraction for the AI exception classifier.

Defines the abstract base class and a factory function for
provider-agnostic model selection.
"""

from abc import ABC, abstractmethod

from eagle.models.ai_contracts import (
    ClassificationCase,
    CandidateSelectionDecision,
    ExceptionClassificationDecision,
)


class LLMProvider(ABC):
    """Abstract base for LLM provider implementations."""

    @abstractmethod
    async def classify_exception(
        self, case: ClassificationCase
    ) -> ExceptionClassificationDecision:
        """Classify an exception for a committed relationship."""
        ...

    @abstractmethod
    async def select_candidate(
        self, case: ClassificationCase
    ) -> CandidateSelectionDecision:
        """Select a target from a candidate pool."""
        ...


def create_provider(config) -> LLMProvider:
    """Factory function to create the appropriate LLM provider.

    Provider SDK imports are lazy so that only the selected
    provider's dependencies are required at runtime.
    """
    match config.AI_PROVIDER:
        case "gemini":
            from eagle.agents._gemini import GeminiProvider
            return GeminiProvider(
                api_key=config.GEMINI_API_KEY,
                model=config.AI_MODEL,
                timeout=config.AI_TIMEOUT_SECONDS,
            )
        case "claude":
            from eagle.agents._claude import ClaudeProvider
            return ClaudeProvider(
                api_key=config.CLAUDE_API_KEY,
                model=config.AI_MODEL,
                timeout=config.AI_TIMEOUT_SECONDS,
            )
        case "mock":
            from eagle.agents._mock import MockProvider
            return MockProvider()
        case _:
            raise ValueError(f"Unknown AI provider: {config.AI_PROVIDER}")
