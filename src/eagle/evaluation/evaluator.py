"""Evaluation logic for the synthetic benchmark."""

from collections import defaultdict
from decimal import Decimal
from collections.abc import Iterable

from eagle.models.reconciliation import ReconciliationResult
from eagle.models.ground_truth import GroundTruthDataset, GroundTruthRelationship
from eagle.models.enums import ReconciliationOutcome, ExceptionType
from eagle.models.evidence import CandidateRelationshipEvidence
from eagle.models.ai_contracts import FailedClassification
from eagle.reconciliation.constants import ROUNDING_TOLERANCE

from eagle.evaluation.models import (
    PipelineOutput,
    EvaluationReport,
    RelationshipMetrics,
    ClassificationMetrics,
    AmountMetrics,
    CandidateMetrics,
    AIImprovementMetrics,
    ErrorDiagnostic,
    ComparisonMetrics
)


def combine_outputs(
    engine_results: list[ReconciliationResult],
    engine_candidates: list[CandidateRelationshipEvidence],
    ai_classified_results: list[ReconciliationResult],
    ai_failed_classifications: list[FailedClassification]
) -> PipelineOutput:
    """Combine deterministic engine results with AI classifier results.
    
    Exception-classification results REPLACE the deterministic ones.
    Candidate-selection results are ADDED as new predictions.
    """
    final_predictions: dict[tuple[frozenset[str], frozenset[str]], ReconciliationResult] = {}
    
    # 1. Add all deterministic results
    for res in engine_results:
        key = (frozenset(res.source_record_ids), frozenset(res.target_record_ids))
        final_predictions[key] = res
        
    # 2. Add or replace with AI results
    for res in ai_classified_results:
        key = (frozenset(res.source_record_ids), frozenset(res.target_record_ids))
        final_predictions[key] = res
        
    # 3. Determine unresolved candidates
    # A candidate is unresolved if it's not in classified results and not in failed classifications?
    # Wait, failed classifications mean it IS unresolved, just failed.
    # The requirement: "CandidateRelationshipEvidence entries remaining after AI classification are tracked as unresolved candidates."
    # The AI resolves a candidate by returning a CandidateSelectionDecision which becomes a ReconciliationResult.
    # If it fails, it produces a FailedClassification.
    
    resolved_candidate_keys = set()
    for res in ai_classified_results:
        # We don't have case_type here, but candidates are the ones that were NOT in engine_results.
        key = (frozenset(res.source_record_ids), frozenset(res.target_record_ids))
        # This is a bit tricky: a candidate might have multiple target_record_ids, but the AI selects a subset.
        # It's better to just track by source_record_ids because in our domain, candidate pools are 1:1 or 1:N from a source.
        pass

    # A simpler way: we know the candidate pools.
    # If an AI classified result has the same source_record_ids as a candidate pool, it resolved it.
    resolved_sources = {frozenset(res.source_record_ids) for res in ai_classified_results}
    failed_sources = {frozenset(fc.source_record_ids) for fc in ai_failed_classifications if fc.case_type == "CANDIDATE_SELECTION"}
    
    unresolved_candidates = []
    for cand in engine_candidates:
        src_set = frozenset(sid for opt in cand.candidate_options for sid in opt.source_record_ids)
        if src_set not in resolved_sources and src_set not in failed_sources:
            unresolved_candidates.append(cand)
            
    return PipelineOutput(
        predictions=list(final_predictions.values()),
        failed_classifications=ai_failed_classifications,
        unresolved_candidates=unresolved_candidates
    )


def safe_div(n: int | float, d: int | float) -> float:
    return float(n) / float(d) if d > 0 else 0.0


