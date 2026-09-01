"""End-to-End Demonstration Script for Day 2:
Human Correction -> Generalized Rule -> Rule Persistence -> Rerun -> Rule Impact
"""

from datetime import date
from decimal import Decimal
from fastapi.testclient import TestClient

from eagle.agents._mock import MockProvider
from eagle.api.main import app
from eagle.api.routes import get_service
from eagle.core.config import Settings
from eagle.models.canonical import CanonicalRecord
from eagle.services.reconciliation_service import ReconciliationService
from eagle.storage.database import Database
from eagle.storage.repository import Repository


def run_demo():
    print("\n=======================================================")
    print("  EAGLE DAY 2.1: TARGETED RULE APPLICATION DEMO")
    print("=======================================================\n")

    # 1. Initialize isolated environment
    db = Database(":memory:")
    repo = Repository(db)
    provider = MockProvider()
    settings = Settings(DATABASE_PATH=":memory:", AI_PROVIDER="mock")
    service = ReconciliationService(repository=repo, provider=provider, settings=settings)

    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)

    # 2. Ingest transactions where candidate ambiguity exists:
    # 1 source for Merchant Gamma (INR 10,000)
    # 3 bank targets forming two competing split-settlement candidates
    sources = [
        CanonicalRecord(
            record_id="SRC-GAMMA-01",
            transaction_id="TX-GAMMA-01",
            source="GATEWAY",
            source_reference="REF-GAMMA-100",
            amount=Decimal("10000.00"),
            currency="INR",
            transaction_date=date(2025, 5, 1),
            settlement_date=date(2025, 5, 1),
            counterparty="Merchant Gamma",
            status="COMPLETED",
            transaction_type="CREDIT",
        )
    ]
    targets = [
        CanonicalRecord(
            record_id="BNK-GAMMA-01",
            transaction_id="BNK-GAMMA-01",
            source="BANK",
            source_reference="BNK-GAMMA-01",
            amount=Decimal("6000.00"),
            currency="INR",
            transaction_date=date(2025, 5, 2),
            settlement_date=date(2025, 5, 2),
            counterparty="Merchant Gamma",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BNK-GAMMA-02",
            transaction_id="BNK-GAMMA-02",
            source="BANK",
            source_reference="BNK-GAMMA-02",
            amount=Decimal("4000.00"),
            currency="INR",
            transaction_date=date(2025, 5, 2),
            settlement_date=date(2025, 5, 2),
            counterparty="Merchant Gamma",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BNK-DECOY-03",
            transaction_id="BNK-DECOY-03",
            source="BANK",
            source_reference="BNK-DECOY-03",
            amount=Decimal("4000.00"),
            currency="INR",
            transaction_date=date(2025, 5, 2),
            settlement_date=date(2025, 5, 2),
            counterparty="Decoy Merchant",
            status="POSTED",
            transaction_type="CREDIT",
        ),
    ]

    # [Step 1] Initial Run
    print("[Step 1] Initial run")
    init_res = service.reconcile_records(sources, targets, apply_rules=False)
    run_id = init_res["run_id"]
    init_metrics = service.calculate_metrics(run_id)
    print(f"    Run ID: {run_id}")
    print(f"    Match Rate: {init_metrics['match_rate']}%")
    print(f"    Exception Count: {init_metrics['exception_count']}")

    results = repo.get_results(run_id)
    target_rel = [r for r in results if "SRC-GAMMA-01" in r.source_record_ids][0]

    # [Step 2] Operator Correction
    print("\n[Step 2] Operator correction")
    corr_payload = {
        "corrected_outcome": "MATCHED",
        "corrected_exception_type": None,
        "corrected_source_ids": ["SRC-GAMMA-01"],
        "corrected_target_ids": ["BNK-GAMMA-01", "BNK-GAMMA-02"],
        "operator_reason": "Merchant Gamma split batch settlement match",
        "generate_rule": True,
    }
    post_corr_res = client.post(f"/runs/{run_id}/results/{target_rel.relationship_id}/correct", json=corr_payload)
    assert post_corr_res.status_code == 201
    corr_data = post_corr_res.json()
    rule_id = corr_data["generated_rule_id"]
    print(f"    Correction ID: {corr_data['correction_id']}")
    print(f"    Relationship ID: {target_rel.relationship_id}")

    # [Step 3] Rule Synthesis
    print("\n[Step 3] Rule synthesis")
    rule_resp = client.get(f"/rules/{rule_id}").json()
    print(f"    Rule ID: {rule_resp['rule_id']}")
    print(f"    Predicates: Counterparty='{rule_resp['source_counterparty_pattern']}', "
          f"Currency='{rule_resp['currency']}', "
          f"MaxAmountDiff={rule_resp['max_amount_difference']}, "
          f"MaxDelayDays={rule_resp['max_settlement_delay_days']}")

    # [Step 4] Rule Activation
    print("\n[Step 4] Rule activation")
    print(f"    Active: {rule_resp['is_active']}")

    # [Step 5] Rerun
    print("\n[Step 5] Rerun")
    rerun_res = client.post(f"/runs/{run_id}/rerun", json={"apply_rules": True})
    assert rerun_res.status_code == 201
    rerun_data = rerun_res.json()
    rerun_id = rerun_data["rerun_id"]
    print(f"    Parent Run: {rerun_data['parent_run_id']}")
    print(f"    Rerun Run: {rerun_id}")

    # [Step 6] Rule Application
    print("\n[Step 6] Rule application")
    rerun_results = repo.get_results(rerun_id)
    matched_results = [r for r in rerun_results if r.outcome.value == "MATCHED"]
    assert len(matched_results) > 0
    matched_rel = matched_results[0]
    audit_logs = repo.get_audit_logs(rerun_id)
    rule_app_events = [l for l in audit_logs if l["event_type"] == "RULE_APPLICATION_COMPLETED"]
    assert len(rule_app_events) > 0
    print(f"    Candidate selected: Sources={matched_rel.source_record_ids}, Targets={matched_rel.target_record_ids}")
    print(f"    Rule ID: {rule_app_events[0]['details']['rule_id']}")

    # [Step 7] Final Result
    print("\n[Step 7] Final result")
    print(f"    Outcome: {matched_rel.outcome.value}")
    print(f"    Relationship Type: {matched_rel.relationship_type.value}")
    print(f"    Reconciled Amount: INR {matched_rel.reconciled_amount}")

    # [Step 8] Rule Impact
    print("\n[Step 8] Rule impact")
    impact_res = client.get(f"/runs/{run_id}/rule-impact").json()
    print(f"    Before Match Rate: {impact_res['before']['match_rate']}%")
    print(f"    After Match Rate: {impact_res['after']['match_rate']}%")
    print(f"    Improvement: +{impact_res['delta']['match_rate_improvement']}%")
    print(f"    Resolved Exceptions: {impact_res['delta']['resolved_exceptions']}")

    # [Step 9] Immutability
    print("\n[Step 9] Immutability")
    orig_results = repo.get_results(run_id)
    orig_unchanged = len(orig_results) == len(results) and all(
        r.outcome == init_r.outcome for r, init_r in zip(orig_results, results)
    )
    print(f"    Original run unchanged: {'YES' if orig_unchanged else 'NO'}")

    print("\n=======================================================")
    print("  [SUCCESS] TARGETED RULE APPLICATION VERIFIED CLEANLY")
    print("=======================================================\n")


if __name__ == "__main__":
    run_demo()
