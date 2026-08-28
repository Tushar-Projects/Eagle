"""Pipeline runner for the evaluation benchmark."""

from eagle.evaluation.data_loader import load_gateway_records, load_bank_records, load_ground_truth
from eagle.evaluation.evaluator import combine_outputs, evaluate, compute_comparison
from eagle.evaluation.models import EvaluationReport, PipelineOutput
from eagle.reconciliation.engine import reconcile
from eagle.agents.classifier import AIExceptionClassifier

def run_deterministic_only(gateway_csv: str, bank_csv: str, ground_truth_json: str) -> EvaluationReport:
    """Run evaluation using only the deterministic engine."""
    sources = load_gateway_records(gateway_csv)
    targets = load_bank_records(bank_csv)
    ground_truth = load_ground_truth(ground_truth_json)
    
    engine_output = reconcile(sources, targets)
    
    pipeline_output = PipelineOutput(
        predictions=engine_output.results,
        failed_classifications=[],
        unresolved_candidates=engine_output.candidates
    )
    
    return evaluate(
        predictions=engine_output.results,
        ground_truth=ground_truth,
        pipeline_output=pipeline_output,
        engine_candidates=engine_output.candidates
    )

def run_synthetic_benchmark(
    gateway_csv: str = "data/synthetic/gateway.csv",
    bank_csv: str = "data/synthetic/bank.csv",
    ground_truth_json: str = "data/synthetic/ground_truth.json",
    classifier: AIExceptionClassifier | None = None
) -> EvaluationReport:
    """Run full evaluation pipeline including AI classifier."""
    
    sources = load_gateway_records(gateway_csv)
    targets = load_bank_records(bank_csv)
    ground_truth = load_ground_truth(ground_truth_json)
    
    # 1. Deterministic Engine
    engine_output = reconcile(sources, targets)
    
    # Evaluate Deterministic-Only
    det_pipeline = PipelineOutput(
        predictions=engine_output.results,
        failed_classifications=[],
        unresolved_candidates=engine_output.candidates
    )
    det_report = evaluate(
        predictions=engine_output.results,
        ground_truth=ground_truth,
        pipeline_output=det_pipeline,
        engine_candidates=engine_output.candidates
    )
    
    # 2. AI Classifier
    if classifier is None:
        from eagle.core.config import settings
        from eagle.agents.provider import create_provider
        
        # Check credentials based on provider
        if settings.AI_PROVIDER == "gemini" and not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not configured for the gemini provider.")
        elif settings.AI_PROVIDER == "claude" and not settings.CLAUDE_API_KEY:
            raise ValueError("CLAUDE_API_KEY is not configured for the claude provider.")
            
        provider = create_provider(settings)
        classifier = AIExceptionClassifier(provider=provider)
        
    classifier_output = classifier.classify_all_sync(engine_output, sources, targets)
    
    # 3. Combine outputs
    final_pipeline = combine_outputs(
        engine_results=engine_output.results,
        engine_candidates=engine_output.candidates,
        ai_classified_results=classifier_output.classified_results,
        ai_failed_classifications=classifier_output.failed_cases
    )
    
    # 4. Evaluate Final
    final_report = evaluate(
        predictions=final_pipeline.predictions,
        ground_truth=ground_truth,
        pipeline_output=final_pipeline,
        engine_candidates=engine_output.candidates
    )
    
    # 5. Compute Comparison
    comparison = compute_comparison(det_report, final_report)
    
    # 6. Build combined report
    final_report.deterministic_metrics = comparison.deterministic_only
    final_report.final_metrics = comparison.final
    final_report.ai_improvement = comparison.ai_improvement
    
    return final_report
