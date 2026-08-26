"""Google Gemini LLM provider implementation.

Requires: pip install google-genai
"""

from eagle.agents.provider import LLMProvider
from eagle.models.ai_contracts import (
    CandidateSelectionDecision,
    ClassificationCase,
    ExceptionClassificationDecision,
)

try:
    from google import genai
except ImportError:
    raise ImportError(
        "google-genai is required for the Gemini provider. "
        "Install it with: pip install google-genai"
    )


class GeminiProvider(LLMProvider):
    """Google Gemini provider implementation."""

    def __init__(self, api_key: str, model: str, timeout: int = 30):
        self._client = genai.Client(api_key=api_key)
        self._model = model or "gemini-2.5-flash"
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
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
        )
        return response.text

    def _build_exception_prompt(self, case: ClassificationCase) -> str:
        return _build_system_prompt() + "\n\n" + _build_exception_evidence(case)

    def _build_candidate_prompt(self, case: ClassificationCase) -> str:
        return _build_system_prompt() + "\n\n" + _build_candidate_evidence(case)


def _build_system_prompt() -> str:
    return """You are a financial reconciliation exception classifier.

RULES:
- You MUST only use record IDs that appear in the supplied evidence.
- You MUST NOT fabricate transaction IDs, bank references, or any identifiers.
- You MUST NOT create N:M relationships.
- You MUST use only these relationship types: 1:1, 1:N, N:1.
- You MUST use only these exception types: SETTLEMENT_DELAY, FEE_DEDUCTION, ROUNDING_DIFFERENCE, PARTIAL_SETTLEMENT, SPLIT_SETTLEMENT, DUPLICATE, MISSING_RECORD, CURRENCY_MISMATCH, POSSIBLE_DUPLICATE, UNKNOWN.
- You MUST NOT override deterministic financial facts (amounts, currencies, dates).
- For CANDIDATE_SELECTION: select exactly one target, or select none if evidence is insufficient.
- Output valid JSON conforming to the provided schema."""


def _build_exception_evidence(case: ClassificationCase) -> str:
    lines = [f"CASE TYPE: {case.case_type}", "", "SOURCE RECORDS:"]
    for i, sid in enumerate(case.source_record_ids):
        lines.append(f"- ID: {sid}, Amount: {case.source_amounts[i]} {case.source_currencies[i]}, Date: {case.source_transaction_dates[i]}")
    lines.append("")
    lines.append("TARGET RECORDS:")
    for i, tid in enumerate(case.committed_target_record_ids):
        lines.append(f"- ID: {tid}, Amount: {case.target_amounts[i]} {case.target_currencies[i]}, Settlement: {case.target_settlement_dates[i]}")
    lines.append("")
    lines.append(f"EVIDENCE: {case.evidence_summary}")
    lines.append("")
    lines.append('Output JSON: {"exception_type": "...", "severity": "...", "flag_for_review": true/false, "reasoning": "...", "confidence": 0.0-1.0}')
    return "\n".join(lines)


def _build_candidate_evidence(case: ClassificationCase) -> str:
    lines = [f"CASE TYPE: {case.case_type}", "", "SOURCE RECORDS:"]
    for i, sid in enumerate(case.source_record_ids):
        lines.append(f"- ID: {sid}, Amount: {case.source_amounts[i]} {case.source_currencies[i]}, Date: {case.source_transaction_dates[i]}")
    lines.append("")
    lines.append("CANDIDATE TARGET RECORDS:")
    for i, tid in enumerate(case.candidate_target_record_ids):
        lines.append(f"- ID: {tid}, Amount: {case.target_amounts[i]} {case.target_currencies[i]}, Settlement: {case.target_settlement_dates[i]}")
    lines.append("")
    lines.append(f"EVIDENCE: {case.evidence_summary}")
    lines.append("")
    lines.append('Output JSON: {"selected_target_record_ids": [...], "relationship_type": "...", "outcome": "...", "exception_type": "...", "severity": "...", "flag_for_review": true/false, "reconciled_amount": "...", "reasoning": "...", "confidence": 0.0-1.0}')
    return "\n".join(lines)
