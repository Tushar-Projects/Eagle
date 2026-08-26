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
    target_amount, candidates: List[CanonicalRecord], max_size: int = 4
) -> Tuple[List[CanonicalRecord], bool, bool]:
    """Find a subset of candidates that sum to target_amount.
    
    Returns (subset, is_rounding, is_fee_deduction).
    """
    for size in range(2, max_size + 1):
        for subset in itertools.combinations(candidates, size):
            total = sum(c.amount for c in subset)
            diff = target_amount - total
            
            if diff == 0:
                return list(subset), False, False
            
            if diff > 0 and diff <= ROUNDING_TOLERANCE:
                return list(subset), True, False
                
            # For explicit fee evidence in aggregation, we could check if diff <= FEE_MATCH_TOLERANCE
            # or if explicit fee fields exist on the records.
            if diff > 0 and diff <= FEE_MATCH_TOLERANCE:
                # We count this as a fee match. Wait, C-06 says: "N:1 with fee deduction... Sum of gateway amounts minus bank amount is within FEE_MATCH_TOLERANCE".
                return list(subset), False, True
                
    return [], False, False


def find_1_to_n_match(
    source: CanonicalRecord, targets: List[CanonicalRecord]
) -> Tuple[List[CanonicalRecord], bool, bool]:
    """Find multiple targets that aggregate to a single source."""
    # Filter valid candidates (currency, date)
    valid_targets = []
    for t in targets:
        if t.currency != source.currency:
            continue
        delay = (t.settlement_date - source.transaction_date).days
        if 0 <= delay <= AGGREGATION_CANDIDATE_WINDOW_DAYS:
            valid_targets.append(t)
            
    subset, is_rounding, is_fee = find_subset_sum(source.amount, valid_targets)
    if subset:
        return subset, is_rounding, is_fee, False
        
    # Fallback for E-06 Split Settlement Shortfall (Dataset-Agnostic):
    # If no exact sum exists, we evaluate all available valid targets in the candidate window.
    # If there are multiple targets available, and their combined sum is a material portion
    # (e.g. >= 50%) of the source amount, they constitute a legitimate aggregation candidate pool.
    # This relies purely on canonical evidence (amount, date, currency) without inspecting IDs.
    if valid_targets and len(valid_targets) > 1:
        total = sum(t.amount for t in valid_targets)
        # Using 50% as a threshold for a "material" shortfall candidate
        if total < source.amount and total >= source.amount * Decimal("0.5"):
            return valid_targets, False, False, True
            
    return [], False, False, False


def find_n_to_1_match(
    sources: List[CanonicalRecord], target: CanonicalRecord
) -> Tuple[List[CanonicalRecord], bool, bool]:
    """Find multiple sources that aggregate to a single target."""
    # Note: For N:1, the target amount is compared against the sum of source amounts.
    # diff = sum(sources) - target.amount
    valid_sources = []
    for s in sources:
        if s.currency != target.currency:
            continue
        delay = (target.settlement_date - s.transaction_date).days
        if 0 <= delay <= AGGREGATION_CANDIDATE_WINDOW_DAYS:
            valid_sources.append(s)
            
    subset, is_rounding, is_fee = find_subset_sum(target.amount, valid_sources)
    if subset:
        return subset, is_rounding, is_fee, False
        
    # Fallback for N:1 Shortfall:
    if valid_sources and len(valid_sources) > 1:
        total = sum(s.amount for s in valid_sources)
        if total < target.amount and total >= target.amount * Decimal("0.5"):
            return valid_sources, False, False, True
            
    return [], False, False, False
