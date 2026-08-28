"""Tests for the evaluation and benchmarking layer."""

import pytest
from decimal import Decimal

from eagle.models.reconciliation import ReconciliationResult
from eagle.models.ground_truth import GroundTruthDataset, GroundTruthRelationship
from eagle.models.enums import ReconciliationOutcome, ExceptionType, RelationshipType, Severity
from eagle.models.ai_contracts import FailedClassification
from eagle.models.evidence import CandidateRelationshipEvidence, CandidateRelationshipOption
from eagle.evaluation.models import PipelineOutput
from eagle.evaluation.evaluator import evaluate, combine_outputs

# --- Helpers ---

def gt_rel(sid, tid, type_str="1:1", outcome="MATCHED", exc=None, amt="100.00"):
    return GroundTruthRelationship(
        relationship_id="R-TEST",
        relationship_type=RelationshipType(type_str),
        source_record_ids=[sid] if sid else [],
        target_record_ids=[tid] if tid else [],
        expected_outcome=ReconciliationOutcome(outcome),
        expected_exception_type=ExceptionType(exc) if exc else None,
        expected_reconciled_amount=Decimal(amt)
    )

def pred_rel(sid, tid, type_str="1:1", outcome="MATCHED", exc=None, amt="100.00"):
    return ReconciliationResult(
        relationship_id="REL-HASH",
        relationship_type=RelationshipType(type_str),
        source_record_ids=[sid] if sid else [],
        target_record_ids=[tid] if tid else [],
        outcome=ReconciliationOutcome(outcome),
        exception_type=ExceptionType(exc) if exc else None,
        reconciled_amount=Decimal(amt) if amt else None
    )

def run_eval(preds, gts, po=None, cands=None):
    ds = GroundTruthDataset(relationships=gts)
    return evaluate(preds, ds, po, cands)

# --- Tests ---

def test_perfect_prediction():
    gt = [gt_rel("S1", "T1")]
    pd = [pred_rel("S1", "T1")]
    rep = run_eval(pd, gt)
    assert rep.relationship_metrics.precision == 1.0
    assert rep.relationship_metrics.recall == 1.0
    assert rep.relationship_metrics.f1 == 1.0
    assert rep.classification_metrics.outcome_accuracy == 1.0
    assert rep.classification_metrics.exception_type_accuracy == 1.0
    assert rep.amount_metrics.exact_match_accuracy == 1.0

def test_missing_relationship_fn():
    gt = [gt_rel("S1", "T1")]
    pd = []
    rep = run_eval(pd, gt)
    assert rep.relationship_metrics.false_negatives == 1
    assert rep.relationship_metrics.recall == 0.0

def test_false_positive_relationship():
    gt = []
    pd = [pred_rel("S1", "T1")]
    rep = run_eval(pd, gt)
    assert rep.relationship_metrics.false_positives == 1
    assert rep.relationship_metrics.precision == 0.0

def test_wrong_target_set():
    gt = [gt_rel("S1", "T1")]
    pd = [pred_rel("S1", "T2")]
    rep = run_eval(pd, gt)
    assert rep.relationship_metrics.false_positives == 1
    assert rep.relationship_metrics.false_negatives == 1
    assert rep.relationship_metrics.f1 == 0.0

def test_wrong_source_set():
    gt = [gt_rel("S1", "T1")]
    pd = [pred_rel("S2", "T1")]
    rep = run_eval(pd, gt)
    assert rep.relationship_metrics.f1 == 0.0

def test_wrong_1n_topology():
    gt = [
        GroundTruthRelationship(
            relationship_id="R",
            relationship_type=RelationshipType.ONE_TO_MANY,
            source_record_ids=["S1"],
            target_record_ids=["T1", "T2"],
            expected_outcome=ReconciliationOutcome.MATCHED,
            expected_reconciled_amount=Decimal("100.00")
        )
    ]
    pd = [
        ReconciliationResult(
            relationship_id="REL",
            relationship_type=RelationshipType.ONE_TO_ONE, # WRONG
            source_record_ids=["S1"],
            target_record_ids=["T1", "T2"],
            outcome=ReconciliationOutcome.MATCHED,
            reconciled_amount=Decimal("100.00")
        )
    ]
    rep = run_eval(pd, gt)
    assert rep.relationship_metrics.true_positives == 1 # Structural match!
    assert rep.classification_metrics.relationship_type_correct == 0
    assert rep.classification_metrics.relationship_type_accuracy == 0.0
    
    topo_errs = [e for e in rep.errors if e.error_type == "WRONG_TOPOLOGY"]
    assert len(topo_errs) == 1