def evaluate(
    predictions: list[ReconciliationResult],
    ground_truth: GroundTruthDataset,
    pipeline_output: PipelineOutput | None = None,
    engine_candidates: list[CandidateRelationshipEvidence] | None = None
) -> EvaluationReport:
    """Evaluate predictions against ground truth."""
    
    gt_index: dict[tuple[frozenset[str], frozenset[str]], GroundTruthRelationship] = {}
    for gt in ground_truth.relationships:
        key = (frozenset(gt.source_record_ids), frozenset(gt.target_record_ids))
        gt_index[key] = gt
        
    pred_index: dict[tuple[frozenset[str], frozenset[str]], ReconciliationResult] = {}
    errors: list[ErrorDiagnostic] = []
    
    # Check for duplicate predictions
    for p in predictions:
        key = (frozenset(p.source_record_ids), frozenset(p.target_record_ids))
        if key in pred_index:
            errors.append(ErrorDiagnostic(
                error_type="DUPLICATE_PREDICTION",
                gt_relationship_id=gt_index.get(key).relationship_id if key in gt_index else None,
                source_record_ids=p.source_record_ids,
                target_record_ids=p.target_record_ids,
                expected={},
                predicted={"relationship_type": p.relationship_type.value},
                detail="Multiple predictions have the same participant sets."
            ))
        else:
            pred_index[key] = p
            
    # Calculate PR/F1
    tp = 0
    fp = 0
    fn = 0
    
    aligned_pairs: list[tuple[GroundTruthRelationship, ReconciliationResult]] = []
    
    for gt_key, gt in gt_index.items():
        if gt_key in pred_index:
            tp += 1
            aligned_pairs.append((gt, pred_index[gt_key]))
        else:
            fn += 1
            errors.append(ErrorDiagnostic(
                error_type="MISSING_RELATIONSHIP",
                gt_relationship_id=gt.relationship_id,
                source_record_ids=gt.source_record_ids,
                target_record_ids=gt.target_record_ids,
                expected={"relationship_type": gt.relationship_type.value},
                predicted=None,
                detail="Ground-truth relationship has no structurally aligned prediction."
            ))
            
    for pred_key, pred in pred_index.items():
        if pred_key not in gt_index:
            fp += 1
            errors.append(ErrorDiagnostic(
                error_type="FALSE_RELATIONSHIP",
                gt_relationship_id=None,
                source_record_ids=pred.source_record_ids,
                target_record_ids=pred.target_record_ids,
                expected={},
                predicted={"relationship_type": pred.relationship_type.value},
                detail="Prediction has no structurally aligned ground-truth relationship."
            ))

    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = safe_div(2 * precision * recall, precision + recall)
    
    rel_metrics = RelationshipMetrics(
        total_ground_truth=len(gt_index),
        total_predictions=len(pred_index),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1
    )
    
    # Classification Metrics
    outcome_correct = 0
    exc_type_correct = 0
    rel_type_correct = 0
    exc_type_bd: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "incorrect": 0, "missed": 0})
    
    for gt, pred in aligned_pairs:
        # Outcome
        if pred.outcome == gt.expected_outcome:
            outcome_correct += 1
        else:
            errors.append(ErrorDiagnostic(
                error_type="WRONG_OUTCOME",
                gt_relationship_id=gt.relationship_id,
                source_record_ids=gt.source_record_ids,
                target_record_ids=gt.target_record_ids,
                expected={"outcome": gt.expected_outcome.value},
                predicted={"outcome": pred.outcome.value},
                detail=f"Expected {gt.expected_outcome.value}, got {pred.outcome.value}"
            ))
            
        # Exception Type
        expected_exc = gt.expected_exception_type.value if gt.expected_exception_type else None
        predicted_exc = pred.exception_type.value if pred.exception_type else None
        
        if predicted_exc == expected_exc:
            exc_type_correct += 1
            if expected_exc:
                exc_type_bd[expected_exc]["correct"] += 1
        else:
            if expected_exc:
                exc_type_bd[expected_exc]["missed"] += 1
            if predicted_exc and not expected_exc:
                exc_type_bd[predicted_exc]["incorrect"] += 1
            elif predicted_exc and expected_exc:
                exc_type_bd[predicted_exc]["incorrect"] += 1
                
            errors.append(ErrorDiagnostic(
                error_type="WRONG_EXCEPTION_TYPE",
                gt_relationship_id=gt.relationship_id,
                source_record_ids=gt.source_record_ids,
                target_record_ids=gt.target_record_ids,
                expected={"exception_type": expected_exc},
                predicted={"exception_type": predicted_exc},
                detail=f"Expected {expected_exc}, got {predicted_exc}"
            ))
            
        # Relationship Type
        if pred.relationship_type == gt.relationship_type:
            rel_type_correct += 1
        else:
            errors.append(ErrorDiagnostic(
                error_type="WRONG_TOPOLOGY",
                gt_relationship_id=gt.relationship_id,
                source_record_ids=gt.source_record_ids,
                target_record_ids=gt.target_record_ids,
                expected={"relationship_type": gt.relationship_type.value},
                predicted={"relationship_type": pred.relationship_type.value},
                detail=f"Expected {gt.relationship_type.value}, got {pred.relationship_type.value}"
            ))

    class_metrics = ClassificationMetrics(
        total_aligned=tp,
        outcome_correct=outcome_correct,
        outcome_accuracy=safe_div(outcome_correct, tp),
        exception_type_correct=exc_type_correct,
        exception_type_accuracy=safe_div(exc_type_correct, tp),
        relationship_type_correct=rel_type_correct,
        relationship_type_accuracy=safe_div(rel_type_correct, tp),
        exception_type_breakdown=dict(exc_type_bd)
    )
    
    # Amount Metrics
    exact_match_count = 0
    within_tolerance_count = 0
    total_error = Decimal("0.00")
    amount_errors_list = []
    
    for gt, pred in aligned_pairs:
        gt_amt = gt.expected_reconciled_amount
        pred_amt = pred.reconciled_amount if pred.reconciled_amount is not None else Decimal("0.00")
        
        error = abs(gt_amt - pred_amt)
        total_error += error
        
        if error == Decimal("0.00"):
            exact_match_count += 1
            within_tolerance_count += 1
        elif error <= ROUNDING_TOLERANCE:
            within_tolerance_count += 1
            amount_errors_list.append({"relationship_id": gt.relationship_id, "error": str(error), "type": "WITHIN_TOLERANCE"})
        else:
            amount_errors_list.append({"relationship_id": gt.relationship_id, "error": str(error), "type": "OUTSIDE_TOLERANCE"})
            errors.append(ErrorDiagnostic(
                error_type="WRONG_RECONCILED_AMOUNT",
                gt_relationship_id=gt.relationship_id,
                source_record_ids=gt.source_record_ids,
                target_record_ids=gt.target_record_ids,
                expected={"reconciled_amount": str(gt_amt)},
                predicted={"reconciled_amount": str(pred_amt)},
                detail=f"Amount error: {error}"
            ))
            
    amt_metrics = AmountMetrics(
        total_aligned=tp,
        exact_match_count=exact_match_count,
        exact_match_accuracy=safe_div(exact_match_count, tp),
        within_tolerance_count=within_tolerance_count,
        within_tolerance_accuracy=safe_div(within_tolerance_count, tp),
        mean_absolute_error=total_error / tp if tp > 0 else Decimal("0.00"),
        amount_errors=amount_errors_list
    )
    
    # Candidate Metrics
    if pipeline_output and engine_candidates is not None:
        failed_count = sum(1 for fc in pipeline_output.failed_classifications if fc.case_type == "CANDIDATE_SELECTION")
        unresolved_count = len(pipeline_output.unresolved_candidates)
        total_pools = len(engine_candidates)
        resolved_count = total_pools - failed_count - unresolved_count
        
        # Determine correct/incorrect selections
        # For a candidate to be correct, the AI must have selected the targets such that it forms a TP
        # We can look at the predictions that came from candidate pools.
        # But a simpler way: just check if the source is in aligned_pairs (since it's a TP).
        correct_selections = 0
        incorrect_selections = 0
        
        for cand in engine_candidates:
            src_set = frozenset(sid for opt in cand.candidate_options for sid in opt.source_record_ids)
            # Was this candidate resolved?
            is_resolved = True
            if any(frozenset(fc.source_record_ids) == src_set for fc in pipeline_output.failed_classifications if fc.case_type == "CANDIDATE_SELECTION"):
                is_resolved = False
            if any(frozenset(sid for opt in uc.candidate_options for sid in opt.source_record_ids) == src_set for uc in pipeline_output.unresolved_candidates):
                is_resolved = False
                
            if is_resolved:
                # Did it result in a TP?
                # Check if there is a TP with this source set
                is_tp = any(frozenset(aligned_gt.source_record_ids) == src_set for aligned_gt, _ in aligned_pairs)
                if is_tp:
                    correct_selections += 1
                else:
                    incorrect_selections += 1
                    
        for cand in pipeline_output.unresolved_candidates:
            errors.append(ErrorDiagnostic(
                error_type="UNRESOLVED_CANDIDATE",
                gt_relationship_id=None,
                source_record_ids=list(frozenset(sid for opt in cand.candidate_options for sid in opt.source_record_ids)),
                target_record_ids=[],
                expected={},
                predicted=None,
                detail="Candidate pool remained unresolved."
            ))
            
        for fc in pipeline_output.failed_classifications:
            errors.append(ErrorDiagnostic(
                error_type="AI_CLASSIFICATION_FAILURE",
                gt_relationship_id=None,
                source_record_ids=fc.source_record_ids,
                target_record_ids=[],
                expected={},
                predicted=None,
                detail=f"AI failed: {fc.failure_reason}"
            ))
            
    else:
        # Deterministic-only mode or missing pipeline data
        total_pools = len(engine_candidates) if engine_candidates else 0
        failed_count = 0
        unresolved_count = total_pools
        resolved_count = 0
        correct_selections = 0
        incorrect_selections = 0
        
    cand_metrics = CandidateMetrics(
        total_candidate_pools=total_pools,
        resolved_candidates=resolved_count,
        failed_candidates=failed_count,
        unresolved_candidates=unresolved_count,
        correct_selections=correct_selections,
        incorrect_selections=incorrect_selections
    )
    
    # Severity & Flag descriptive stats
    severity_dist: dict[str, int] = defaultdict(int)
    flag_count = 0
    for pred in predictions:
        sev = pred.severity.value if pred.severity else "None"
        severity_dist[sev] += 1
        if pred.flag_for_review:
            flag_count += 1
            
    return EvaluationReport(
        relationship_metrics=rel_metrics,
        classification_metrics=class_metrics,
        amount_metrics=amt_metrics,
        candidate_metrics=cand_metrics,
        deterministic_metrics=rel_metrics, # Will be replaced by runner
        final_metrics=rel_metrics,       # Will be replaced by runner
        ai_improvement=AIImprovementMetrics(
            relationships_resolved_by_ai=0,
            exceptions_classified_by_ai=0,
            precision_delta=0.0,
            recall_delta=0.0,
            f1_delta=0.0,
            exception_accuracy_delta=0.0
        ), # Will be replaced by runner
        errors=errors,
        severity_distribution=dict(severity_dist),
        flag_for_review_count=flag_count
    )


