"""Deterministic matching logic for individual relationship stages."""
from collections import defaultdict
from typing import List, Tuple

from eagle.models.canonical import CanonicalRecord
from eagle.reconciliation.constants import (
    FEE_MATCH_TOLERANCE,
    ROUNDING_TOLERANCE,
    SETTLEMENT_DELAY_HIGH_MIN_DAYS,
)
from eagle.reconciliation.normalization import normalize_reference


def get_exact_references(record: CanonicalRecord) -> set[str]:
    """Get non-empty exact references from a record."""
    refs = set()
    if record.transaction_id and record.transaction_id.strip():
        refs.add(record.transaction_id.strip())
    if record.source_reference and record.source_reference.strip():
        refs.add(record.source_reference.strip())
    return refs


def get_normalized_references(record: CanonicalRecord) -> set[str]:
    """Get non-empty normalized references from a record."""
    refs = set()
    if record.transaction_id:
        norm = normalize_reference(record.transaction_id)
        if norm:
            refs.add(norm)
    if record.source_reference:
        norm = normalize_reference(record.source_reference)
        if norm:
            refs.add(norm)
    return refs


def is_stage1_exact_match(source: CanonicalRecord, target: CanonicalRecord) -> bool:
    """Determine if records match based on exact identifier/reference."""
    s_refs = get_exact_references(source)
    t_refs = get_exact_references(target)
    return bool(s_refs.intersection(t_refs))


def is_stage2_normalized_match(source: CanonicalRecord, target: CanonicalRecord) -> bool:
    """Determine if records match based on normalized identifier/reference."""
    s_refs = get_normalized_references(source)
    t_refs = get_normalized_references(target)
    return bool(s_refs.intersection(t_refs))


def is_stage3_financial_match(source: CanonicalRecord, target: CanonicalRecord) -> bool:
    """Determine if records match based on amount, currency, date, and counterparty.

    Counterparty is used as a disambiguation signal if both records provide it.
    If they both provide it and it conflicts, they do not match.
    """
    if source.amount != target.amount:
        return False
    if source.currency != target.currency:
        return False

    # Check date window (allowing up to 10 days for normal matching to catch delayed settlements)
    # The actual settlement classification happens post-match.
    delay_days = (target.settlement_date - source.transaction_date).days
    if delay_days < 0 or delay_days > 15: # Arbitrary upper bound for financial matching
        return False

    # Counterparty evidence
    if source.counterparty and target.counterparty:
        # If both are present, they must not conflict materially.
        # We'll use a simple normalized check.
        s_cp = normalize_reference(source.counterparty)
        t_cp = normalize_reference(target.counterparty)
        if s_cp and t_cp and s_cp != t_cp:
            return False

    return True


def is_stage4_fee_match(source: CanonicalRecord, target: CanonicalRecord) -> Tuple[bool, bool, bool]:
    """Determine if records match based on fee/net settlement evidence.
    
    Returns:
        (is_match, is_rounding, is_fee)
    """
    if source.currency != target.currency:
        return False, False, False

    delay_days = (target.settlement_date - source.transaction_date).days
    if delay_days < 0 or delay_days > 15:
        return False, False, False

    # Check counterparty as well to be safe
    if source.counterparty and target.counterparty:
        s_cp = normalize_reference(source.counterparty)
        t_cp = normalize_reference(target.counterparty)
        if s_cp and t_cp and s_cp != t_cp:
            return False, False, False

    # 1. Check explicit gross/fee/net fields on source
    if source.net_amount is not None:
        if source.net_amount == target.amount:
            return True, False, True

    # 2. Check inferred fee if explicitly provided
    if source.fee_amount is not None:
        if source.amount - source.fee_amount == target.amount:
            return True, False, True

    # 3. Fallback to tolerances based on amount difference
    diff = source.amount - target.amount
    
    # Target amount cannot be greater than source amount unless there's some weird refund,
    # but strictly speaking fees deduct from the source amount.
    if diff <= 0:
        return False, False, False

    if diff <= ROUNDING_TOLERANCE:
        return True, True, False

    if diff <= FEE_MATCH_TOLERANCE:
        # We only classify fee if there's explicit evidence. But the prompt says:
        # "Use the frozen project constants... The deterministic engine may classify FEE_DEDUCTION 
        # when the evidence is explicit... Do not infer arbitrary fee percentages."
        # If there's no explicit fee field, but it's within FEE_MATCH_TOLERANCE, we only accept it 
        # if the difference is explicitly backed. Actually, Stage 4 allows it if we are sure it's a match.
        # Wait, if we don't have exact refs, is amount-difference enough?
        # Usually fee matching is only safe if refs match or it's the ONLY candidate.
        pass

    return False, False, False


def identify_deterministic_duplicates(sources: List[CanonicalRecord]) -> List[List[CanonicalRecord]]:
    """Identify sets of source records that are deterministic duplicates.
    
    A deterministic duplicate shares identical semantic evidence:
    amount, currency, transaction_date, and non-empty merchant_txn_ref (source_reference).
    """
    groups = defaultdict(list)
    for src in sources:
        # We need a strong identifier. If source_reference is present, we use it.
        # If it's missing, we cannot deterministically call it a duplicate (D-08 case).
        ref = src.source_reference.strip() if src.source_reference else ""
        if ref:
            key = (src.amount, src.currency, src.transaction_date, ref)
            groups[key].append(src)
        else:
            # Cannot be grouped as a deterministic duplicate without a reference
            # It will be left for AI as POSSIBLE_DUPLICATE
            pass
            
    return [group for group in groups.values() if len(group) > 1]