def test_wrong_n1_topology():
    gt = [
        GroundTruthRelationship(
            relationship_id="R",
            relationship_type=RelationshipType.MANY_TO_ONE,
            source_record_ids=["S1", "S2"],
            target_record_ids=["T1"],
            expected_outcome=ReconciliationOutcome.MATCHED,
            expected_reconciled_amount=Decimal("100.00")
        )
    ]
    pd = [
        ReconciliationResult(
            relationship_id="REL",
            relationship_type=RelationshipType.ONE_TO_ONE,
            source_record_ids=["S1", "S2"],
            target_record_ids=["T1"],
            outcome=ReconciliationOutcome.MATCHED,
            reconciled_amount=Decimal("100.00")
        )
    ]
    rep = run_eval(pd, gt)
    assert rep.relationship_metrics.true_positives == 1
    assert rep.classification_metrics.relationship_type_correct == 0

def test_missing_record_source_side():
    gt = [gt_rel("S1", None, outcome="EXCEPTION", exc="MISSING_RECORD")]
    pd = [pred_rel("S1", None, outcome="EXCEPTION", exc="MISSING_RECORD")]
    rep = run_eval(pd, gt)
    assert rep.relationship_metrics.true_positives == 1

def test_missing_record_target_side():
    gt = [gt_rel(None, "T1", outcome="EXCEPTION", exc="MISSING_RECORD")]
    pd = [pred_rel(None, "T1", outcome="EXCEPTION", exc="MISSING_RECORD")]
    rep = run_eval(pd, gt)
    assert rep.relationship_metrics.true_positives == 1

def test_missing_record_wrong_direction():
    gt = [gt_rel("S1", None, outcome="EXCEPTION", exc="MISSING_RECORD")]
    pd = [pred_rel(None, "S1", outcome="EXCEPTION", exc="MISSING_RECORD")]
    rep = run_eval(pd, gt)
    assert rep.relationship_metrics.true_positives == 0
    assert rep.relationship_metrics.false_positives == 1
    assert rep.relationship_metrics.false_negatives == 1

def test_correct_exception_classification():
    gt = [gt_rel("S1", "T1", outcome="EXCEPTION", exc="CURRENCY_MISMATCH")]
    pd = [pred_rel("S1", "T1", outcome="EXCEPTION", exc="CURRENCY_MISMATCH")]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.exception_type_correct == 1

def test_incorrect_exception_classification():
    gt = [gt_rel("S1", "T1", outcome="EXCEPTION", exc="CURRENCY_MISMATCH")]
    pd = [pred_rel("S1", "T1", outcome="EXCEPTION", exc="PARTIAL_SETTLEMENT")]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.exception_type_correct == 0
    assert "CURRENCY_MISMATCH" in rep.classification_metrics.exception_type_breakdown
    assert rep.classification_metrics.exception_type_breakdown["CURRENCY_MISMATCH"]["missed"] == 1
    assert rep.classification_metrics.exception_type_breakdown["PARTIAL_SETTLEMENT"]["incorrect"] == 1

def test_none_exception_type_correct():
    gt = [gt_rel("S1", "T1")]
    pd = [pred_rel("S1", "T1")]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.exception_type_correct == 1

def test_none_exception_type_incorrect():
    gt = [gt_rel("S1", "T1")]
    pd = [pred_rel("S1", "T1", exc="UNKNOWN")]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.exception_type_correct == 0

def test_unresolved_exception_incorrect():
    gt = [gt_rel("S1", "T1", exc="CURRENCY_MISMATCH")]
    pd = [pred_rel("S1", "T1", exc=None)]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.exception_type_correct == 0

