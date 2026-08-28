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

        # Evaluate candidate options using deterministic mock heuristic
        selected_idx = None
        if case.candidate_options:
            for i, opt in enumerate(case.candidate_options):
                src = opt.source_record_ids[0]
                core_id = src.replace("GTW-", "").split("-")[0]
                if all(core_id in t for t in opt.target_record_ids):
                    selected_idx = i
                    break

        if selected_idx is not None and case.candidate_options:
            chosen = case.candidate_options[selected_idx]
            if len(chosen.source_record_ids) > 1 and len(chosen.target_record_ids) == 1:
                rel_type = "N:1"
            elif len(chosen.source_record_ids) == 1 and len(chosen.target_record_ids) > 1:
                rel_type = "1:N"
            else:
                rel_type = "1:1"

            # Calculate sum of source amounts for chosen option
            from decimal import Decimal
            amt_sum = Decimal("0.00")
            for sid in chosen.source_record_ids:
                if sid in case.source_record_ids:
                    s_idx = case.source_record_ids.index(sid)
                    amt_sum += Decimal(str(case.source_amounts[s_idx]))

            return CandidateSelectionDecision(
                selected_candidate_index=selected_idx,
                relationship_type=rel_type,
                outcome="MATCHED",
                exception_type=None,
                severity=None,
                flag_for_review=False,
                reconciled_amount=str(amt_sum),
                reasoning="Mock heuristic match",
                confidence=0.9,
            )

        # Default abstention: when no candidate option satisfies the heuristic criteria
        from decimal import Decimal
        source_total = sum(case.source_amounts) if case.source_amounts else Decimal("0.00")

        return CandidateSelectionDecision(
            selected_candidate_index=None,
            relationship_type="1:1",
            outcome="EXCEPTION",
            exception_type="POSSIBLE_DUPLICATE",
            severity="MEDIUM",
            flag_for_review=True,
            reconciled_amount=str(source_total),
            reasoning="Mock default abstention: no candidate option matched heuristic criteria",
            confidence=0.5,
        )