def compute_comparison(det_report: EvaluationReport, final_report: EvaluationReport) -> ComparisonMetrics:
    """Compare deterministic-only against final (AI) evaluation."""
    
    det_rm = det_report.relationship_metrics
    fin_rm = final_report.relationship_metrics
    
    det_cm = det_report.classification_metrics
    fin_cm = final_report.classification_metrics
    
    ai_imp = AIImprovementMetrics(
        relationships_resolved_by_ai=final_report.candidate_metrics.resolved_candidates,
        # Exceptions classified by AI: number of exceptions where AI made a decision.
        # We can approximate this by the increase in classified exceptions, or just look at the difference in exception_type_correct.
        # But really it's the number of aligned pairs where deterministic was None and final is not None.
        # For simplicity in this aggregated function, we can compute it from the accuracy change or just the raw counts if we track it.
        # Let's just track the delta in correct exception types as a proxy for now, or since we only have reports here, let's use the delta.
        exceptions_classified_by_ai=fin_cm.exception_type_correct - det_cm.exception_type_correct,
        precision_delta=fin_rm.precision - det_rm.precision,
        recall_delta=fin_rm.recall - det_rm.recall,
        f1_delta=fin_rm.f1 - det_rm.f1,
        exception_accuracy_delta=fin_cm.exception_type_accuracy - det_cm.exception_type_accuracy
    )
    
    return ComparisonMetrics(
        deterministic_only=det_rm,
        final=fin_rm,
        ai_improvement=ai_imp
    )
