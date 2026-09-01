"""Rule synthesizer for extracting generalized reconciliation rules from operator corrections."""

from datetime import datetime, timezone
from decimal import Decimal
import os
import re
from typing import List, Optional
import uuid

from eagle.models.canonical import CanonicalRecord
from eagle.rules.models import OperatorCorrection, ReconciliationRule


class RuleSynthesizer:
    """Synthesizes generalized, non-memorizing ReconciliationRule instances from operator corrections."""

    @staticmethod
    def synthesize(
        correction: OperatorCorrection,
        source_records: List[CanonicalRecord],
        target_records: List[CanonicalRecord],
    ) -> ReconciliationRule:
        """Derive a safe generalized rule from an operator correction and participating CanonicalRecords.

        Safety Invariants:
        1. Never embeds individual record IDs (e.g. GTW-001, BANK-001).
        2. Rejects synthesis if no non-identity generalized predicates can be formed.
        3. Never produces negative monetary tolerances or contradictory bounds.
        """
        # 1. Filter participating records
        src_set = set(correction.corrected_source_ids)
        tgt_set = set(correction.corrected_target_ids)

        active_sources = [r for r in source_records if r.record_id in src_set]
        active_targets = [r for r in target_records if r.record_id in tgt_set]

        if not active_sources and not active_targets:
            raise ValueError("Cannot synthesize rule: no participating source or target records provided.")

        # 2. Extract Generalized Counterparty
        counterparty_pattern: Optional[str] = None
        source_cps = {r.counterparty.strip() for r in active_sources if r.counterparty and r.counterparty.strip()}
        if len(source_cps) == 1:
            counterparty_pattern = next(iter(source_cps))
        elif not source_cps and active_targets:
            target_cps = {r.counterparty.strip() for r in active_targets if r.counterparty and r.counterparty.strip()}
            if len(target_cps) == 1:
                counterparty_pattern = next(iter(target_cps))

        # 3. Extract Generalized Reference Prefix
        ref_prefix: Optional[str] = None
        source_refs = [r.source_reference.strip() for r in active_sources if r.source_reference and r.source_reference.strip()]
        if source_refs:
            # Check for common prefix across references
            common = os.path.commonprefix(source_refs)
            # Remove trailing numbers to make it a general prefix (e.g. "REF-101" -> "REF-")
            clean_prefix = re.sub(r"\d+$", "", common)
            if len(clean_prefix) >= 3:
                ref_prefix = clean_prefix

        # 4. Extract Common Currency
        currency: Optional[str] = None
        currencies = {r.currency.strip().upper() for r in (active_sources + active_targets) if r.currency}
        if len(currencies) == 1:
            currency = next(iter(currencies))

        # 5. Extract Amount Difference / Tolerance
        max_amount_diff: Optional[Decimal] = None
        total_src = sum((r.amount for r in active_sources), Decimal("0.00"))
        total_tgt = sum((r.amount for r in active_targets), Decimal("0.00"))
        if active_sources and active_targets:
            diff = abs(total_src - total_tgt)
            max_amount_diff = diff

        # 6. Extract Settlement Delay Days
        max_delay_days: Optional[int] = None
        if active_sources and active_targets:
            min_src_date = min(r.transaction_date for r in active_sources)
            max_tgt_date = max(r.settlement_date for r in active_targets)
            delay = (max_tgt_date - min_src_date).days
            max_delay_days = max(0, delay)

        # 7. Safety Validation: Verify at least one meaningful predicate exists
        predicates = (counterparty_pattern, ref_prefix, currency, max_amount_diff, max_delay_days)
        if all(p is None for p in predicates):
            raise ValueError(
                "Cannot synthesize safe generalized rule: no distinctive generalized predicates found."
            )

        # 8. Check for Forbidden Memorization of Specific Record IDs
        all_record_ids = {r.record_id for r in (active_sources + active_targets)}
        if counterparty_pattern and counterparty_pattern in all_record_ids:
            raise ValueError(f"Unsafe counterparty pattern embeds exact record ID '{counterparty_pattern}'.")

        # 9. Format Descriptive Name & Description
        ex_label = correction.corrected_exception_type or "match"
        cp_label = counterparty_pattern or (f"Ref[{ref_prefix}]" if ref_prefix else "General")
        rule_name = f"{cp_label} {ex_label.lower().replace('_', ' ')} reconciliation rule"
        rule_description = (
            f"Rule derived from operator correction on relationship {correction.relationship_id}: "
            f"{correction.operator_reason}"
        )

        rule_id = f"RULE-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()

        return ReconciliationRule(
            rule_id=rule_id,
            name=rule_name,
            description=rule_description,
            source_counterparty_pattern=counterparty_pattern,
            reference_prefix=ref_prefix,
            currency=currency,
            max_amount_difference=max_amount_diff,
            max_settlement_delay_days=max_delay_days,
            target_action="PREFER_CANDIDATE",
            resulting_outcome=correction.corrected_outcome,
            resulting_exception_type=correction.corrected_exception_type,
            confidence=1.0,
            is_active=True,
            created_at=now_iso,
            source_correction_id=correction.correction_id,
        )