def test_correct_outcome():
    gt = [gt_rel("S1", "T1", outcome="EXCEPTION")]
    pd = [pred_rel("S1", "T1", outcome="EXCEPTION")]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.outcome_correct == 1

def test_incorrect_outcome():
    gt = [gt_rel("S1", "T1", outcome="EXCEPTION")]
    pd = [pred_rel("S1", "T1", outcome="MATCHED")]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.outcome_correct == 0

def test_correct_reconciled_amount():
    gt = [gt_rel("S1", "T1", amt="100.00")]
    pd = [pred_rel("S1", "T1", amt="100.00")]
    rep = run_eval(pd, gt)
    assert rep.amount_metrics.exact_match_count == 1
    assert rep.amount_metrics.within_tolerance_count == 1

def test_incorrect_reconciled_amount():
    gt = [gt_rel("S1", "T1", amt="100.00")]
    pd = [pred_rel("S1", "T1", amt="150.00")]
    rep = run_eval(pd, gt)
    assert rep.amount_metrics.exact_match_count == 0
    assert rep.amount_metrics.within_tolerance_count == 0

def test_amount_within_tolerance():
    gt = [gt_rel("S1", "T1", amt="100.00")]
    pd = [pred_rel("S1", "T1", amt="99.50")] # 0.50 diff <= 1.00 rounding tolerance
    rep = run_eval(pd, gt)
    assert rep.amount_metrics.exact_match_count == 0
    assert rep.amount_metrics.within_tolerance_count == 1

def test_unresolved_candidate_pool():
    gt = [gt_rel("S1", "T1")]
    pd = []
    
    cands = [CandidateRelationshipEvidence(
        candidate_options=[
            CandidateRelationshipOption(source_record_ids=["S1"], target_record_ids=["T1"]),
            CandidateRelationshipOption(source_record_ids=["S1"], target_record_ids=["T2"])
        ],
        relationship_context="test"
    )]
    
    po = PipelineOutput(predictions=[], failed_classifications=[], unresolved_candidates=cands)
    rep = run_eval(pd, gt, po, cands)
    
    assert rep.candidate_metrics.unresolved_candidates == 1
    assert rep.relationship_metrics.false_negatives == 1

def test_e03_correct_resolution():
    gt = [gt_rel("S1", "T1")]
    pd = [pred_rel("S1", "T1")]
    
    cands = [CandidateRelationshipEvidence(
        candidate_options=[
            CandidateRelationshipOption(source_record_ids=["S1"], target_record_ids=["T1"]),
            CandidateRelationshipOption(source_record_ids=["S1"], target_record_ids=["T2"])
        ],
        relationship_context="test"
    )]
    
    po = PipelineOutput(predictions=pd, failed_classifications=[], unresolved_candidates=[])
    rep = run_eval(pd, gt, po, cands)
    
    assert rep.candidate_metrics.resolved_candidates == 1
    assert rep.candidate_metrics.correct_selections == 1
    assert rep.relationship_metrics.true_positives == 1

def test_d08_possible_duplicate():
    gt = [gt_rel("S1", None, outcome="EXCEPTION", exc="POSSIBLE_DUPLICATE")]
    pd = [pred_rel("S1", None, outcome="EXCEPTION", exc="POSSIBLE_DUPLICATE")]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.exception_type_correct == 1

def test_e06_split_settlement():
    gt = [
        GroundTruthRelationship(
            relationship_id="R-E06",
            relationship_type=RelationshipType.ONE_TO_MANY,
            source_record_ids=["S1"],
            target_record_ids=["T1", "T2"],
            expected_outcome=ReconciliationOutcome.EXCEPTION,
            expected_exception_type=ExceptionType.SPLIT_SETTLEMENT,
            expected_reconciled_amount=Decimal("100.00")
        )
    ]
    pd = [
        ReconciliationResult(
            relationship_id="REL",
            relationship_type=RelationshipType.ONE_TO_MANY,
            source_record_ids=["S1"],
            target_record_ids=["T1", "T2"],
            outcome=ReconciliationOutcome.EXCEPTION,
            exception_type=ExceptionType.SPLIT_SETTLEMENT,
            reconciled_amount=Decimal("100.00")
        )
    ]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.exception_type_correct == 1

