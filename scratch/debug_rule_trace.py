"""Diagnostic trace script to inspect the exact execution flow of Day 2."""

from datetime import date
from decimal import Decimal
import json

from eagle.agents._mock import MockProvider
from eagle.core.config import Settings
from eagle.models.canonical import CanonicalRecord
from eagle.reconciliation.engine import reconcile
from eagle.rules.models import OperatorCorrection
from eagle.rules.rule_engine import RuleEngine
from eagle.rules.rule_synthesizer import RuleSynthesizer
from eagle.services.reconciliation_service import ReconciliationService
from eagle.storage.database import Database
from eagle.storage.repository import Repository


def trace():
    db = Database(":memory:")
    repo = Repository(db)
    provider = MockProvider()
    settings = Settings(DATABASE_PATH=":memory:", AI_PROVIDER="mock")
    service = ReconciliationService(repository=repo, provider=provider, settings=settings)

    sources = [
        CanonicalRecord(
            record_id="GTW-DEMO-01",
            transaction_id="TX-DEMO-01",
            source="GATEWAY",
            source_reference="REF-GAMMA-101",
            amount=Decimal("5000.00"),
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
            record_id="BANK-DEMO-01",
            transaction_id="BNK-DEMO-01",
            source="BANK",
            source_reference="REF-GAMMA-101",
            amount=Decimal("4998.00"),
            currency="INR",
            transaction_date=date(2025, 5, 2),
            settlement_date=date(2025, 5, 2),
            counterparty="Merchant Gamma",
            status="POSTED",
            transaction_type="CREDIT",
        ),
        CanonicalRecord(
            record_id="BANK-DEMO-02",
            transaction_id="BNK-DEMO-02",
            source="BANK",
            source_reference="REF-DECOY-101",
            amount=Decimal("4998.00"),
            currency="INR",
            transaction_date=date(2025, 5, 2),
            settlement_date=date(2025, 5, 2),
            counterparty="Other Merchant",
            status="POSTED",
            transaction_type="CREDIT",
        ),
    ]

    print("--- 1. Deterministic Engine Output ---")
    engine_output = reconcile(sources, targets)
    print(f"Engine Results count: {len(engine_output.results)}")
    for r in engine_output.results:
        print(f"  Result: {r.relationship_id}, outcome={r.outcome}, ex={r.exception_type}, src={r.source_record_ids}, tgt={r.target_record_ids}")
    print(f"Engine Candidates count: {len(engine_output.candidates)}")
    for c in engine_output.candidates:
        print(f"  Candidate pool context: {c.relationship_context}")
        for opt in c.candidate_options:
            print(f"    Option: src={opt.source_record_ids}, tgt={opt.target_record_ids}")

    print("\n--- 2. Initial Full Reconciliation Run ---")
    init_res = service.reconcile_records(sources, targets, apply_rules=False)
    run_id = init_res["run_id"]
    results_run = repo.get_results(run_id)
    print(f"Run ID: {run_id}, results count: {len(results_run)}")
    for r in results_run:
        print(f"  Run Result: {r.relationship_id}, outcome={r.outcome}, ex={r.exception_type}, src={r.source_record_ids}, tgt={r.target_record_ids}")

    rel_id = results_run[0].relationship_id
    corr = OperatorCorrection(
        correction_id="CORR-1",
        run_id=run_id,
        relationship_id=rel_id,
        original_outcome="EXCEPTION",
        original_source_ids=["GTW-DEMO-01"],
        original_target_ids=["BANK-DEMO-01"],
        corrected_outcome="MATCHED",
        corrected_exception_type="FEE_DEDUCTION",
        corrected_source_ids=["GTW-DEMO-01"],
        corrected_target_ids=["BANK-DEMO-01"],
        operator_reason="Merchant Gamma fee",
        created_at="2025-05-02T00:00:00Z",
    )

    print("\n--- 3. Synthesizing Rule ---")
    rule = RuleSynthesizer.synthesize(corr, sources, targets)
    print(f"Synthesized Rule: {rule.model_dump_json(indent=2)}")
    repo.save_rule(rule)

    print("\n--- 4. Trace RuleEngine Evaluation ---")
    active_rules = repo.get_rules(active_only=True)
    print(f"Active rules in repo: {len(active_rules)}")
    rule_results, remaining_cands, events = RuleEngine.evaluate(
        engine_output=engine_output,
        source_records=sources,
        target_records=targets,
        active_rules=active_rules,
        committed_results=engine_output.results,
    )
    print(f"Rule results count: {len(rule_results)}")
    for r in rule_results:
        print(f"  Rule Result: {r.relationship_id}, outcome={r.outcome}, ex={r.exception_type}, src={r.source_record_ids}, tgt={r.target_record_ids}")
    print(f"Remaining candidates: {len(remaining_cands)}")
    print(f"Events: {events}")

    print("\n--- 5. Trace Rerun ---")
    rerun_res = service.reconcile_records(sources, targets, run_id=f"{run_id}-RERUN-1", apply_rules=True)
    rerun_id = rerun_res["run_id"]
    rerun_results = repo.get_results(rerun_id)
    print(f"Rerun ID: {rerun_id}, results count: {len(rerun_results)}")
    for r in rerun_results:
        print(f"  Rerun Result: {r.relationship_id}, outcome={r.outcome}, ex={r.exception_type}, src={r.source_record_ids}, tgt={r.target_record_ids}")

    print("\n--- 6. Metrics ---")
    init_metrics = service.calculate_metrics(run_id)
    rerun_metrics = service.calculate_metrics(rerun_id)
    print(f"Init Metrics: {init_metrics}")
    print(f"Rerun Metrics: {rerun_metrics}")


if __name__ == "__main__":
    trace()
