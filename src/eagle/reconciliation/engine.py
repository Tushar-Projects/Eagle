"""Deterministic reconciliation engine."""
import hashlib
from typing import List

from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType, Severity
from eagle.models.evidence import CandidateRelationshipEvidence, EngineOutput
from eagle.models.reconciliation import ReconciliationResult
from eagle.reconciliation.aggregation import find_1_to_n_match, find_n_to_1_match
from eagle.reconciliation.matching import (
    identify_deterministic_duplicates,
    is_stage1_exact_match,
    is_stage2_normalized_match,
    is_stage3_financial_match,
    is_stage4_fee_match,
)
from eagle.reconciliation.constants import ROUNDING_TOLERANCE
from eagle.reconciliation.timing import evaluate_settlement_timing


def _generate_relationship_id(source_ids: List[str], target_ids: List[str]) -> str:
    """Generate a stable, deterministic relationship ID using SHA-256.

    Inputs are sorted participant record IDs.
    """
    all_ids = sorted(source_ids + target_ids)
    joined = "|".join(all_ids)
    hash_hex = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return f"REL-{hash_hex[:12]}"


def reconcile(
    sources: List[CanonicalRecord], targets: List[CanonicalRecord]
) -> EngineOutput:
    """Execute the deterministic matching pipeline."""
    unmatched_sources = list(sources)
    unmatched_targets = list(targets)
    results: List[ReconciliationResult] = []
    candidates_evidence: List[CandidateRelationshipEvidence] = []
    ambiguous_1_to_1_sources = {}

    def _remove_matched(matched_sources: List[CanonicalRecord], matched_targets: List[CanonicalRecord]):
        for s in matched_sources:
            if s in unmatched_sources:
                unmatched_sources.remove(s)
        for t in matched_targets:
            if t in unmatched_targets:
                unmatched_targets.remove(t)

    # Helper for 1:1 stages
    def _run_1_to_1_stage(match_func, is_stage_4=False):
        matches_found = []
        candidates_for_source = {}

        for s in unmatched_sources:
            candidates = []
            for t in unmatched_targets:
                if is_stage_4:
                    is_match, is_rounding, is_fee = match_func(s, t)
                    if is_match:
                        candidates.append((t, is_rounding, is_fee))
                else:
                    if match_func(s, t):
                        candidates.append((t, False, False))
            candidates_for_source[s.record_id] = candidates

        for s in list(unmatched_sources):
            candidates = candidates_for_source.get(s.record_id, [])
            if len(candidates) == 1:
                t, is_rounding, is_fee = candidates[0]
                # Check for reverse ambiguity
                claims = sum(
                    1 for c_list in candidates_for_source.values() 
                    if any(c[0].record_id == t.record_id for c in c_list)
                )
                if claims == 1:
                    matches_found.append((s, t, is_rounding, is_fee))
            elif len(candidates) > 1:
                ambiguous_1_to_1_sources[s.record_id] = (s, candidates)

        for s, t, is_rounding, is_fee in matches_found:
            # Always check financial consistency even if matched by exact ref
            is_curr_mismatch = (s.currency != t.currency)
            diff = s.amount - t.amount
            is_material_diff = False
            
            # Check explicit fee/net match
            has_explicit_fee = (s.net_amount is not None and s.net_amount == t.amount) or \
                               (s.fee_amount is not None and s.amount - s.fee_amount == t.amount)
                               
            if not is_curr_mismatch and diff != 0:
                if has_explicit_fee:
                    is_fee = True
                elif 0 < diff <= ROUNDING_TOLERANCE:
                    is_rounding = True
                else:
                    is_material_diff = True

            # Settlement timing logic
            timing_outcome, timing_ex, timing_sev, timing_flag = evaluate_settlement_timing(
                s.transaction_date, t.settlement_date
            )
            
            # Default to outcome from timing
            final_outcome = timing_outcome
            final_ex = timing_ex
            
            if is_curr_mismatch or is_material_diff:
                # Unresolved for AI
                final_outcome = ReconciliationOutcome.EXCEPTION
                final_ex = None
                timing_sev = Severity.HIGH
                timing_flag = True
            elif final_outcome == ReconciliationOutcome.MATCHED:
                if is_rounding:
                    final_ex = ExceptionType.ROUNDING_DIFFERENCE
                elif is_fee:
                    final_ex = ExceptionType.FEE_DEDUCTION

            res = ReconciliationResult(
                relationship_id=_generate_relationship_id([s.record_id], [t.record_id]),
                relationship_type=RelationshipType.ONE_TO_ONE,
                source_record_ids=[s.record_id],
                target_record_ids=[t.record_id],
                outcome=final_outcome,
                exception_type=final_ex,
                severity=timing_sev,
                flag_for_review=timing_flag,
                reconciled_amount=s.amount,
            )
            results.append(res)
            _remove_matched([s], [t])

    # --- Duplicate Evaluation (Deterministic D-07 style) ---
    duplicate_groups = identify_deterministic_duplicates(sources) # Using full sources
    for group in duplicate_groups:
        # Keep the first, mark the rest as DUPLICATE
        keep = group[0]
        duplicates = group[1:]
        for dup in duplicates:
            if dup in unmatched_sources:
                res = ReconciliationResult(
                    relationship_id=_generate_relationship_id([dup.record_id], []),
                    relationship_type=RelationshipType.ONE_TO_ONE,
                    source_record_ids=[dup.record_id],
                    target_record_ids=[],
                    outcome=ReconciliationOutcome.EXCEPTION,
                    exception_type=ExceptionType.DUPLICATE,
                    severity=Severity.HIGH,
                    flag_for_review=True,
                    reconciled_amount=dup.amount,
                )
                results.append(res)
                unmatched_sources.remove(dup)

    # --- Stage 1: Exact Match ---
    _run_1_to_1_stage(is_stage1_exact_match)

    # --- Stage 2: Normalized Match ---
    _run_1_to_1_stage(is_stage2_normalized_match)

    # --- Stage 3: Amount/Date/Currency Match ---
    _run_1_to_1_stage(is_stage3_financial_match)

    # --- Stage 4: Fee/Net Match ---
    _run_1_to_1_stage(is_stage4_fee_match, is_stage_4=True)

    # --- Stage 5: Aggregation Match (1:N) ---
    print("UNMATCHED TARGETS BEFORE STAGE 5:")
    for t in unmatched_targets:
        print(f"{t.record_id} - {t.amount} - {t.settlement_date}")
    for s in list(unmatched_sources):
        t_subset, is_rounding, is_fee, is_shortfall = find_1_to_n_match(s, unmatched_targets)
        if t_subset:
            max_stl_date = max(t.settlement_date for t in t_subset)
            timing_outcome, timing_ex, timing_sev, timing_flag = evaluate_settlement_timing(
                s.transaction_date, max_stl_date
            )
            
            final_ex = timing_ex
            if is_shortfall:
                timing_outcome = ReconciliationOutcome.EXCEPTION
                final_ex = None
                timing_sev = Severity.HIGH
                timing_flag = True
            elif timing_outcome == ReconciliationOutcome.MATCHED:
                if is_rounding:
                    final_ex = ExceptionType.ROUNDING_DIFFERENCE
                elif is_fee:
                    final_ex = ExceptionType.FEE_DEDUCTION

            res = ReconciliationResult(
                relationship_id=_generate_relationship_id([s.record_id], [t.record_id for t in t_subset]),
                relationship_type=RelationshipType.ONE_TO_MANY,
                source_record_ids=[s.record_id],
                target_record_ids=[t.record_id for t in t_subset],
                outcome=timing_outcome,
                exception_type=final_ex,
                severity=timing_sev,
                flag_for_review=timing_flag,
                reconciled_amount=s.amount,
            )
            results.append(res)
            _remove_matched([s], t_subset)

    # --- Stage 5: Aggregation Match (N:1) ---
    for t in list(unmatched_targets):
        s_subset, is_rounding, is_fee, is_shortfall = find_n_to_1_match(unmatched_sources, t)
        if s_subset:
            max_txn_date = max(s.transaction_date for s in s_subset)
            timing_outcome, timing_ex, timing_sev, timing_flag = evaluate_settlement_timing(
                max_txn_date, t.settlement_date
            )
            
            final_ex = timing_ex
            if is_shortfall:
                timing_outcome = ReconciliationOutcome.EXCEPTION
                final_ex = None
                timing_sev = Severity.HIGH
                timing_flag = True
            elif timing_outcome == ReconciliationOutcome.MATCHED:
                if is_rounding:
                    final_ex = ExceptionType.ROUNDING_DIFFERENCE
                elif is_fee:
                    final_ex = ExceptionType.FEE_DEDUCTION

            res = ReconciliationResult(
                relationship_id=_generate_relationship_id([s.record_id for s in s_subset], [t.record_id]),
                relationship_type=RelationshipType.MANY_TO_ONE,
                source_record_ids=[s.record_id for s in s_subset],
                target_record_ids=[t.record_id],
                outcome=timing_outcome,
                exception_type=final_ex,
                severity=timing_sev,
                flag_for_review=timing_flag,
                reconciled_amount=t.amount,
            )
            results.append(res)
            _remove_matched(s_subset, [t])

    # --- Post-Stage 5: Emit Ambiguous 1:1 Pools ---
    ambiguous_targets_seen = set()
    for s_id, (s, candidates) in ambiguous_1_to_1_sources.items():
        if any(src.record_id == s_id for src in unmatched_sources):
            t_ids = [c[0].record_id for c in candidates]
            # Include targets that are unmatched OR were already used in another ambiguous pool
            valid_t_ids = [tid for tid in t_ids if tid in ambiguous_targets_seen or any(t.record_id == tid for t in unmatched_targets)]
            if valid_t_ids:
                evidence = CandidateRelationshipEvidence(
                    source_record_ids=[s.record_id],
                    candidate_target_record_ids=valid_t_ids,
                    relationship_context="Ambiguous 1:1 candidate pool. Multiple targets exist with identical financial evidence.",
                    amount_evidence="Exact amount match",
                    date_evidence="Compatible settlement delay",
                )
                candidates_evidence.append(evidence)
                unmatched_sources = [src for src in unmatched_sources if src.record_id != s_id]
                for tid in valid_t_ids:
                    ambiguous_targets_seen.add(tid)
                    unmatched_targets = [tgt for tgt in unmatched_targets if tgt.record_id != tid]

    # --- POST: Deterministic MISSING_RECORD Resolution ---
    for s in unmatched_sources:
        res = ReconciliationResult(
            relationship_id=_generate_relationship_id([s.record_id], []),
            relationship_type=RelationshipType.ONE_TO_ONE,
            source_record_ids=[s.record_id],
            target_record_ids=[],
            outcome=ReconciliationOutcome.EXCEPTION,
            exception_type=ExceptionType.MISSING_RECORD,
            severity=Severity.HIGH,
            flag_for_review=True,
            reconciled_amount=s.amount,
        )
        results.append(res)

    for t in unmatched_targets:
        res = ReconciliationResult(
            relationship_id=_generate_relationship_id([], [t.record_id]),
            relationship_type=RelationshipType.ONE_TO_ONE,
            source_record_ids=[],
            target_record_ids=[t.record_id],
            outcome=ReconciliationOutcome.EXCEPTION,
            exception_type=ExceptionType.MISSING_RECORD,
            severity=Severity.HIGH,
            flag_for_review=True,
            reconciled_amount=t.amount,
        )
        results.append(res)

    return EngineOutput(results=results, candidates=candidates_evidence)
