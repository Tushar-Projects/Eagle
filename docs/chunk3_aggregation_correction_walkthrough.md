# Chunk 3 Aggregation Correction Walkthrough

This walkthrough summarizes the implementation of the Chunk 3 Stage 5 aggregation correction and the final candidate-evidence contract.

## Goal
To correctly handle deterministic matching where multiple valid combination subsets exist, by refraining from greedy consumption, identifying all valid alternatives, and delegating the choice to the Chunk 4 AI via a bounded index selection.

## 1. Candidate Evidence Contract Update
- **`CandidateRelationshipOption`**: Introduced in `src/eagle/models/evidence.py` to represent a single structurally valid source-to-target combination alternative.
- **`CandidateRelationshipEvidence`**: Updated to contain a list of `CandidateRelationshipOption` (`candidate_options`), replacing the disjointed `source_record_ids` and `candidate_target_record_ids`. This prevents cross-product ambiguity and enforces strict topologies that were verified deterministically.

## 2. Deterministic Engine Corrections
- **`src/eagle/reconciliation/aggregation.py`**: Refactored `find_aggregation_matches` to explore all combinations and return all valid subsets rather than breaking at the first valid result. 
- **`src/eagle/reconciliation/engine.py`**: Updated `_stage5_aggregation` to evaluate the multiplicity of the valid subsets. If exactly one subset is valid, it continues to emit a committed deterministic `MATCHED`. If multiple subsets are valid, it constructs a `CandidateRelationshipEvidence` comprising each option and refrains from consuming those records from the unmatched pools.
- **Orphan Record Filtering**: Implemented a safety filter before producing `MISSING_RECORD` exceptions to verify that a record is not involved in any pending candidate pools. Furthermore, explicitly enforced `reconciled_amount = Decimal("0.00")` for missing record exceptions.

## 3. AI Classifier Bounded Selection
- **`ClassificationCase` & `CandidateSelectionDecision`**: Updated AI contracts in `src/eagle/models/ai_contracts.py` to prompt the AI for `selected_candidate_index` instead of constructing arbitrary target ID sets.
- **`AIExceptionClassifier` (`src/eagle/agents/classifier.py`)**: 
  - Restructured to enforce bounds-checking on the AI's returned index.
  - Sourced all participant IDs explicitly from the validated `selected_candidate_index` option, satisfying the requirement that the AI must not fabricate or mutate `source_record_ids` or `target_record_ids`.
  - Updated amount and topology validation to apply specifically to the selected option, enforcing correct logic around pool-wide versus choice-specific source sets.

## 4. Evaluator and Testing Refactor
- Evaluator tests and benchmark runner logic in `tests/test_evaluator.py`, `tests/test_runner_provider.py`, and `src/eagle/evaluation/evaluator.py` were refactored to align with the new model schema, successfully gathering `source_record_ids` from nested `candidate_options`.
- `MockProvider` logic adjusted to navigate indexed pool structure to ensure deterministic pipeline benchmarks run successfully.
- **All 152 unit tests pass successfully.**

## Verification
```bash
> pytest tests/ -v
152 passed, 1 warning
> python -m eagle.evaluation
AI Improvement (F1): +3.0%
```

The system operates correctly and maintains all original frozen domain models while solving the aggregation ambiguity constraint.
