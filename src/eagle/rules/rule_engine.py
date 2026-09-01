"""Rule engine for applying learned reconciliation rules to deterministic candidate pools."""

from decimal import Decimal
import logging
from typing import Dict, List, Optional, Tuple

from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType, Severity
from eagle.models.evidence import CandidateRelationshipEvidence, CandidateRelationshipOption, EngineOutput
from eagle.models.reconciliation import ReconciliationResult
from eagle.reconciliation.utils import generate_relationship_id
from eagle.rules.models import ReconciliationRule

logger = logging.getLogger(__name__)


class RuleEngine:
    """Evaluates active learned rules against candidate pools and applies GlobalCommitValidator safety."""

    @classmethod
    def evaluate(
        cls,
        engine_output: EngineOutput,
        source_records: List[CanonicalRecord],
        target_records: List[CanonicalRecord],
        active_rules: List[ReconciliationRule],
        committed_results: Optional[List[ReconciliationResult]] = None,
    ) -> Tuple[List[ReconciliationResult], List[CandidateRelationshipEvidence], List[dict]]:
        """Evaluate active rules against candidate pools.

        Returns:
            Tuple of:
            - rule_results: List of committed ReconciliationResults resolved by rules.
            - remaining_candidates: List of CandidateRelationshipEvidence that were not resolved by rules.
            - applied_events: Audit metadata detailing applied and rejected rule resolutions.
        """
        if not active_rules or not engine_output.candidates:
            return [], list(engine_output.candidates), []

        source_lookup: Dict[str, CanonicalRecord] = {r.record_id: r for r in source_records}
        target_lookup: Dict[str, CanonicalRecord] = {r.record_id: r for r in target_records}

        # Seed global commitment tracker with deterministically committed results
        globally_committed_sources: set[str] = set()
        globally_committed_targets: set[str] = set()

        base_results = committed_results if committed_results is not None else engine_output.results
        for res in base_results:
            globally_committed_sources.update(res.source_record_ids)
            globally_committed_targets.update(res.target_record_ids)

        rule_results: List[ReconciliationResult] = []
        remaining_candidates: List[CandidateRelationshipEvidence] = []
        applied_events: List[dict] = []

        # Evaluate rules in candidate pools
        for candidate_pool in engine_output.candidates:
            matched_resolution = cls._resolve_pool_with_rules(
                candidate_pool=candidate_pool,
                active_rules=active_rules,
                source_lookup=source_lookup,
                target_lookup=target_lookup,
            )

            if matched_resolution is None:
                # No unambiguous rule match found
                remaining_candidates.append(candidate_pool)
                continue

            rule, selected_option = matched_resolution

            # Check Global Commitment Safety (Single-Assignment Invariant)
            src_conflicts = set(selected_option.source_record_ids) & globally_committed_sources
            tgt_conflicts = set(selected_option.target_record_ids) & globally_committed_targets

            if src_conflicts or tgt_conflicts:
                conflicts = sorted(list(src_conflicts | tgt_conflicts))
                logger.warning(
                    "Rule %s selection rejected due to global participant collision on %s",
                    rule.rule_id, conflicts
                )
                applied_events.append({
                    "event": "RULE_APPLICATION_REJECTED",
                    "rule_id": rule.rule_id,
                    "rule_name": rule.name,
                    "reason": f"Global participant collision on record(s): {conflicts}",
                    "source_record_ids": selected_option.source_record_ids,
                    "target_record_ids": selected_option.target_record_ids,
                })
                # Leave in candidate pools for downstream AI / human handling
                remaining_candidates.append(candidate_pool)
                continue

            # Determine Relationship Topology
            num_src = len(selected_option.source_record_ids)
            num_tgt = len(selected_option.target_record_ids)

            if num_src == 1 and num_tgt == 1:
                rel_type = RelationshipType.ONE_TO_ONE
            elif num_src == 1 and num_tgt > 1:
                rel_type = RelationshipType.ONE_TO_MANY
            elif num_src > 1 and num_tgt == 1:
                rel_type = RelationshipType.MANY_TO_ONE
            elif num_src >= 1 and num_tgt == 0:
                rel_type = RelationshipType.ONE_TO_ONE
            else:
                rel_type = RelationshipType.ONE_TO_ONE

            # Compute Reconciled Amount
            src_objs = [source_lookup[sid] for sid in selected_option.source_record_ids if sid in source_lookup]
            tgt_objs = [target_lookup[tid] for tid in selected_option.target_record_ids if tid in target_lookup]

            if src_objs:
                reconciled_amt = sum((s.amount for s in src_objs), Decimal("0.00"))
            elif tgt_objs:
                reconciled_amt = sum((t.amount for t in tgt_objs), Decimal("0.00"))
            else:
                reconciled_amt = None

            outcome_val = ReconciliationOutcome(rule.resulting_outcome)
            ex_type_val = (
                ExceptionType(rule.resulting_exception_type)
                if rule.resulting_exception_type
                else None
            )

            rel_id = generate_relationship_id(
                selected_option.source_record_ids,
                selected_option.target_record_ids,
            )

            result = ReconciliationResult(
                relationship_id=rel_id,
                relationship_type=rel_type,
                source_record_ids=selected_option.source_record_ids,
                target_record_ids=selected_option.target_record_ids,
                outcome=outcome_val,
                exception_type=ex_type_val,
                severity=Severity.LOW if outcome_val == ReconciliationOutcome.MATCHED else Severity.MEDIUM,
                flag_for_review=False,
                reconciled_amount=reconciled_amt,
            )

            # Global commitment passed: commit and reserve participants
            globally_committed_sources.update(selected_option.source_record_ids)
            globally_committed_targets.update(selected_option.target_record_ids)
            rule_results.append(result)

            applied_events.append({
                "event": "RULE_APPLICATION_COMPLETED",
                "rule_id": rule.rule_id,
                "rule_name": rule.name,
                "relationship_id": rel_id,
                "source_record_ids": selected_option.source_record_ids,
                "target_record_ids": selected_option.target_record_ids,
                "outcome": outcome_val.value,
                "exception_type": ex_type_val.value if ex_type_val else None,
            })

        return rule_results, remaining_candidates, applied_events

    @classmethod
    def _resolve_pool_with_rules(
        cls,
        candidate_pool: CandidateRelationshipEvidence,
        active_rules: List[ReconciliationRule],
        source_lookup: Dict[str, CanonicalRecord],
        target_lookup: Dict[str, CanonicalRecord],
    ) -> Optional[Tuple[ReconciliationRule, CandidateRelationshipOption]]:
        """Find the highest-confidence, most specific unambiguous rule matching an option in the pool."""
        valid_matches: List[Tuple[ReconciliationRule, CandidateRelationshipOption, int]] = []

        for rule in active_rules:
            matching_options = []
            for option in candidate_pool.candidate_options:
                matches, specificity = cls._evaluate_option(
                    rule=rule,
                    option=option,
                    source_lookup=source_lookup,
                    target_lookup=target_lookup,
                )
                if matches:
                    matching_options.append((option, specificity))

            # Ambiguity Check: If a rule matches more than 1 option in this pool, do not guess
            if len(matching_options) == 1:
                opt, spec = matching_options[0]
                valid_matches.append((rule, opt, spec))

        if not valid_matches:
            return None

        # Precedence:
        # 1. Higher confidence
        # 2. More specific predicates satisfied
        # 3. Deterministic rule ID tie-breaker
        valid_matches.sort(
            key=lambda item: (
                item[0].confidence,
                item[2],
                item[0].rule_id,
            ),
            reverse=True,
        )

        top_rule, top_option, _ = valid_matches[0]
        return top_rule, top_option

    @classmethod
    def _evaluate_option(
        cls,
        rule: ReconciliationRule,
        option: CandidateRelationshipOption,
        source_lookup: Dict[str, CanonicalRecord],
        target_lookup: Dict[str, CanonicalRecord],
    ) -> Tuple[bool, int]:
        """Check whether candidate option satisfies all non-None predicates of a rule.

        Returns:
            (is_match, specificity_score)
        """
        src_records = [source_lookup[sid] for sid in option.source_record_ids if sid in source_lookup]
        tgt_records = [target_lookup[tid] for tid in option.target_record_ids if tid in target_lookup]

        if not src_records and not tgt_records:
            return False, 0

        specificity = 0

        # 1. Counterparty Predicate
        if rule.source_counterparty_pattern is not None:
            pattern = rule.source_counterparty_pattern.strip().lower()
            # All source records providing a counterparty must match the pattern
            for s in src_records:
                if s.counterparty and pattern not in s.counterparty.strip().lower():
                    return False, 0
            # All target records providing a counterparty must match the pattern
            for t in tgt_records:
                if t.counterparty and pattern not in t.counterparty.strip().lower():
                    return False, 0
            # At least one participant record must have provided a counterparty that matched
            matched_any = (
                any(s.counterparty and pattern in s.counterparty.strip().lower() for s in src_records) or
                any(t.counterparty and pattern in t.counterparty.strip().lower() for t in tgt_records)
            )
            if not matched_any:
                return False, 0
            specificity += 1

        # 2. Reference Prefix Predicate
        if rule.reference_prefix is not None:
            prefix = rule.reference_prefix.strip().lower()
            src_refs = [s.source_reference.strip().lower() for s in src_records if s.source_reference]
            tgt_refs = [t.source_reference.strip().lower() for t in tgt_records if t.source_reference]
            all_refs = src_refs + tgt_refs
            if not all_refs:
                return False, 0
            if not any(r.startswith(prefix) for r in all_refs):
                return False, 0
            specificity += 1

        # 3. Currency Predicate
        if rule.currency is not None:
            curr = rule.currency.strip().upper()
            all_records = src_records + tgt_records
            if not all_records:
                return False, 0
            if not all(r.currency and r.currency.strip().upper() == curr for r in all_records):
                return False, 0
            specificity += 1

        # 4. Amount Difference Predicate
        if rule.max_amount_difference is not None:
            if not src_records or not tgt_records:
                return False, 0
            total_src = sum((s.amount for s in src_records), Decimal("0.00"))
            total_tgt = sum((t.amount for t in tgt_records), Decimal("0.00"))
            diff = abs(total_src - total_tgt)
            if diff > rule.max_amount_difference:
                return False, 0
            specificity += 1

        # 5. Settlement Delay Predicate
        if rule.max_settlement_delay_days is not None:
            if not src_records or not tgt_records:
                return False, 0
            min_src_date = min(s.transaction_date for s in src_records)
            max_tgt_date = max(t.settlement_date for t in tgt_records)
            delay = (max_tgt_date - min_src_date).days
            if delay > rule.max_settlement_delay_days or delay < 0:
                return False, 0
            specificity += 1

        return True, specificity

