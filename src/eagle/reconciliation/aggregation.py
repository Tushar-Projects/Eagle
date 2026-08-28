"""Aggregation matching (Stage 5) for 1:N and N:1 relationships."""
import itertools
from decimal import Decimal
from typing import List, Tuple

from eagle.models.canonical import CanonicalRecord
from eagle.reconciliation.constants import (
    FEE_MATCH_TOLERANCE,
    ROUNDING_TOLERANCE,
)

# Implementation-level configuration to bound candidate generation safely.
AGGREGATION_CANDIDATE_WINDOW_DAYS = 7



def find_subset_sum(
    target_amount: Decimal,
    candidates: List[CanonicalRecord],
    max_size: int = 4,
    is_source_candidates: bool = False,
) -> List[Tuple[List[CanonicalRecord], bool, bool]]:
    """Find ALL subsets of candidates that sum to target_amount.
    
    Args:
        target_amount: The single amount to match against (source amount for 1:N, or target amount for N:1).
        candidates: The list of records to subset from.
        max_size: Maximum subset size (default 4).
        is_source_candidates: True if candidates are source records (N:1), False if target records (1:N).

    Returns:
        List of (subset, is_rounding, is_fee_deduction).
    """
    valid_subsets = []
    for size in range(2, max_size + 1):
        for subset in itertools.combinations(candidates, size):
            candidate_sum = sum(c.amount for c in subset)
            if is_source_candidates:
                # N:1 aggregation: candidate_sum is gross source total, target_amount is net bank target
                source_total = candidate_sum
                target_total = target_amount
            else:
                # 1:N aggregation: target_amount is gross gateway source, candidate_sum is net bank targets total
                source_total = target_amount
                target_total = candidate_sum

            diff = source_total - target_total  # fee = gross source total - net target amount
            
            if diff == 0:
                valid_subsets.append((list(subset), False, False))
            elif diff > 0 and diff <= ROUNDING_TOLERANCE:
                valid_subsets.append((list(subset), True, False))
            elif diff > 0 and diff <= FEE_MATCH_TOLERANCE:
                valid_subsets.append((list(subset), False, True))
                
    return valid_subsets


def find_1_to_n_match(
    source: CanonicalRecord, targets: List[CanonicalRecord]
) -> List[Tuple[List[CanonicalRecord], bool, bool, bool]]:
    """Find ALL target combinations that aggregate to a single source.
    
    Returns a list of (subset, is_rounding, is_fee, is_shortfall).
    """
    valid_targets = []
    for t in targets:
        if t.currency != source.currency:
            continue
        delay = (t.settlement_date - source.transaction_date).days
        if 0 <= delay <= AGGREGATION_CANDIDATE_WINDOW_DAYS:
            valid_targets.append(t)
            
    matches = []
    subsets = find_subset_sum(source.amount, valid_targets)
    for subset, is_rounding, is_fee in subsets:
        matches.append((subset, is_rounding, is_fee, False))
        
    if matches:
        return matches
        
    # Fallback for E-06 Split Settlement Shortfall
    if valid_targets and len(valid_targets) > 1:
        total = sum(t.amount for t in valid_targets)
        if total < source.amount and total >= source.amount * Decimal("0.5"):
            return [(valid_targets, False, False, True)]
            
    return []


def find_n_to_1_match(
    sources: List[CanonicalRecord], target: CanonicalRecord
) -> List[Tuple[List[CanonicalRecord], bool, bool, bool]]:
    """Find ALL source combinations that aggregate to a single target."""
    valid_sources = []
    for s in sources:
        if s.currency != target.currency:
            continue
        delay = (target.settlement_date - s.transaction_date).days
        if 0 <= delay <= AGGREGATION_CANDIDATE_WINDOW_DAYS:
            valid_sources.append(s)
            
    matches = []
    subsets = find_subset_sum(target.amount, valid_sources, is_source_candidates=True)
    for subset, is_rounding, is_fee in subsets:
        matches.append((subset, is_rounding, is_fee, False))
        
    if matches:
        return matches
        
    # Fallback for N:1 Shortfall:
    if valid_sources and len(valid_sources) > 1:
        total = sum(s.amount for s in valid_sources)
        if total < target.amount and total >= target.amount * Decimal("0.5"):
            return [(valid_sources, False, False, True)]
            
    return []
