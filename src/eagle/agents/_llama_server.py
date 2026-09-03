"""Local llama-server LLM provider implementation.

Communicates with an externally managed llama-server HTTP service
via its OpenAI-compatible HTTP API (/v1/chat/completions).
"""

import json
import re
from typing import Any
import httpx

from eagle.agents.provider import LLMProvider
from eagle.models.ai_contracts import (
    CandidateSelectionDecision,
    ClassificationCase,
    ExceptionClassificationDecision,
)


class LlamaServerProvider(LLMProvider):
    """Provider connecting to an external llama-server instance."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        model: str = "",
        timeout: int = 120,
        check_health: bool = True,
    ):
        self._base_url = (base_url or "http://127.0.0.1:8000").rstrip("/")
        self._model = model or "local-model"
        self._timeout = timeout
        if check_health:
            self.check_server_health()

    def check_server_health(self) -> bool:
        """Verify that the llama-server service is reachable and healthy."""
        try:
            with httpx.Client(timeout=min(float(self._timeout), 5.0)) as client:
                resp = client.get(f"{self._base_url}/health")
                if resp.status_code == 200:
                    return True
                resp_models = client.get(f"{self._base_url}/v1/models")
                if resp_models.status_code == 200:
                    return True
        except Exception as e:
            raise RuntimeError(
                f"llama-server is unavailable at {self._base_url}. "
                f"Please ensure llama-server is running. (Error: {e})"
            ) from e

        raise RuntimeError(
            f"llama-server returned unhealthy status from {self._base_url}."
        )

    async def classify_exception(
        self, case: ClassificationCase
    ) -> ExceptionClassificationDecision:
        prompt = self._build_exception_prompt(case)
        response_text = await self._call(prompt)
        clean_json = self._normalize_exception_json(response_text)
        return ExceptionClassificationDecision.model_validate_json(clean_json)

    async def select_candidate(
        self, case: ClassificationCase
    ) -> CandidateSelectionDecision:
        prompt = self._build_candidate_prompt(case)
        response_text = await self._call(prompt)
        clean_json = self._normalize_candidate_json(response_text, case)
        return CandidateSelectionDecision.model_validate_json(clean_json)

    async def _call(self, user_prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        async with httpx.AsyncClient(timeout=float(self._timeout)) as client:
            try:
                resp = await client.post(
                    f"{self._base_url}/v1/chat/completions",
                    json=payload,
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise RuntimeError(
                    f"llama-server returned HTTP {e.response.status_code}: {e.response.text}"
                ) from e
            except httpx.RequestError as e:
                raise RuntimeError(
                    f"Failed to communicate with llama-server at {self._base_url}: {e}"
                ) from e

            data = resp.json()
            if "choices" not in data or not data["choices"]:
                raise RuntimeError("llama-server response missing 'choices'")
            return data["choices"][0]["message"]["content"]

    def _build_exception_prompt(self, case: ClassificationCase) -> str:
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
        lines.append('Output JSON format:\n{"exception_type": "...", "severity": "...", "flag_for_review": true/false, "reasoning": "...", "confidence": 0.0-1.0}')
        return "\n".join(lines)

    def _build_candidate_prompt(self, case: ClassificationCase) -> str:
        lines = [
            f"CASE TYPE: {case.case_type}",
            "",
            "TRANSACTION METADATA:",
            case.evidence_summary,
            "",
            "CANDIDATE OPTIONS:",
        ]
        if case.candidate_options:
            for idx, opt in enumerate(case.candidate_options):
                lines.append(f"Option {idx}:")
                lines.append(f"  Sources: {opt.source_record_ids}")
                lines.append(f"  Targets: {opt.target_record_ids}")
        lines.append("")
        lines.append("CRITICAL INSTRUCTIONS:")
        lines.append("1. AMBIGUITY ABSTENTION: When candidate_options contains more than 1 option (e.g. multiple competing targets, conflicting counterparties, or competing 1:1 vs 1:N split aggregations), this represents an unresolved business ambiguity that must be decided by human operator rules. You MUST ABSTAIN: do not choose any option; return selected_candidate_index = null, relationship_type = '1:1', outcome = 'EXCEPTION', exception_type = 'POSSIBLE_DUPLICATE', severity = 'MEDIUM', flag_for_review = true, and state in reasoning that competing candidate options require human operator review.")
        lines.append("2. SINGLE OPTION EVALUATION: When exactly 1 candidate option exists and the evidence supports it, return selected_candidate_index = 0, outcome = 'MATCHED', reconciled_amount = total matched source amount. If not supported, return selected_candidate_index = null, outcome = 'EXCEPTION'.")
        lines.append("3. OPTION ORDER HAS NO SEMANTIC MEANING. Option 0 is NEVER a default choice.")
        lines.append("4. Respect relationship direction: 1 source + multiple targets = 1:N; multiple sources + 1 target = N:1; 1 source + 1 target = 1:1.")
        lines.append("5. If selecting MATCHED, reconciled_amount must equal the total matched source amount.")
        lines.append("")
        if case.candidate_options and len(case.candidate_options) > 1:
            lines.append('Output JSON format:\n{"selected_candidate_index": null, "relationship_type": "1:1", "outcome": "EXCEPTION", "exception_type": "POSSIBLE_DUPLICATE", "severity": "MEDIUM", "flag_for_review": true, "reconciled_amount": "0.00", "reasoning": "...", "confidence": 0.9}')
        else:
            lines.append('Output JSON format:\n{"selected_candidate_index": 0 or null, "relationship_type": "1:1" or "1:N" or "N:1", "outcome": "MATCHED" or "EXCEPTION", "exception_type": null or "...", "severity": null or "...", "flag_for_review": true/false, "reconciled_amount": "5000.00", "reasoning": "...", "confidence": 0.0-1.0}')
        return "\n".join(lines)

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        s = text.strip()
        if s.startswith("```"):
            lines = s.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        return s

    def _normalize_exception_json(self, raw_json: str) -> str:
        s = self._strip_markdown_fences(raw_json)
        data = json.loads(s)
        if not isinstance(data, dict):
            raise ValueError(f"Expected JSON object, got {type(data).__name__}")
        
        # Normalize enums to uppercase
        ex_type = data.get("exception_type")
        data["exception_type"] = str(ex_type).upper() if ex_type is not None else None
        
        sev = data.get("severity")
        data["severity"] = str(sev).upper() if sev is not None else None

        data.setdefault("flag_for_review", False)
        data.setdefault("reasoning", "")
        data.setdefault("confidence", 0.5)
        return json.dumps(data)

    def _normalize_candidate_json(self, raw_json: str, case: ClassificationCase | None = None) -> str:
        s = self._strip_markdown_fences(raw_json)
        data = json.loads(s)
        if not isinstance(data, dict):
            raise ValueError(f"Expected JSON object, got {type(data).__name__}")

        # Normalize enums to uppercase
        ex_type = data.get("exception_type")
        data["exception_type"] = str(ex_type).upper() if ex_type is not None else None

        sev = data.get("severity")
        data["severity"] = str(sev).upper() if sev is not None else None

        if "outcome" in data and data["outcome"] is not None:
            data["outcome"] = str(data["outcome"]).upper()

        rel = data.get("relationship_type")
        data["relationship_type"] = str(rel).upper() if rel is not None else "1:1"

        data.setdefault("flag_for_review", False)
        data.setdefault("reasoning", "")
        data.setdefault("confidence", 0.5)

        # Normalize reconciled_amount
        amt = data.get("reconciled_amount")
        if isinstance(amt, (int, float)):
            data["reconciled_amount"] = str(amt)
        elif isinstance(amt, str) and amt.strip() and amt.strip().lower() != "null":
            match = re.search(r"[-+]?\d*\.?\d+", amt)
            data["reconciled_amount"] = match.group(0) if match else "0.00"
        else:
            # If omitted or None, calculate from selected option's source amounts if case is available
            idx = data.get("selected_candidate_index")
            if case and idx is not None and isinstance(idx, int) and case.candidate_options and 0 <= idx < len(case.candidate_options):
                opt = case.candidate_options[idx]
                amt_sum = sum(
                    case.source_amounts[case.source_record_ids.index(sid)]
                    for sid in opt.source_record_ids
                    if sid in case.source_record_ids
                )
                data["reconciled_amount"] = str(amt_sum)
            else:
                data["reconciled_amount"] = "0.00"

        return json.dumps(data)


def _build_system_prompt() -> str:
    return """You are a financial reconciliation exception classifier.

RULES:
- You MUST only use record IDs that appear in the supplied evidence.
- You MUST NOT fabricate transaction IDs, bank references, or any identifiers.
- You MUST NOT create N:M relationships.
- You MUST use only these relationship types: 1:1, 1:N, N:1.
- You MUST use only these exception types: SETTLEMENT_DELAY, FEE_DEDUCTION, ROUNDING_DIFFERENCE, PARTIAL_SETTLEMENT, SPLIT_SETTLEMENT, DUPLICATE, MISSING_RECORD, CURRENCY_MISMATCH, POSSIBLE_DUPLICATE, UNKNOWN.
- You MUST NOT override deterministic financial facts (amounts, currencies, dates).
- For CANDIDATE_SELECTION: You are selecting among candidate options. When candidate options are ambiguous (competing counterparties or 1:1 vs 1:N split settlement alternatives), return selected_candidate_index = null. Do not construct participant IDs. Do not combine records from different options.
- Output valid JSON conforming to the requested schema."""
