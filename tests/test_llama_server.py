"""Unit tests for LlamaServerProvider with mocked HTTP client.

These tests do NOT require llama-server to be running or a GPU.
"""

import asyncio
from decimal import Decimal
import json
from unittest.mock import patch, MagicMock
import httpx
import pytest

from eagle.agents._llama_server import LlamaServerProvider
from eagle.agents.classifier import AIExceptionClassifier
from eagle.agents.provider import create_provider
from eagle.core.config import Settings
from eagle.models.ai_contracts import (
    CandidateRelationshipOption,
    ClassificationCase,
    CandidateSelectionDecision,
    ExceptionClassificationDecision,
)
from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType
from eagle.models.evidence import CandidateRelationshipEvidence, EngineOutput


def _run_sync(coro):
    return asyncio.run(coro)


def _make_mock_response(status_code: int = 200, json_data: dict | None = None, text: str = "") -> httpx.Response:
    request = httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions")
    if json_data is not None:
        return httpx.Response(status_code=status_code, json=json_data, request=request)
    return httpx.Response(status_code=status_code, text=text, request=request)


def test_provider_factory_selects_llama_server():
    """Verify that create_provider returns LlamaServerProvider when AI_PROVIDER=llama_server."""
    settings = Settings(
        AI_PROVIDER="llama_server",
        AI_MODEL="test-model",
        LLAMA_SERVER_URL="http://127.0.0.1:8000",
    )
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = httpx.Response(200, json={"status": "ok"}, request=httpx.Request("GET", "http://127.0.0.1:8000/health"))
        provider = create_provider(settings)
        assert isinstance(provider, LlamaServerProvider)
        assert provider._base_url == "http://127.0.0.1:8000"
        assert provider._model == "test-model"


def test_llama_server_unavailable_raises_clear_error():
    """Verify that an unreachable llama-server raises a clear actionable RuntimeError on startup."""
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("Connection refused")):
        with pytest.raises(RuntimeError, match="llama-server is unavailable at http://127.0.0.1:8000"):
            LlamaServerProvider(base_url="http://127.0.0.1:8000", check_health=True)


