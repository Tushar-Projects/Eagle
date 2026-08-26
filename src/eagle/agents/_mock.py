"""Mock LLM provider for testing.

Returns pre-configured deterministic responses.
No external dependencies required.
"""

from typing import Callable

from eagle.agents.provider import LLMProvider
from eagle.models.ai_contracts import (
    CandidateSelectionDecision,
    ClassificationCase,
    ExceptionClassificationDecision,
)


class MockProvider(LLMProvider):
    """Deterministic mock provider for testing.

    Supports two modes:
    1. Default: returns generic safe responses.
    2. Custom: uses caller-supplied response functions.
    """

    def __init__(
        self,
        exception_handler: Callable[[ClassificationCase], ExceptionClassificationDecision] | None = None,
        candidate_handler: Callable[[ClassificationCase], CandidateSelectionDecision] | None = None,
    ):
        self._exception_handler = exception_handler
        self._candidate_handler = candidate_handler
        self.exception_calls: list[ClassificationCase] = []
        self.candidate_calls: list[ClassificationCase] = []

    async def classify_exception(
        self, case: ClassificationCase
    ) -> ExceptionClassificationDecision:
        self.exception_calls.append(case)
        if self._exception_handler:
            return self._exception_handler(case)
        # Default: return UNKNOWN classification
        return ExceptionClassificationDecision(
            exception_type="UNKNOWN",
            severity="HIGH",
            flag_for_review=True,
            reasoning="Mock default classification",
            confidence=0.5,
        )

    async def select_candidate(
        self, case: ClassificationCase
    ) -> CandidateSelectionDecision:
        self.candidate_calls.append(case)
        if self._candidate_handler:
            return self._candidate_handler(case)
        # Default: select first candidate if available
        selected = case.candidate_target_record_ids[:1]
        return CandidateSelectionDecision(
            selected_target_record_ids=selected,
            relationship_type="1:1",
            outcome="MATCHED",
            exception_type=None,
            severity=None,
            flag_for_review=False,
            reconciled_amount=str(case.source_amounts[0]) if case.source_amounts else "0",
            reasoning="Mock default selection",
            confidence=0.5,
        )
