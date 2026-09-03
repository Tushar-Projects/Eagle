"""Deterministic reconciliation engine."""
from typing import List

from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType, Severity
from decimal import Decimal
from eagle.models.evidence import CandidateRelationshipEvidence, EngineOutput, CandidateRelationshipOption
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
from eagle.reconciliation.utils import generate_relationship_id


def reconcile(
    sources: List[CanonicalRecord], targets: List[CanonicalRecord]
) -> EngineOutput:
    """Execute the deterministic matching pipeline using anchor-based decision groups."""
    unmatched_sources = list(sources)
    unmatched_targets = list(targets)
    results: List[ReconciliationResult] = []
    
    # Track candidate 1:1 options from Stages 3 and 4
    candidate_1_to_1_options: List[CandidateRelationshipOption] = []

    def _remove_matched(matched_sources: List[CanonicalRecord], matched_targets: List[CanonicalRecord]):
        for s in matched_sources:
            if s in unmatched_sources:
                unmatched_sources.remove(s)
        for t in matched_targets:
            if t in unmatched_targets:
                unmatched_targets.remove(t)

    # Helper for 1:1 stages
    def _run_1_to_1_stage(match_func, is_stage_3=False, is_stage_4=False, collect_ambiguous=False):
        matches_found = []
        candidates_for_source = {}

        for s in unmatched_sources:
            candidates = []
            for t in unmatched_targets:
                if is_stage_4:
                    is_match, is_rounding, is_fee = match_func(s, t)
                    if is_match:
                        candidates.append((t, is_rounding, is_fee, False))
                elif is_stage_3:
                    is_cand, has_conflict = match_func(s, t)
                    if is_cand:
                        candidates.append((t, False, False, has_conflict))
                else:
                    if match_func(s, t):
                        candidates.append((t, False, False, False))
            candidates_for_source[s.record_id] = candidates

        # Check for claims per target
        target_claims = {}
        for s_id, c_list in candidates_for_source.items():
            for c in c_list:
                t_id = c[0].record_id
                target_claims.setdefault(t_id, []).append(s_id)

        for s in list(unmatched_sources):
            candidates = candidates_for_source.get(s.record_id, [])
            if len(candidates) == 1:
                t, is_rounding, is_fee, has_conflict = candidates[0]
                claims = len(target_claims.get(t.record_id, []))
                if claims == 1 and not has_conflict:
                    matches_found.append((s, t, is_rounding, is_fee))
                elif collect_ambiguous:
                    candidate_1_to_1_options.append(
                        CandidateRelationshipOption(
                            source_record_ids=[s.record_id],
                            target_record_ids=[t.record_id]
                        )
                    )
            elif len(candidates) > 1 and collect_ambiguous:
                for t, is_rounding, is_fee, has_conflict in candidates:
                    candidate_1_to_1_options.append(
                        CandidateRelationshipOption(
                            source_record_ids=[s.record_id],
                            target_record_ids=[t.record_id]
                        )
                    )

        for s, t, is_rounding, is_fee in matches_found:
            is_curr_mismatch = (s.currency != t.currency)
            diff = s.amount - t.amount
            is_material_diff = False
            
            has_explicit_fee = (s.net_amount is not None and s.net_amount == t.amount) or \
                               (s.fee_amount is not None and s.amount - s.fee_amount == t.amount)
                               
            if not is_curr_mismatch and diff != 0:
                if has_explicit_fee:
                    is_fee = True
                elif 0 < diff <= ROUNDING_TOLERANCE:
                    is_rounding = True
                else:
                    is_material_diff = True

            timing_outcome, timing_ex, timing_sev, timing_flag = evaluate_settlement_timing(
                s.transaction_date, t.settlement_date
            )
            
            final_outcome = timing_outcome
            final_ex = timing_ex
            
            if is_curr_mismatch or is_material_diff:
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
                relationship_id=generate_relationship_id([s.record_id], [t.record_id]),
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
    duplicate_groups = identify_deterministic_duplicates(sources)
    for group in duplicate_groups:
        keep = group[0]
        duplicates = group[1:]
        for dup in duplicates:
            if dup in unmatched_sources:
                res = ReconciliationResult(
                    relationship_id=generate_relationship_id([dup.record_id], []),
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
    _run_1_to_1_stage(is_stage3_financial_match, is_stage_3=True, collect_ambiguous=True)

    # --- Stage 4: Fee/Net Match ---
    _run_1_to_1_stage(is_stage4_fee_match, is_stage_4=True, collect_ambiguous=True)

    # --- Stage 5: Aggregation Match (1:N & N:1 Options Collection) ---
    candidate_1_to_n_options: List[CandidateRelationshipOption] = []
    option_flags: dict[tuple[tuple[str, ...], tuple[str, ...]], tuple[bool, bool, bool]] = {}

    for s in list(unmatched_sources):
        matches = find_1_to_n_match(s, unmatched_targets)
        if not matches:
            continue
        for t_subset, is_rounding, is_fee, is_shortfall in matches:
            opt = CandidateRelationshipOption(
                source_record_ids=[s.record_id],
                target_record_ids=sorted([t.record_id for t in t_subset])
            )
            candidate_1_to_n_options.append(opt)
            key = (tuple(sorted(opt.source_record_ids)), tuple(sorted(opt.target_record_ids)))
            option_flags[key] = (is_rounding, is_fee, is_shortfall)

    candidate_n_to_1_options: List[CandidateRelationshipOption] = []
    for t in list(unmatched_targets):
        matches = find_n_to_1_match(unmatched_sources, t)
        if not matches:
            continue
        for s_subset, is_rounding, is_fee, is_shortfall in matches:
            opt = CandidateRelationshipOption(
                source_record_ids=sorted([s.record_id for s in s_subset]),
                target_record_ids=[t.record_id]
            )
            candidate_n_to_1_options.append(opt)
            key = (tuple(sorted(opt.source_record_ids)), tuple(sorted(opt.target_record_ids)))
            option_flags[key] = (is_rounding, is_fee, is_shortfall)

    # --- Candidate Option Deduplication & Integrity ---
    # Combine all candidate options (1:1, 1:N, N:1)
    all_raw_options = candidate_1_to_1_options + candidate_1_to_n_options + candidate_n_to_1_options
    
    unique_options_dict: dict[tuple[tuple[str, ...], tuple[str, ...]], CandidateRelationshipOption] = {}
    for opt in all_raw_options:
        s_key = tuple(sorted(opt.source_record_ids))
        t_key = tuple(sorted(opt.target_record_ids))
        if (s_key, t_key) not in unique_options_dict:
            unique_options_dict[(s_key, t_key)] = CandidateRelationshipOption(
                source_record_ids=list(s_key),
                target_record_ids=list(t_key)
            )

    all_candidate_options = list(unique_options_dict.values())

    # Check for truly unambiguous deterministic aggregation matches:
    source_option_counts = {}
    target_option_counts = {}
    for opt in all_candidate_options:
        for sid in opt.source_record_ids:
            source_option_counts[sid] = source_option_counts.get(sid, 0) + 1
        for tid in opt.target_record_ids:
            target_option_counts[tid] = target_option_counts.get(tid, 0) + 1

    remaining_candidate_options: List[CandidateRelationshipOption] = []
    source_lookup = {s.record_id: s for s in sources}
    target_lookup = {t.record_id: t for t in targets}

    for opt in all_candidate_options:
        is_1_to_n = len(opt.source_record_ids) == 1 and len(opt.target_record_ids) > 1
        is_n_to_1 = len(opt.source_record_ids) > 1 and len(opt.target_record_ids) == 1
        
        # Check if strictly unambiguous
        sources_unique = all(source_option_counts[sid] == 1 for sid in opt.source_record_ids)
        targets_unique = all(target_option_counts[tid] == 1 for tid in opt.target_record_ids)

        if (is_1_to_n or is_n_to_1) and sources_unique and targets_unique:
            s_key = tuple(sorted(opt.source_record_ids))
            t_key = tuple(sorted(opt.target_record_ids))
            is_rounding, is_fee, is_shortfall = option_flags.get((s_key, t_key), (False, False, False))

            # Commit as unambiguous deterministic aggregation match
            if is_1_to_n:
                s = source_lookup[opt.source_record_ids[0]]
                t_subset = [target_lookup[tid] for tid in opt.target_record_ids]
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
                    relationship_id=generate_relationship_id([s.record_id], [t.record_id for t in t_subset]),
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
            else:
                t = target_lookup[opt.target_record_ids[0]]
                s_subset = [source_lookup[sid] for sid in opt.source_record_ids]
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
                    relationship_id=generate_relationship_id([s.record_id for s in s_subset], [t.record_id]),
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
        else:
            remaining_candidate_options.append(opt)

    # --- Construct Anchor-Based Decision Groups ---
    # Deterministic Ownership Rule:
    # 1. If len(source_record_ids) == 1 (1:1 and 1:N alternatives):
    #    Anchor = source_record_ids[0] -> Source-Anchored Group.
    # 2. If len(target_record_ids) == 1 and len(source_record_ids) > 1 (N:1 alternatives):
    #    Anchor = target_record_ids[0] -> Target-Anchored Group.
    # This guarantees every option belongs to EXACTLY ONE decision group with zero option duplication.
    source_anchored_groups: dict[str, list[CandidateRelationshipOption]] = {}
    target_anchored_groups: dict[str, list[CandidateRelationshipOption]] = {}

    for opt in remaining_candidate_options:
        if len(opt.source_record_ids) == 1:
            anchor_src = opt.source_record_ids[0]
            source_anchored_groups.setdefault(anchor_src, []).append(opt)
        elif len(opt.target_record_ids) == 1:
            anchor_tgt = opt.target_record_ids[0]
            target_anchored_groups.setdefault(anchor_tgt, []).append(opt)

    candidates_evidence: List[CandidateRelationshipEvidence] = []

    # Sort source anchors deterministically
    for anchor_src in sorted(source_anchored_groups.keys()):
        opts = source_anchored_groups[anchor_src]
        # Sort options within group deterministically
        opts.sort(key=lambda o: (o.source_record_ids, o.target_record_ids))
        evidence = CandidateRelationshipEvidence(
            candidate_options=opts,
            relationship_context=(
                f"Source-anchored candidate pool for {anchor_src}. "
                "Multiple competing 1:1 or 1:N alternatives exist for this source record."
            ),
            amount_evidence="Deterministic financial match alternatives found.",
            date_evidence="Compatible settlement delay window.",
        )
        candidates_evidence.append(evidence)

    # Sort target anchors deterministically
    for anchor_tgt in sorted(target_anchored_groups.keys()):
        opts = target_anchored_groups[anchor_tgt]
        # Sort options within group deterministically
        opts.sort(key=lambda o: (o.source_record_ids, o.target_record_ids))
        evidence = CandidateRelationshipEvidence(
            candidate_options=opts,
            relationship_context=(
                f"Target-anchored candidate pool for {anchor_tgt}. "
                "Multiple competing N:1 source combinations aggregate to target amount."
            ),
            amount_evidence="Multiple exact or near-exact sum combinations found.",
            date_evidence="Compatible settlement delay window.",
        )
        candidates_evidence.append(evidence)

    # --- POST: Deterministic MISSING_RECORD Resolution ---
    # Only records not involved in ANY committed result and not involved in ANY candidate option become MISSING_RECORD
    candidate_src_ids = {sid for ev in candidates_evidence for opt in ev.candidate_options for sid in opt.source_record_ids}
    candidate_tgt_ids = {tid for ev in candidates_evidence for opt in ev.candidate_options for tid in opt.target_record_ids}

    for s in unmatched_sources:
        if s.record_id in candidate_src_ids:
            continue
        res = ReconciliationResult(
            relationship_id=generate_relationship_id([s.record_id], []),
            relationship_type=RelationshipType.ONE_TO_ONE,
            source_record_ids=[s.record_id],
            target_record_ids=[],
            outcome=ReconciliationOutcome.EXCEPTION,
            exception_type=ExceptionType.MISSING_RECORD,
            severity=Severity.HIGH,
            flag_for_review=True,
            reconciled_amount=Decimal("0.00"),
        )
        results.append(res)

    for t in unmatched_targets:
        if t.record_id in candidate_tgt_ids:
            continue
        res = ReconciliationResult(
            relationship_id=generate_relationship_id([], [t.record_id]),
            relationship_type=RelationshipType.ONE_TO_ONE,
            source_record_ids=[],
            target_record_ids=[t.record_id],
            outcome=ReconciliationOutcome.EXCEPTION,
            exception_type=ExceptionType.MISSING_RECORD,
            severity=Severity.HIGH,
            flag_for_review=True,
            reconciled_amount=Decimal("0.00"),
        )
        results.append(res)

    return EngineOutput(results=results, candidates=candidates_evidence)