def test_llama_server_successful_candidate_selection():
    """Verify successful structured candidate selection parsing from OpenAI-compatible response."""
    provider = LlamaServerProvider(base_url="http://127.0.0.1:8000", check_health=False)
    case = ClassificationCase(
        case_type="CANDIDATE_SELECTION",
        source_record_ids=["SRC-1"],
        committed_target_record_ids=[],
        candidate_options=[
            CandidateRelationshipOption(source_record_ids=["SRC-1"], target_record_ids=["TGT-A"]),
            CandidateRelationshipOption(source_record_ids=["SRC-1"], target_record_ids=["TGT-B"]),
        ],
        source_amounts=[Decimal("5000.00")],
        source_currencies=["INR"],
        target_amounts=[Decimal("5000.00"), Decimal("5000.00")],
        target_currencies=["INR", "INR"],
        source_transaction_dates=["2025-01-15"],
        target_settlement_dates=["2025-01-16", "2025-01-17"],
        evidence_summary="Test candidate selection",
    )

    mock_content = json.dumps({
        "selected_candidate_index": 1,
        "relationship_type": "1:1",
        "outcome": "MATCHED",
        "exception_type": None,
        "severity": None,
        "flag_for_review": False,
        "reconciled_amount": "5000.00 INR",
        "reasoning": "Selected option 1 due to matching date",
        "confidence": 0.95,
    })
    mock_resp_json = {
        "choices": [{"message": {"content": mock_content}}]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _make_mock_response(200, json_data=mock_resp_json)
        decision = _run_sync(provider.select_candidate(case))

        assert isinstance(decision, CandidateSelectionDecision)
        assert decision.selected_candidate_index == 1
        assert decision.relationship_type == "1:1"
        assert decision.outcome == "MATCHED"
        assert decision.reconciled_amount == "5000.00"
        assert decision.confidence == 0.95


def test_llama_server_selected_candidate_index_null():
    """Verify that selected_candidate_index=null is parsed cleanly as an abstention."""
    provider = LlamaServerProvider(base_url="http://127.0.0.1:8000", check_health=False)
    case = ClassificationCase(
        case_type="CANDIDATE_SELECTION",
        source_record_ids=["SRC-ORPHAN"],
        committed_target_record_ids=[],
        candidate_options=[
            CandidateRelationshipOption(source_record_ids=["SRC-ORPHAN"], target_record_ids=["TGT-DECOY"]),
        ],
        source_amounts=[Decimal("5000.00")],
        source_currencies=["INR"],
        target_amounts=[Decimal("5000.00")],
        target_currencies=["INR"],
        source_transaction_dates=["2025-01-15"],
        target_settlement_dates=["2025-01-18"],
        evidence_summary="Near duplicate / no match",
    )

    mock_content = json.dumps({
        "selected_candidate_index": None,
        "relationship_type": "1:1",
        "outcome": "EXCEPTION",
        "exception_type": "POSSIBLE_DUPLICATE",
        "severity": "MEDIUM",
        "flag_for_review": True,
        "reconciled_amount": "0.00",
        "reasoning": "No valid counterpart found in candidates",
        "confidence": 0.8,
    })
    mock_resp_json = {
        "choices": [{"message": {"content": mock_content}}]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _make_mock_response(200, json_data=mock_resp_json)
        decision = _run_sync(provider.select_candidate(case))

        assert decision.selected_candidate_index is None
        assert decision.outcome == "EXCEPTION"
        assert decision.exception_type == "POSSIBLE_DUPLICATE"
        assert decision.severity == "MEDIUM"
        assert decision.flag_for_review is True


def test_llama_server_malformed_model_output():
    """Verify that malformed model output raises an error resulting in classification failure."""
    provider = LlamaServerProvider(base_url="http://127.0.0.1:8000", check_health=False)
    case = ClassificationCase(
        case_type="CANDIDATE_SELECTION",
        source_record_ids=["SRC-1"],
        committed_target_record_ids=[],
        candidate_options=[
            CandidateRelationshipOption(source_record_ids=["SRC-1"], target_record_ids=["TGT-1"]),
        ],
        source_amounts=[Decimal("5000.00")],
        source_currencies=["INR"],
        target_amounts=[Decimal("5000.00")],
        target_currencies=["INR"],
        source_transaction_dates=["2025-01-15"],
        target_settlement_dates=["2025-01-16"],
        evidence_summary="Test malformed output",
    )

    mock_resp_json = {
        "choices": [{"message": {"content": "This is plain text and not JSON at all!"}}]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _make_mock_response(200, json_data=mock_resp_json)
        with pytest.raises(Exception):
            _run_sync(provider.select_candidate(case))


def test_llama_server_participant_ids_come_from_deterministic_option():
    """Verify that participant IDs come exclusively from the deterministic option, not model output."""
    import datetime
    provider = LlamaServerProvider(base_url="http://127.0.0.1:8000", check_health=False)
    classifier = AIExceptionClassifier(provider=provider, max_retries=0)

    src = CanonicalRecord(
        record_id="SRC-GENUINE",
        transaction_id="TXN-1",
        account_id="ACC",
        amount=Decimal("5000.00"),
        currency="INR",
        transaction_date=datetime.date(2025, 1, 15),
        settlement_date=datetime.date(2025, 1, 15),
        source="GATEWAY",
        source_reference="",
        counterparty="",
        status="SUCCESS",
        transaction_type="DEBIT",
    )
    tgt = CanonicalRecord(
        record_id="TGT-GENUINE",
        transaction_id="TXN-2",
        account_id="ACC",
        amount=Decimal("5000.00"),
        currency="INR",
        transaction_date=datetime.date(2025, 1, 16),
        settlement_date=datetime.date(2025, 1, 16),
        source="BANK",
        source_reference="",
        counterparty="",
        status="SUCCESS",
        transaction_type="CREDIT",
    )

    ev = CandidateRelationshipEvidence(
        candidate_options=[
            CandidateRelationshipOption(source_record_ids=["SRC-GENUINE"], target_record_ids=["TGT-GENUINE"]),
        ],
        relationship_context="Test context",
    )
    engine_output = EngineOutput(results=[], candidates=[ev])

    # Model returns index 0 (even if it tries to mention other IDs in reasoning)
    mock_content = json.dumps({
        "selected_candidate_index": 0,
        "relationship_type": "1:1",
        "outcome": "MATCHED",
        "reconciled_amount": "5000.00",
        "reasoning": "Claiming hallucinated IDs FABRICATED-1",
        "confidence": 0.9,
    })
    mock_resp_json = {
        "choices": [{"message": {"content": mock_content}}]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _make_mock_response(200, json_data=mock_resp_json)
        output = classifier.classify_all_sync(engine_output, [src], [tgt])

        assert len(output.classified_results) == 1
        res = output.classified_results[0]
        # IDs must strictly be the genuine deterministic IDs
        assert res.source_record_ids == ["SRC-GENUINE"]
        assert res.target_record_ids == ["TGT-GENUINE"]


def test_llama_server_exception_classification():
    """Verify exception classification parsing."""
    provider = LlamaServerProvider(base_url="http://127.0.0.1:8000", check_health=False)
    case = ClassificationCase(
        case_type="EXCEPTION_CLASSIFICATION",
        source_record_ids=["GTW-B08"],
        committed_target_record_ids=["BANK-B08"],
        candidate_options=None,
        committed_relationship_type="1:1",
        source_amounts=[Decimal("12000.00")],
        source_currencies=["INR"],
        target_amounts=[Decimal("12000.00")],
        target_currencies=["INR"],
        source_transaction_dates=["2025-01-15"],
        target_settlement_dates=["2025-01-25"],
        evidence_summary="10-day settlement delay",
    )

    mock_content = json.dumps({
        "exception_type": "SETTLEMENT_DELAY",
        "severity": "HIGH",
        "flag_for_review": True,
        "reasoning": "10-day delay exceeds normal threshold",
        "confidence": 0.95,
    })
    mock_resp_json = {
        "choices": [{"message": {"content": mock_content}}]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = _make_mock_response(200, json_data=mock_resp_json)
        decision = _run_sync(provider.classify_exception(case))

        assert isinstance(decision, ExceptionClassificationDecision)
        assert decision.exception_type == "SETTLEMENT_DELAY"
        assert decision.severity == "HIGH"
        assert decision.flag_for_review is True


def test_llama_server_candidate_prompt_contains_enriched_metadata():
    """Verify that _build_candidate_prompt formats transaction metadata, options, and instructions."""
    provider = LlamaServerProvider(base_url="http://127.0.0.1:8000", check_health=False)
    case = ClassificationCase(
        case_type="CANDIDATE_SELECTION",
        source_record_ids=["SRC-100"],
        committed_target_record_ids=[],
        candidate_options=[
            CandidateRelationshipOption(source_record_ids=["SRC-100"], target_record_ids=["TGT-A", "TGT-B"]),
            CandidateRelationshipOption(source_record_ids=["SRC-100"], target_record_ids=["TGT-C"]),
        ],
        source_amounts=[Decimal("10000.00")],
        source_currencies=["INR"],
        target_amounts=[Decimal("6000.00"), Decimal("4000.00"), Decimal("10000.00")],
        target_currencies=["INR", "INR", "INR"],
        source_transaction_dates=["2025-02-01"],
        target_settlement_dates=["2025-02-03", "2025-02-03", "2025-02-04"],
        evidence_summary=(
            "SOURCE RECORDS:\n- ID: SRC-100\n  Amount: 10000.00 INR\n  Reference: REF-SRC-100\n"
            "TARGET RECORDS:\n- ID: TGT-A\n  Amount: 6000.00 INR\n  Reference: REF-TGT-A\n"
            "- ID: TGT-B\n  Amount: 4000.00 INR\n  Reference: REF-TGT-B"
        ),
    )

    prompt = provider._build_candidate_prompt(case)

    assert "TRANSACTION METADATA:" in prompt
    assert "REF-SRC-100" in prompt
    assert "REF-TGT-A" in prompt
    assert "REF-TGT-B" in prompt
    assert "Option 0:" in prompt
    assert "Sources: ['SRC-100']" in prompt
    assert "Targets: ['TGT-A', 'TGT-B']" in prompt
    assert "Option 1:" in prompt
    assert "OPTION ORDER HAS NO SEMANTIC MEANING" in prompt
    assert "CRITICAL INSTRUCTIONS:" in prompt