def test_d05_currency_mismatch():
    gt = [gt_rel("S1", "T1", exc="CURRENCY_MISMATCH")]
    pd = [pred_rel("S1", "T1", exc="CURRENCY_MISMATCH")]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.exception_type_correct == 1

def test_d06_partial_settlement():
    gt = [gt_rel("S1", "T1", exc="PARTIAL_SETTLEMENT")]
    pd = [pred_rel("S1", "T1", exc="PARTIAL_SETTLEMENT")]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.exception_type_correct == 1

def test_d09_unknown():
    gt = [gt_rel("S1", "T1", exc="UNKNOWN")]
    pd = [pred_rel("S1", "T1", exc="UNKNOWN")]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.exception_type_correct == 1

def test_e05_unknown():
    gt = [gt_rel("S1", "T1", exc="UNKNOWN")]
    pd = [pred_rel("S1", "T1", exc="UNKNOWN")]
    rep = run_eval(pd, gt)
    assert rep.classification_metrics.exception_type_correct == 1

def test_duplicate_prediction_handled():
    gt = [gt_rel("S1", "T1")]
    pd = [pred_rel("S1", "T1"), pred_rel("S1", "T1")]
    rep = run_eval(pd, gt)
    assert rep.relationship_metrics.true_positives == 1
    errs = [e for e in rep.errors if e.error_type == "DUPLICATE_PREDICTION"]
    assert len(errs) == 1

def test_extra_prediction_fp():
    gt = [gt_rel("S1", "T1")]
    pd = [pred_rel("S1", "T1"), pred_rel("S2", "T2")]
    rep = run_eval(pd, gt)
    assert rep.relationship_metrics.false_positives == 1

# --- Integration / Pipeline tests ---

from eagle.evaluation.runner import run_synthetic_benchmark, run_deterministic_only
import os

def test_deterministic_only_benchmark():
    # Will run on synthetic dataset files
    report = run_deterministic_only(
        "data/synthetic/gateway.csv",
        "data/synthetic/bank.csv",
        "data/synthetic/ground_truth.json"
    )
    assert report.relationship_metrics.total_ground_truth > 0
    # E-03 is candidate pool, so FP/FN exist in deterministic-only
    
def test_full_pipeline_benchmark():
    from eagle.agents.classifier import AIExceptionClassifier
    from eagle.agents._mock import MockProvider
    
    report = run_synthetic_benchmark(
        "data/synthetic/gateway.csv",
        "data/synthetic/bank.csv",
        "data/synthetic/ground_truth.json",
        classifier=AIExceptionClassifier(provider=MockProvider())
    )
    assert report.relationship_metrics.total_ground_truth > 0
    assert report.classification_metrics.exception_type_correct > 0

def test_ai_improvement_positive():
    from eagle.agents.classifier import AIExceptionClassifier
    from eagle.agents._mock import MockProvider
    
    report = run_synthetic_benchmark(
        "data/synthetic/gateway.csv",
        "data/synthetic/bank.csv",
        "data/synthetic/ground_truth.json",
        classifier=AIExceptionClassifier(provider=MockProvider())
    )
    assert report.ai_improvement.relationships_resolved_by_ai > 0
    assert report.ai_improvement.f1_delta > 0

def test_combine_outputs():
    er = [pred_rel("S1", "T1", exc=None)]
    ar = [pred_rel("S1", "T1", exc="CURRENCY_MISMATCH")]
    po = combine_outputs(er, [], ar, [])
    assert len(po.predictions) == 1
    assert po.predictions[0].exception_type == ExceptionType.CURRENCY_MISMATCH

def test_summary_output_format():
    from eagle.agents.classifier import AIExceptionClassifier
    from eagle.agents._mock import MockProvider
    
    report = run_synthetic_benchmark(
        classifier=AIExceptionClassifier(provider=MockProvider())
    )
    from eagle.evaluation.report import to_summary
    text = to_summary(report)
    assert "EAGLE RECONCILIATION BENCHMARK" in text
    assert "True Positives" in text
