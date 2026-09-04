"""Comprehensive End-to-End Integration Test Suite for Eagle's Learning Loop:
Human Correction -> Generalized Rule Synthesis -> Rule Activation -> Rerun -> RAG Indexing -> Scoped Ask Eagle.

Proves the complete architectural learning loop:
1. Ambiguous transaction is flagged for review.
2. Operator submits a human correction.
3. Generalized (non-ID memorizing) rule is synthesized and activated globally.
4. Rerun evaluates the active rule and achieves 100% match rate.
5. Generalized rule resolves unseen records with different IDs.
6. Rerun evidence is indexed into ChromaDB.
7. Scoped Ask Eagle retrieves operational evidence with strict cross-run isolation.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import pytest
from fastapi.testclient import TestClient

from eagle.agents._mock import MockProvider
from eagle.api.main import app
from eagle.api.routes import get_service
from eagle.core.config import Settings
from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType
from eagle.models.evidence import CandidateRelationshipEvidence, CandidateRelationshipOption, EngineOutput
from eagle.models.reconciliation import ReconciliationResult
from eagle.rag.models import QARequest
from eagle.rag.qa_agent import EagleQAAgent, INSUFFICIENT_EVIDENCE_MSG
from eagle.rag.qa_provider import MockQAProvider
from eagle.rag.vector_store import EagleVectorStore
from eagle.rules.models import OperatorCorrection, ReconciliationRule
from eagle.rules.rule_engine import RuleEngine
from eagle.rules.rule_synthesizer import RuleSynthesizer
from eagle.services.reconciliation_service import ReconciliationService
from eagle.storage.database import Database
from eagle.storage.repository import Repository


# -----------------------------------------------------------------------------
# Test Fixtures & Isolated Setup
# -----------------------------------------------------------------------------

@pytest.fixture
def isolated_db():
    """Create an isolated in-memory SQLite database."""
    db = Database(":memory:")
    yield db
    db.close()


@pytest.fixture
def isolated_repo(isolated_db):
    """Repository backed by isolated in-memory SQLite."""
    return Repository(isolated_db)


@pytest.fixture
def isolated_vector_store():
    """Isolated In-Memory ChromaDB vector store."""
    import chromadb
    client = chromadb.EphemeralClient()
    return EagleVectorStore(chroma_path=":memory:", client=client)


@pytest.fixture
def learning_service(isolated_repo, isolated_vector_store):
    """ReconciliationService with isolated repository, vector store, and mock providers."""
    provider = MockProvider()
    settings = Settings(DATABASE_PATH=":memory:", AI_PROVIDER="mock")
    service = ReconciliationService(
        repository=isolated_repo,
        provider=provider,
        settings=settings,
    )
    service.vector_store = isolated_vector_store
    service.qa_agent = EagleQAAgent(
        vector_store=isolated_vector_store,
        qa_provider=MockQAProvider(),
    )
    return service


@pytest.fixture
def api_client(learning_service):
    """FastAPI TestClient with isolated service dependency override."""
    app.dependency_overrides[get_service] = lambda: learning_service
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def make_orbit_dataset():
    """Construct the 6 canonical Orbit dataset records (2 Gateway + 4 Bank)."""
    gtw_01 = CanonicalRecord(
        record_id="SRC-ORBIT-001",
        transaction_id="SRC-ORBIT-001",
        source="GATEWAY",
        source_reference="ORBIT-2026-001",
        amount=Decimal("18500.00"),
        currency="INR",
        transaction_date=date(2026, 9, 4),
        settlement_date=date(2026, 9, 4),
        counterparty="Merchant-Orbit",
        status="COMPLETED",
        transaction_type="PAYMENT",
    )
    gtw_02 = CanonicalRecord(
        record_id="SRC-ORBIT-002",
        transaction_id="SRC-ORBIT-002",
        source="GATEWAY",
        source_reference="ORBIT-2026-002",
        amount=Decimal("7500.00"),
        currency="INR",
        transaction_date=date(2026, 9, 4),
        settlement_date=date(2026, 9, 4),
        counterparty="Merchant-Nova",
        status="COMPLETED",
        transaction_type="PAYMENT",
    )
    bnk_01 = CanonicalRecord(
        record_id="BANK-ORBIT-01",
        transaction_id="BANK-ORBIT-01",
        source="BANK",
        source_reference="ORBIT-2026-001",
        amount=Decimal("11000.00"),
        currency="INR",
        transaction_date=date(2026, 9, 4),
        settlement_date=date(2026, 9, 4),
        counterparty="Merchant-Orbit",
        status="POSTED",
        transaction_type="CREDIT",
    )
    bnk_02 = CanonicalRecord(
        record_id="BANK-ORBIT-02",
        transaction_id="BANK-ORBIT-02",
        source="BANK",
        source_reference="ORBIT-2026-001",
        amount=Decimal("7500.00"),
        currency="INR",
        transaction_date=date(2026, 9, 4),
        settlement_date=date(2026, 9, 4),
        counterparty="Merchant-Orbit",
        status="POSTED",
        transaction_type="CREDIT",
    )
    bnk_decoy = CanonicalRecord(
        record_id="BANK-DECOY-01",
        transaction_id="BANK-DECOY-01",
        source="BANK",
        source_reference="ORBIT-2026-001",
        amount=Decimal("18500.00"),
        currency="INR",
        transaction_date=date(2026, 9, 4),
        settlement_date=date(2026, 9, 4),
        counterparty="Wrong-Merchant",
        status="POSTED",
        transaction_type="CREDIT",
    )
    bnk_nova = CanonicalRecord(
        record_id="BANK-NOVA",
        transaction_id="BANK-NOVA",
        source="BANK",
        source_reference="ORBIT-2026-002",
        amount=Decimal("7500.00"),
        currency="INR",
        transaction_date=date(2026, 9, 4),
        settlement_date=date(2026, 9, 4),
        counterparty="Merchant-Nova",
        status="POSTED",
        transaction_type="CREDIT",
    )
    return [gtw_01, gtw_02], [bnk_01, bnk_02, bnk_decoy, bnk_nova]


# -----------------------------------------------------------------------------
# End-to-End Learning Loop Integration Test
# -----------------------------------------------------------------------------

def test_end_to_end_learning_loop_lifecycle(learning_service, api_client):
    """Full End-to-End Test:
    Baseline Run -> Ambiguity -> Human Correction -> Rule Synthesis -> Activation ->
    Rerun -> 100% Match -> Generalization Proof -> ChromaDB Indexing -> Scoped Ask Eagle.
    """
    sources, targets = make_orbit_dataset()
    base_run_id = "RUN-ORBIT-BASELINE-01"

    # =========================================================================
    # Step 1: Execute Baseline Run
    # =========================================================================
    base_res = learning_service.reconcile_records(sources, targets, run_id=base_run_id, apply_rules=True)
    assert base_res["status"] == "COMPLETED"

    base_metrics = learning_service.calculate_metrics(base_run_id)
    assert base_metrics["total_records"] == 6
    assert base_metrics["source_count"] == 2
    assert base_metrics["target_count"] == 4
    assert base_metrics["matched_count"] == 1
    assert base_metrics["match_rate"] == 50.0  # 1 of 2 source records matched

    results = learning_service.repository.get_results(base_run_id)
    assert len(results) >= 2

    # Nova is matched
    nova_res = next(r for r in results if "SRC-ORBIT-002" in r.source_record_ids)
    assert nova_res.outcome == ReconciliationOutcome.MATCHED
    assert nova_res.target_record_ids == ["BANK-NOVA"]
    assert nova_res.reconciled_amount == Decimal("7500.00")

    # Orbit 18,500 is unresolved exception / candidate
    orbit_res = next(r for r in results if "SRC-ORBIT-001" in r.source_record_ids)
    assert orbit_res.outcome == ReconciliationOutcome.EXCEPTION
    ambiguous_rel_id = orbit_res.relationship_id

    # =========================================================================
    # Step 2: Submit Human Correction via API
    # =========================================================================
    corr_payload = {
        "corrected_source_ids": ["SRC-ORBIT-001"],
        "corrected_target_ids": ["BANK-ORBIT-01", "BANK-ORBIT-02"],
        "corrected_outcome": "MATCHED",
        "corrected_exception_type": None,
        "operator_reason": "Split settlement: Merchant-Orbit payment ₹18,500 settled via ₹11,000 + ₹7,500",
        "generate_rule": True,
    }
    corr_response = api_client.post(
        f"/runs/{base_run_id}/results/{ambiguous_rel_id}/correct",
        json=corr_payload,
    )
    assert corr_response.status_code == 201
    corr_data = corr_response.json()
    assert corr_data["status"] == "COMMITTED"
    assert corr_data["corrected_source_ids"] == ["SRC-ORBIT-001"]
    assert corr_data["corrected_target_ids"] == ["BANK-ORBIT-01", "BANK-ORBIT-02"]
    assert corr_data["generated_rule_id"] is not None

    generated_rule_id = corr_data["generated_rule_id"]

    # Verify baseline run results remained immutable
    base_res_after_corr = learning_service.repository.get_results(base_run_id)
    orig_orbit_after = next(r for r in base_res_after_corr if r.relationship_id == ambiguous_rel_id)
    assert orig_orbit_after.outcome == ReconciliationOutcome.EXCEPTION

    # =========================================================================
    # Step 3: Verify Synthesized Rule is Generalized (Zero ID Memorization)
    # =========================================================================
    rule_resp = api_client.get(f"/rules/{generated_rule_id}")
    assert rule_resp.status_code == 200
    rule_data = rule_resp.json()

    assert rule_data["rule_id"] == generated_rule_id
    assert rule_data["is_active"] is True
    assert rule_data["source_counterparty_pattern"] == "Merchant-Orbit"
    assert rule_data["reference_prefix"] == "ORBIT-2026-"
    assert rule_data["currency"] == "INR"
    assert Decimal(str(rule_data["max_amount_difference"])) == Decimal("0.00")
    assert rule_data["max_settlement_delay_days"] == 0
    assert rule_data["resulting_outcome"] == "MATCHED"

    # Explicit Safety Check: Assert rule does NOT contain any exact record IDs as predicates
    forbidden_ids = {"SRC-ORBIT-001", "SRC-ORBIT-002", "BANK-ORBIT-01", "BANK-ORBIT-02", "BANK-DECOY-01", "BANK-NOVA"}
    assert rule_data["source_counterparty_pattern"] not in forbidden_ids
    assert rule_data["reference_prefix"] not in forbidden_ids

    # =========================================================================
    # Step 4: Execute Rerun via API
    # =========================================================================
    rerun_resp = api_client.post(f"/runs/{base_run_id}/rerun", json={"apply_rules": True})
    assert rerun_resp.status_code == 201
    rerun_data = rerun_resp.json()

    rerun_id = rerun_data["rerun_id"]
    assert rerun_id.startswith(f"{base_run_id}-RERUN-")
    assert rerun_data["status"] == "COMPLETED"

    # Verify Rerun Metrics reached 100%
    summary = rerun_data["summary"]
    assert summary["matched_count"] == 2
    assert summary["exception_count"] == 0
    assert summary["unresolved_count"] == 0
    assert summary["match_rate"] == 100.0
    assert summary["value_weighted_match_rate"] == 100.0
    assert summary["total_reconciled_amount"] == "26000.00"

    # Verify exact final relationships
    rerun_results = learning_service.repository.get_results(rerun_id)
    assert len(rerun_results) == 2

    # Relationship 1: Nova 1:1
    nova_match = next(r for r in rerun_results if "SRC-ORBIT-002" in r.source_record_ids)
    assert nova_match.outcome == ReconciliationOutcome.MATCHED
    assert nova_match.target_record_ids == ["BANK-NOVA"]
    assert nova_match.reconciled_amount == Decimal("7500.00")

    # Relationship 2: Orbit 1:N resolved by learned rule
    orbit_match = next(r for r in rerun_results if "SRC-ORBIT-001" in r.source_record_ids)
    assert orbit_match.outcome == ReconciliationOutcome.MATCHED
    assert set(orbit_match.target_record_ids) == {"BANK-ORBIT-01", "BANK-ORBIT-02"}
    assert orbit_match.relationship_type == RelationshipType.ONE_TO_MANY
    assert orbit_match.reconciled_amount == Decimal("18500.00")

    # Decoy was NOT selected
    assert "BANK-DECOY-01" not in orbit_match.target_record_ids

    # =========================================================================
    # Step 5: Verify Rule Impact Before/After Comparison
    # =========================================================================
    impact_resp = api_client.get(f"/runs/{rerun_id}/rule-impact")
    assert impact_resp.status_code == 200
    impact_data = impact_resp.json()

    assert impact_data["has_rerun"] is True
    assert impact_data["before"]["match_rate"] == 50.0
    assert impact_data["after"]["match_rate"] == 100.0
    assert impact_data["delta"]["match_rate_improvement"] == 50.0
    assert impact_data["delta"]["resolved_exceptions"] == 1

    # =========================================================================
    # Step 6: Prove Generalization on Completely New Record IDs
    # =========================================================================
    new_src = [
        CanonicalRecord(
            record_id="SRC-ORBIT-UNSEEN-99",
            transaction_id="SRC-ORBIT-UNSEEN-99",
            source="GATEWAY",
            source_reference="ORBIT-2026-999",
            amount=Decimal("18500.00"),
            currency="INR",
            transaction_date=date(2026, 9, 10),
            settlement_date=date(2026, 9, 10),
            counterparty="Merchant-Orbit",
            status="COMPLETED",
            transaction_type="PAYMENT",
        )
    ]
    new_tgt = [
        CanonicalRecord(
            record_id="BANK-ORBIT-UNSEEN-A",
            transaction_id="BANK-ORBIT-UNSEEN-A",
            source="BANK",
            source_reference="ORBIT-2026-999",
            amount=Decimal("11000.00"),
            currency="INR",
            transaction_date=date(2026, 9, 10),
            settlement_date=date(2026, 9, 10),
            counterparty="Merchant-Orbit",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BANK-ORBIT-UNSEEN-B",
            transaction_id="BANK-ORBIT-UNSEEN-B",
            source="BANK",
            source_reference="ORBIT-2026-999",
            amount=Decimal("7500.00"),
            currency="INR",
            transaction_date=date(2026, 9, 10),
            settlement_date=date(2026, 9, 10),
            counterparty="Merchant-Orbit",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BANK-DECOY-UNSEEN",
            transaction_id="BANK-DECOY-UNSEEN",
            source="BANK",
            source_reference="ORBIT-2026-999",
            amount=Decimal("18500.00"),
            currency="INR",
            transaction_date=date(2026, 9, 10),
            settlement_date=date(2026, 9, 10),
            counterparty="Wrong-Merchant",
            status="POSTED",
            transaction_type="CREDIT",
        ),
    ]

    new_run_id = "RUN-ORBIT-UNSEEN-01"
    new_res = learning_service.reconcile_records(new_src, new_tgt, run_id=new_run_id, apply_rules=True)
    assert new_res["status"] == "COMPLETED"

    new_results = learning_service.repository.get_results(new_run_id)
    assert len(new_results) == 1
    assert new_results[0].outcome == ReconciliationOutcome.MATCHED
    assert new_results[0].source_record_ids == ["SRC-ORBIT-UNSEEN-99"]
    assert set(new_results[0].target_record_ids) == {"BANK-ORBIT-UNSEEN-A", "BANK-ORBIT-UNSEEN-B"}
    assert new_results[0].reconciled_amount == Decimal("18500.00")

    # =========================================================================
    # Step 7: Verify RAG ChromaDB Indexing & Scoped Ask Eagle
    # =========================================================================
    # Index rerun
    indexed_count = learning_service.index_run(rerun_id)
    assert indexed_count > 0

    # Test Idempotent repeated indexing
    repeated_count = learning_service.index_run(rerun_id)
    assert repeated_count == indexed_count

    # Ask Eagle: Question regarding the learned rule resolution
    qa_resp_1 = api_client.post(
        f"/runs/{rerun_id}/qa",
        json={"question": "What rule resolved the ₹18,500 Orbit transaction in this run?"},
    )
    assert qa_resp_1.status_code == 200
    qa_data_1 = qa_resp_1.json()
    assert qa_data_1["has_sufficient_evidence"] is True
    assert len(qa_data_1["sources"]) > 0

    # Verify rule or result is cited in sources
    cited_types = {s["document_type"] for s in qa_data_1["sources"]}
    assert ("RULE" in cited_types) or ("RESULT" in cited_types)

    # =========================================================================
    # Step 8: Verify Run-Scope Isolation against Unrelated Cross-Run Leakage
    # =========================================================================
    unrelated_run_id = "RUN-UNRELATED-ZEBRA"
    unrelated_src = [
        CanonicalRecord(
            record_id="SRC-ZEBRA-01",
            transaction_id="SRC-ZEBRA-01",
            source="GATEWAY",
            source_reference="ZEBRA-REF-99",
            amount=Decimal("9999.00"),
            currency="INR",
            transaction_date=date(2026, 9, 1),
            settlement_date=date(2026, 9, 1),
            counterparty="Merchant-Zebra-Unique",
            status="COMPLETED",
            transaction_type="PAYMENT",
        )
    ]
    unrelated_tgt = [
        CanonicalRecord(
            record_id="BANK-ZEBRA-01",
            transaction_id="BANK-ZEBRA-01",
            source="BANK",
            source_reference="ZEBRA-REF-99",
            amount=Decimal("9999.00"),
            currency="INR",
            transaction_date=date(2026, 9, 1),
            settlement_date=date(2026, 9, 1),
            counterparty="Merchant-Zebra-Unique",
            status="POSTED",
            transaction_type="CREDIT",
        )
    ]
    learning_service.reconcile_records(unrelated_src, unrelated_tgt, run_id=unrelated_run_id, apply_rules=False)
    learning_service.index_run(unrelated_run_id)

    # Scoped query to rerun_id must NOT retrieve Zebra RUN documents
    qa_resp_scoped = api_client.post(
        f"/runs/{rerun_id}/qa",
        json={"question": "What happened with Merchant-Zebra-Unique?"},
    )
    assert qa_resp_scoped.status_code == 200
    qa_data_scoped = qa_resp_scoped.json()

    # None of the cited sources may carry unrelated_run_id
    for s in qa_data_scoped["sources"]:
        assert s["run_id"] != unrelated_run_id


# -----------------------------------------------------------------------------
# Detailed Specific Invariant Tests (Phase 12)
# -----------------------------------------------------------------------------

def test_invariant_a_correction_does_not_mutate_reconciliation_history(learning_service, api_client):
    """INVARIANT A: Submitting a correction creates an append-only record without modifying original results."""
    sources, targets = make_orbit_dataset()
    run_id = "RUN-INV-A"
    learning_service.reconcile_records(sources, targets, run_id=run_id, apply_rules=False)

    results_before = learning_service.repository.get_results(run_id)
    orbit_res = next(r for r in results_before if "SRC-ORBIT-001" in r.source_record_ids)
    assert orbit_res.outcome == ReconciliationOutcome.EXCEPTION

    # Submit correction
    corr_payload = {
        "corrected_source_ids": ["SRC-ORBIT-001"],
        "corrected_target_ids": ["BANK-ORBIT-01", "BANK-ORBIT-02"],
        "corrected_outcome": "MATCHED",
        "operator_reason": "Operator verification",
        "generate_rule": False,
    }
    resp = api_client.post(f"/runs/{run_id}/results/{orbit_res.relationship_id}/correct", json=corr_payload)
    assert resp.status_code == 201

    # Original result is still EXCEPTION in database
    results_after = learning_service.repository.get_results(run_id)
    orbit_res_after = next(r for r in results_after if "SRC-ORBIT-001" in r.source_record_ids)
    assert orbit_res_after.outcome == ReconciliationOutcome.EXCEPTION


def test_invariant_b_c_rule_synthesis_generalized_and_non_memorizing():
    """INVARIANTS B & C: RuleSynthesizer derives generalized predicates and strictly forbids ID memorization."""
    corr = OperatorCorrection(
        correction_id="CORR-TEST-BC",
        run_id="RUN-BC",
        relationship_id="REL-BC",
        original_outcome="EXCEPTION",
        original_source_ids=["SRC-ORBIT-001"],
        original_target_ids=[],
        corrected_outcome="MATCHED",
        corrected_source_ids=["SRC-ORBIT-001"],
        corrected_target_ids=["BANK-ORBIT-01", "BANK-ORBIT-02"],
        operator_reason="Verified split settlement pattern",
        created_at="2026-09-04T12:00:00Z",
    )
    sources, targets = make_orbit_dataset()

    rule = RuleSynthesizer.synthesize(
        correction=corr,
        source_records=sources,
        target_records=targets,
    )

    # Invariant B: Generalized predicates formed
    assert rule.source_counterparty_pattern == "Merchant-Orbit"
    assert rule.reference_prefix == "ORBIT-2026-"
    assert rule.currency == "INR"
    assert rule.max_amount_difference == Decimal("0.00")
    assert rule.max_settlement_delay_days == 0
    assert rule.resulting_outcome == "MATCHED"

    # Invariant C: Record IDs are NOT embedded
    record_ids = {"SRC-ORBIT-001", "BANK-ORBIT-01", "BANK-ORBIT-02"}
    assert rule.source_counterparty_pattern not in record_ids
    assert rule.reference_prefix not in record_ids


def test_invariant_d_rule_toggle_persistence(learning_service, api_client):
    """INVARIANT D: Rule toggle deactivates and reactivates rule persistently."""
    rule = ReconciliationRule(
        rule_id="RULE-TOGGLE-TEST",
        name="Test Toggle Rule",
        description="Test toggle",
        source_counterparty_pattern="Merchant-Orbit",
        resulting_outcome="MATCHED",
        confidence=1.0,
        is_active=True,
        created_at="2026-09-04T12:00:00Z",
    )
    learning_service.repository.save_rule(rule)

    # Deactivate
    resp_off = api_client.post(f"/rules/{rule.rule_id}/toggle", json={"is_active": False})
    assert resp_off.status_code == 200
    assert resp_off.json()["is_active"] is False

    active_rules = learning_service.repository.get_rules(active_only=True)
    assert not any(r.rule_id == rule.rule_id for r in active_rules)

    # Reactivate
    resp_on = api_client.post(f"/rules/{rule.rule_id}/toggle", json={"is_active": True})
    assert resp_on.status_code == 200
    assert resp_on.json()["is_active"] is True

    active_rules_2 = learning_service.repository.get_rules(active_only=True)
    assert any(r.rule_id == rule.rule_id for r in active_rules_2)


def test_invariant_g_h_unrelated_records_and_decoy_not_affected():
    """INVARIANTS G & H: Active rule matches only the legitimate option and rejects decoy and unrelated items."""
    sources, targets = make_orbit_dataset()

    rule = ReconciliationRule(
        rule_id="RULE-DEC-TEST",
        name="Orbit 1:N Rule",
        description="Matches Merchant-Orbit split payments",
        source_counterparty_pattern="Merchant-Orbit",
        reference_prefix="ORBIT-2026-",
        currency="INR",
        max_amount_difference=Decimal("0.00"),
        max_settlement_delay_days=0,
        resulting_outcome="MATCHED",
        confidence=1.0,
        is_active=True,
        created_at="2026-09-04T12:00:00Z",
    )

    # Candidate pool containing legitimate 1:N option and Decoy 1:1 option
    cand_pool = CandidateRelationshipEvidence(
        candidate_options=[
            CandidateRelationshipOption(
                source_record_ids=["SRC-ORBIT-001"],
                target_record_ids=["BANK-ORBIT-01", "BANK-ORBIT-02"],
            ),
            CandidateRelationshipOption(
                source_record_ids=["SRC-ORBIT-001"],
                target_record_ids=["BANK-DECOY-01"],
            ),
        ],
        relationship_context="Split vs Decoy ambiguity",
    )

    engine_out = EngineOutput(
        results=[],
        candidates=[cand_pool],
    )

    rule_results, remaining_candidates, events = RuleEngine.evaluate(
        engine_output=engine_out,
        source_records=sources,
        target_records=targets,
        active_rules=[rule],
    )

    # Legitimate 1:N option is committed
    assert len(rule_results) == 1
    assert rule_results[0].source_record_ids == ["SRC-ORBIT-001"]
    assert set(rule_results[0].target_record_ids) == {"BANK-ORBIT-01", "BANK-ORBIT-02"}
    assert rule_results[0].outcome == ReconciliationOutcome.MATCHED

    # Decoy was rejected and remaining candidates is empty
    assert len(remaining_candidates) == 0
    assert not any("BANK-DECOY-01" in r.target_record_ids for r in rule_results)


def test_invariant_e_f_rerun_uses_active_rules_and_reproduces_1_to_n(learning_service, api_client):
    """INVARIANTS E & F: Rerun loads active global rules and faithfully reproduces 1:N split matches."""
    sources, targets = make_orbit_dataset()
    run_id = "RUN-INV-EF"
    learning_service.reconcile_records(sources, targets, run_id=run_id, apply_rules=False)

    # Save active 1:N rule
    rule = ReconciliationRule(
        rule_id="RULE-INV-EF",
        name="Orbit 1:N Rule",
        description="Matches Merchant-Orbit split payments",
        source_counterparty_pattern="Merchant-Orbit",
        reference_prefix="ORBIT-2026-",
        currency="INR",
        max_amount_difference=Decimal("0.00"),
        max_settlement_delay_days=0,
        resulting_outcome="MATCHED",
        confidence=1.0,
        is_active=True,
        created_at="2026-09-04T12:00:00Z",
    )
    learning_service.repository.save_rule(rule)

    # Execute Rerun
    resp = api_client.post(f"/runs/{run_id}/rerun", json={"apply_rules": True})
    assert resp.status_code == 201
    rerun_data = resp.json()
    rerun_id = rerun_data["rerun_id"]

    rerun_results = learning_service.repository.get_results(rerun_id)
    orbit_match = next(r for r in rerun_results if "SRC-ORBIT-001" in r.source_record_ids)
    assert orbit_match.outcome == ReconciliationOutcome.MATCHED
    assert set(orbit_match.target_record_ids) == {"BANK-ORBIT-01", "BANK-ORBIT-02"}
    assert orbit_match.relationship_type == RelationshipType.ONE_TO_MANY
    assert orbit_match.reconciled_amount == Decimal("18500.00")


def test_invariant_j_k_l_m_rag_indexing_scoping_idempotency(learning_service, api_client):
    """INVARIANTS J, K, L, M: Rerun indexing, global rule retrieval, cross-run scoping, and idempotency."""
    sources, targets = make_orbit_dataset()
    run_id_1 = "RUN-RAG-01"
    run_id_2 = "RUN-RAG-02"

    learning_service.reconcile_records(sources, targets, run_id=run_id_1, apply_rules=False)
    learning_service.reconcile_records(sources, targets, run_id=run_id_2, apply_rules=False)

    # Save a global rule
    rule = ReconciliationRule(
        rule_id="RULE-RAG-GLOBAL",
        name="Global Orbit Rule",
        description="Global Orbit rule description",
        source_counterparty_pattern="Merchant-Orbit",
        resulting_outcome="MATCHED",
        confidence=1.0,
        is_active=True,
        created_at="2026-09-04T12:00:00Z",
    )
    learning_service.repository.save_rule(rule)

    # Invariant J: Index run 1
    count_1 = learning_service.index_run(run_id_1)
    assert count_1 > 0

    # Invariant M: Repeated indexing does not inflate doc count
    total_before = learning_service.vector_store._collection.count()
    count_repeat = learning_service.index_run(run_id_1)
    total_after = learning_service.vector_store._collection.count()
    assert total_after == total_before
    assert count_repeat == count_1

    # Index run 2
    learning_service.index_run(run_id_2)

    # Invariant K & L: Scoped search for run 1 retrieves run 1 docs + global rules, but NEVER run 2 docs
    search_res = learning_service.vector_store.search(
        query="reconciliation result",
        run_id=run_id_1,
        limit=20,
    )
    assert len(search_res) > 0
    for r in search_res:
        meta = r.metadata
        scope = meta.get("knowledge_scope")
        doc_run_id = meta.get("run_id")
        if scope == "RUN":
            assert doc_run_id == run_id_1
        elif scope == "GLOBAL":
            assert doc_run_id is None or doc_run_id == ""

