"""Test complete end-to-end flow with candidate pool ambiguity resolution."""

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

def run_test():
    db = Database(":memory:")
    repo = Repository(db)
    provider = MockProvider()
    settings = Settings(DATABASE_PATH=":memory:", AI_PROVIDER="mock")
    service = ReconciliationService(repository=repo, provider=provider, settings=settings)

    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)

    # 1 Source, 3 Targets: Ambiguous 1:N split settlement
    # T-1 + T-2 = Merchant Agg (Target match)
    # T-1 + T-3 = Decoy with Other Merchant
    s1 = CanonicalRecord(
        record_id="S-1", transaction_id="S-1", source="GATEWAY", source_reference="REF-AGG",
        amount=Decimal("10000.00"), currency="INR", transaction_date=date(2025, 1, 1),
        settlement_date=date(2025, 1, 1), counterparty="Merchant Agg", status="COMPLETED", transaction_type="CREDIT"
    )
    t1 = CanonicalRecord(
        record_id="T-1", transaction_id="T-1", source="BANK", source_reference="BNK-1",
        amount=Decimal("6000.00"), currency="INR", transaction_date=date(2025, 1, 2),
        settlement_date=date(2025, 1, 2), counterparty="Merchant Agg", status="POSTED", transaction_type="CREDIT"
    )
    t2 = CanonicalRecord(
        record_id="T-2", transaction_id="T-2", source="BANK", source_reference="BNK-2",
        amount=Decimal("4000.00"), currency="INR", transaction_date=date(2025, 1, 2),
        settlement_date=date(2025, 1, 2), counterparty="Merchant Agg", status="POSTED", transaction_type="CREDIT"
    )
    t3 = CanonicalRecord(
        record_id="T-3", transaction_id="T-3", source="BANK", source_reference="BNK-3",
        amount=Decimal("4000.00"), currency="INR", transaction_date=date(2025, 1, 2),
        settlement_date=date(2025, 1, 2), counterparty="Other Merchant", status="POSTED", transaction_type="CREDIT"
    )

    print("[Step 1] Initial Run without rules...")
    init_res = service.reconcile_records([s1], [t1, t2, t3], apply_rules=False)
    run_id = init_res["run_id"]
    init_metrics = service.calculate_metrics(run_id)
    print(f"  Init Run: {run_id}")
    print(f"  Init Metrics: {init_metrics}")

    results = repo.get_results(run_id)
    print(f"  Init Results count: {len(results)}")
    for r in results:
        print(f"    Result: {r.relationship_id}, outcome={r.outcome}, ex={r.exception_type}, src={r.source_record_ids}, tgt={r.target_record_ids}")

    # Pick the relationship with S-1
    target_rel = [r for r in results if "S-1" in r.source_record_ids][0]

    print("\n[Step 2] Operator Submits Correction with generate_rule=True...")
    corr_payload = {
        "corrected_outcome": "MATCHED",
        "corrected_exception_type": None,
        "corrected_source_ids": ["S-1"],
        "corrected_target_ids": ["T-1", "T-2"],
        "operator_reason": "Merchant Agg split settlement match",
        "generate_rule": True,
    }
    post_corr = client.post(f"/runs/{run_id}/results/{target_rel.relationship_id}/correct", json=corr_payload)
    assert post_corr.status_code == 201
    corr_data = post_corr.json()
    rule_id = corr_data["generated_rule_id"]
    print(f"  Correction ID: {corr_data['correction_id']}")
    print(f"  Rule ID: {rule_id}")

    rule_obj = repo.get_rule(rule_id)
    print(f"  Rule: cp={rule_obj.source_counterparty_pattern}, diff={rule_obj.max_amount_difference}, delay={rule_obj.max_settlement_delay_days}")

    print("\n[Step 3] Rerun with apply_rules=True...")
    rerun_post = client.post(f"/runs/{run_id}/rerun", json={"apply_rules": True})
    assert rerun_post.status_code == 201
    rerun_data = rerun_post.json()
    rerun_id = rerun_data["rerun_id"]
    print(f"  Rerun Run ID: {rerun_id}")

    rerun_results = repo.get_results(rerun_id)
    print(f"  Rerun Results count: {len(rerun_results)}")
    for r in rerun_results:
        print(f"    Rerun Result: {r.relationship_id}, outcome={r.outcome}, ex={r.exception_type}, src={r.source_record_ids}, tgt={r.target_record_ids}")

    print("\n[Step 4] Rule Impact...")
    impact = client.get(f"/runs/{run_id}/rule-impact").json()
    print(f"  Impact: {impact}")

if __name__ == "__main__":
    run_test()
