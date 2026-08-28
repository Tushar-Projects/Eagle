"""Reporting and formatting for evaluation results."""

from eagle.evaluation.models import EvaluationReport


def to_summary(report: EvaluationReport) -> str:
    """Format an EvaluationReport as a buildathon-friendly string."""
    
    rm = report.final_metrics
    cm = report.classification_metrics
    am = report.amount_metrics
    det_rm = report.deterministic_metrics
    aim = report.ai_improvement
    cand = report.candidate_metrics
    
    out = []
    out.append("═══════════════════════════════════════════════════════")
    out.append("              EAGLE RECONCILIATION BENCHMARK")
    out.append("═══════════════════════════════════════════════════════")
    out.append(f"\n  Dataset:  {rm.total_ground_truth} ground-truth relationships")
    out.append(f"  Total Predictions: {rm.total_predictions}")
    
    out.append("\n─── RELATIONSHIP DETECTION ───────────────────────────\n")
    out.append(f"  True Positives:    {rm.true_positives}/{rm.total_ground_truth}")
    out.append(f"  False Positives:   {rm.false_positives}")
    out.append(f"  False Negatives:   {rm.false_negatives}")
    out.append(f"  Precision:         {rm.precision * 100:.1f}%")
    out.append(f"  Recall:            {rm.recall * 100:.1f}%")
    out.append(f"  F1 Score:          {rm.f1 * 100:.1f}%")
    
    out.append("\n─── CLASSIFICATION ACCURACY ──────────────────────────\n")
    out.append(f"  Outcome:           {cm.outcome_correct}/{cm.total_aligned}  ({cm.outcome_accuracy * 100:.1f}%)")
    out.append(f"  Exception Type:    {cm.exception_type_correct}/{cm.total_aligned}  ({cm.exception_type_accuracy * 100:.1f}%)")
    out.append(f"  Relationship Type: {cm.relationship_type_correct}/{cm.total_aligned}  ({cm.relationship_type_accuracy * 100:.1f}%)")
    
    out.append("\n─── RECONCILED AMOUNT ────────────────────────────────\n")
    out.append(f"  Exact Match:       {am.exact_match_count}/{am.total_aligned}  ({am.exact_match_accuracy * 100:.1f}%)")
    out.append(f"  Within Tolerance:  {am.within_tolerance_count}/{am.total_aligned}  ({am.within_tolerance_accuracy * 100:.1f}%)")
    out.append(f"  Mean Abs Error:    ₹{am.mean_absolute_error:.2f}")
    
    out.append("\n─── DETERMINISTIC vs AI ──────────────────────────────\n")
    out.append(f"  Deterministic-Only F1:   {det_rm.f1 * 100:.1f}%")
    out.append(f"  Final (Det + AI) F1:     {rm.f1 * 100:.1f}%")
    out.append(f"  AI Improvement (F1):     {aim.f1_delta * 100:+.1f}%")
    out.append("")
    out.append(f"  Candidates Resolved:      {cand.resolved_candidates}/{cand.total_candidate_pools}")
    out.append(f"  Exceptions Classified:    {aim.exceptions_classified_by_ai}")
    
    out.append("\n─── UNRESOLVED ───────────────────────────────────────\n")
    out.append(f"  Unresolved Candidates:    {cand.unresolved_candidates}")
    out.append(f"  AI Classification Failures: {cand.failed_candidates}")
    
    if report.errors:
        out.append("\n─── ERRORS ───────────────────────────────────────────\n")
        out.append(f"  Total Diagnostic Errors: {len(report.errors)}")
        # Optionally print a few
        for idx, err in enumerate(report.errors[:5]):
            out.append(f"  {idx+1}. [{err.error_type}] {err.detail}")
        if len(report.errors) > 5:
            out.append(f"  ... and {len(report.errors) - 5} more.")
            
    out.append("\n═══════════════════════════════════════════════════════")
    
    return "\n".join(out)
