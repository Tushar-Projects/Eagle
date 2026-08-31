"""Application service orchestrating the full reconciliation pipeline."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, List, Optional, TextIO, Union

from eagle.agents.classifier import AIExceptionClassifier
from eagle.agents.provider import LLMProvider, create_provider
from eagle.core.config import Settings, settings as global_settings
from eagle.extraction.csv_extractor import CsvExtractor
from eagle.extraction.models import DocumentExtractionResult
from eagle.extraction.router import ExtractorRouter
from eagle.models.canonical import CanonicalRecord
from eagle.models.enums import ExceptionType, ReconciliationOutcome
from eagle.models.evidence import CandidateRelationshipEvidence, EngineOutput
from eagle.models.reconciliation import ReconciliationResult
from eagle.reconciliation.engine import reconcile
from eagle.storage.database import Database
from eagle.storage.repository import Repository

logger = logging.getLogger(__name__)


def generate_run_id() -> str:
    """Generate a clean, timestamped run ID."""
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"RUN-{now_str}-{uuid.uuid4().hex[:6]}"


class ReconciliationService:
    """Primary application service for ingesting, reconciling, and persisting financial runs."""

    def __init__(
        self,
        repository: Optional[Repository] = None,
        provider: Optional[LLMProvider] = None,
        settings: Optional[Settings] = None,
        router: Optional[ExtractorRouter] = None,
    ):
        self.settings = settings or global_settings
        
        if repository is not None:
            self.repository = repository
        else:
            db = Database(self.settings.DATABASE_PATH)
            self.repository = Repository(db)

        if provider is not None:
            self.provider = provider
            self.provider_name = getattr(provider, "name", provider.__class__.__name__)
        else:
            self.provider = create_provider(self.settings)
            self.provider_name = self.settings.AI_PROVIDER

        self.csv_extractor = CsvExtractor()
        self.router = router or ExtractorRouter()

    # -------------------------------------------------------------------------
    # Public Entry Points
    # -------------------------------------------------------------------------

    def reconcile_files(
        self,
        gateway_input: Union[str, Path, TextIO, BinaryIO, bytes],
        bank_input: Union[str, Path, TextIO, BinaryIO, bytes],
        run_id: Optional[str] = None,
        gateway_filename: str = "gateway.csv",
        bank_filename: str = "bank.csv",
        gateway_content_type: Optional[str] = None,
        bank_content_type: Optional[str] = None,
    ) -> dict:
        """Synchronous ingestion and reconciliation from Gateway and Bank files."""
        return asyncio.run(
            self.reconcile_files_async(
                gateway_input,
                bank_input,
                run_id=run_id,
                gateway_filename=gateway_filename,
                bank_filename=bank_filename,
                gateway_content_type=gateway_content_type,
                bank_content_type=bank_content_type,
            )
        )

    async def reconcile_files_async(
        self,
        gateway_input: Union[str, Path, TextIO, BinaryIO, bytes],
        bank_input: Union[str, Path, TextIO, BinaryIO, bytes],
        run_id: Optional[str] = None,
        gateway_filename: str = "gateway.csv",
        bank_filename: str = "bank.csv",
        gateway_content_type: Optional[str] = None,
        bank_content_type: Optional[str] = None,
    ) -> dict:
        """Asynchronously extract records from files across formats and execute reconciliation."""
        rid = run_id or generate_run_id()

        try:
            sources = await self.router.extract_async(
                gateway_input,
                source_type="GATEWAY",
                filename=gateway_filename,
                content_type=gateway_content_type,
            )
            targets = await self.router.extract_async(
                bank_input,
                source_type="BANK",
                filename=bank_filename,
                content_type=bank_content_type,
            )
        except Exception as e:
            # Record failed run if extraction fails
            self.repository.create_run(
                run_id=rid,
                status="FAILED",
                ai_provider=self.provider_name,
            )
            self.repository.update_run(
                run_id=rid,
                status="FAILED",
                completed_at=datetime.now(timezone.utc).isoformat(),
                error_message=f"Ingestion failed: {e}",
            )
            self.repository.save_audit_event(
                rid, "RUN_FAILED", {"stage": "INGESTION", "error": str(e)}
            )
            raise

        return await self.reconcile_records_async(sources, targets, run_id=rid)

    async def extract_preview_async(
        self,
        file_input: Union[str, Path, TextIO, BinaryIO, bytes],
        source_type: str = "GATEWAY",
        filename: str = "document",
        content_type: Optional[str] = None,
    ) -> DocumentExtractionResult:
        """Extract transactions as a preview result without triggering reconciliation."""
        return await self.router.extract_preview_async(
            file_input=file_input,
            source_type=source_type,
            filename=filename,
            content_type=content_type,
        )

    def reconcile_records(
        self,
        sources: List[CanonicalRecord],
        targets: List[CanonicalRecord],
        run_id: Optional[str] = None,
    ) -> dict:
        """Synchronous wrapper for running reconciliation on pre-extracted records."""
        return asyncio.run(self.reconcile_records_async(sources, targets, run_id))

    async def reconcile_records_async(
        self,
        sources: List[CanonicalRecord],
        targets: List[CanonicalRecord],
        run_id: Optional[str] = None,
    ) -> dict:
        """Asynchronously execute reconciliation lifecycle with full persistence."""
        rid = run_id or generate_run_id()
        total_records = len(sources) + len(targets)

        # 1. Initialize Run
        self.repository.create_run(
            run_id=rid,
            status="PROCESSING",
            ai_provider=self.provider_name,
            total_records=total_records,
            source_count=len(sources),
            target_count=len(targets),
        )
        self.repository.save_audit_event(
            rid,
            "RUN_CREATED",
            {
                "ai_provider": self.provider_name,
                "source_count": len(sources),
                "target_count": len(targets),
            },
        )

        try:
            # 2. Persist Ingested Records
            self.repository.save_records(rid, sources + targets)
            self.repository.save_audit_event(
                rid,
                "INGESTION_COMPLETED",
                {"source_count": len(sources), "target_count": len(targets)},
            )

            # 3. Deterministic Reconciliation Core
            engine_output: EngineOutput = reconcile(sources, targets)
            self.repository.save_audit_event(
                rid,
                "RECONCILIATION_STARTED",
                {
                    "deterministic_matches": len(engine_output.results),
                    "candidate_pools": len(engine_output.candidates),
                },
            )

            # 4. AI Exception Classification & Candidate Selection
            classifier = AIExceptionClassifier(
                provider=self.provider,
                max_retries=self.settings.AI_MAX_RETRIES,
                max_concurrency=self.settings.AI_MAX_CONCURRENCY,
            )
            classifier_output = await classifier.classify_all(engine_output, sources, targets)
            self.repository.save_audit_event(
                rid,
                "AI_CLASSIFICATION_COMPLETED",
                {
                    "classified_results": len(classifier_output.classified_results),
                    "failed_cases": len(classifier_output.failed_cases),
                },
            )

            # 5. Merge Outputs
            final_results = self._merge_results(
                engine_results=engine_output.results,
                ai_results=classifier_output.classified_results,
            )

            # 6. Extract Candidate Decision Metadata for Auditing
            candidate_decisions = self._build_candidate_decisions(
                candidates=engine_output.candidates,
                classified_results=classifier_output.classified_results,
                failed_cases=classifier_output.failed_cases,
            )

            # 7. Compute Summary Metrics
            matched_count = sum(
                1 for r in final_results if r.outcome == ReconciliationOutcome.MATCHED
            )
            exception_count = sum(
                1
                for r in final_results
                if r.outcome == ReconciliationOutcome.EXCEPTION
                and r.exception_type != ExceptionType.MISSING_RECORD
            )
            missing_count = sum(
                1
                for r in final_results
                if r.exception_type == ExceptionType.MISSING_RECORD
            )
            unresolved_count = len(classifier_output.failed_cases)

            # 8. Persist Everything Atomically
            now_iso = datetime.now(timezone.utc).isoformat()
            self.repository.save_results(rid, final_results, provenance="DETERMINISTIC_AND_AI")
            self.repository.save_candidate_decisions(rid, candidate_decisions)
            
            run_data = self.repository.update_run(
                run_id=rid,
                status="COMPLETED",
                completed_at=now_iso,
                total_records=total_records,
                source_count=len(sources),
                target_count=len(targets),
                matched_count=matched_count,
                exception_count=exception_count,
                missing_count=missing_count,
                unresolved_count=unresolved_count,
            )

            self.repository.save_audit_event(
                rid,
                "RUN_COMPLETED",
                {
                    "matched": matched_count,
                    "exceptions": exception_count,
                    "missing": missing_count,
                    "unresolved": unresolved_count,
                },
            )

            return {
                "run_id": rid,
                "status": "COMPLETED",
                "summary": run_data,
                "results_count": len(final_results),
                "candidates_count": len(engine_output.candidates),
            }

        except Exception as e:
            logger.exception("Reconciliation run %s failed: %s", rid, e)
            now_iso = datetime.now(timezone.utc).isoformat()
            self.repository.update_run(
                run_id=rid,
                status="FAILED",
                completed_at=now_iso,
                error_message=str(e),
            )
            self.repository.save_audit_event(
                rid, "RUN_FAILED", {"error": str(e)}
            )
            raise

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------

    def _merge_results(
        self,
        engine_results: List[ReconciliationResult],
        ai_results: List[ReconciliationResult],
    ) -> List[ReconciliationResult]:
        """Merge deterministic results with AI-classified and resolved candidate results.

        Orphaned records superseded by committed candidate selections are cleanly removed.
        """
        final_dict: dict[tuple[frozenset[str], frozenset[str]], ReconciliationResult] = {}

        # Add all deterministic results
        for r in engine_results:
            key = (frozenset(r.source_record_ids), frozenset(r.target_record_ids))
            final_dict[key] = r

        # Add or supersede with AI results
        for r in ai_results:
            # If the AI result committed participants that were previously orphans, remove old orphans
            for sid in r.source_record_ids:
                orphan_key = (frozenset([sid]), frozenset([]))
                if orphan_key in final_dict:
                    del final_dict[orphan_key]

            for tid in r.target_record_ids:
                orphan_key = (frozenset([]), frozenset([tid]))
                if orphan_key in final_dict:
                    del final_dict[orphan_key]

            key = (frozenset(r.source_record_ids), frozenset(r.target_record_ids))
            final_dict[key] = r

        return list(final_dict.values())

    def _build_candidate_decisions(
        self,
        candidates: List[CandidateRelationshipEvidence],
        classified_results: List[ReconciliationResult],
        failed_cases: list,
    ) -> List[dict]:
        """Structure candidate decisions and validation verdicts for persistence."""
        committed_lookup = {
            (frozenset(r.source_record_ids), frozenset(r.target_record_ids)): r
            for r in classified_results
        }
        failed_sources = {
            frozenset(fc.source_record_ids): fc for fc in failed_cases
        }

        decisions = []
        for cand in candidates:
            anchor_id = ""
            if cand.candidate_options:
                if cand.candidate_options[0].source_record_ids:
                    anchor_id = cand.candidate_options[0].source_record_ids[0]
                elif cand.candidate_options[0].target_record_ids:
                    anchor_id = cand.candidate_options[0].target_record_ids[0]

            # Serialize candidate options
            options_json = [
                {
                    "index": idx,
                    "source_record_ids": opt.source_record_ids,
                    "target_record_ids": opt.target_record_ids,
                }
                for idx, opt in enumerate(cand.candidate_options)
            ]

            # Check if one of the candidate options was committed
            matched_result = None
            selected_idx = None
            for idx, opt in enumerate(cand.candidate_options):
                key = (frozenset(opt.source_record_ids), frozenset(opt.target_record_ids))
                if key in committed_lookup:
                    matched_result = committed_lookup[key]
                    selected_idx = idx
                    break

            if matched_result is not None:
                decisions.append(
                    {
                        "anchor_record_id": anchor_id,
                        "candidate_options": options_json,
                        "selected_candidate_index": selected_idx,
                        "ai_outcome": (
                            matched_result.outcome.value
                            if hasattr(matched_result.outcome, "value")
                            else str(matched_result.outcome)
                        ),
                        "ai_exception_type": (
                            matched_result.exception_type.value
                            if matched_result.exception_type and hasattr(matched_result.exception_type, "value")
                            else (str(matched_result.exception_type) if matched_result.exception_type else None)
                        ),
                        "confidence": 1.0,
                        "reasoning": "Deterministic candidate option selected and committed.",
                        "validation_status": "COMMITTED",
                        "rejection_reason": None,
                    }
                )
            else:
                # Check if the candidate was an explicit ABSTENTION (zero target records committed as an exception)
                src_key = frozenset(
                    sid for opt in cand.candidate_options for sid in opt.source_record_ids
                )
                abstained_result = committed_lookup.get((src_key, frozenset([])))

                if abstained_result is not None:
                    decisions.append(
                        {
                            "anchor_record_id": anchor_id,
                            "candidate_options": options_json,
                            "selected_candidate_index": None,
                            "ai_outcome": (
                                abstained_result.outcome.value
                                if hasattr(abstained_result.outcome, "value")
                                else str(abstained_result.outcome)
                            ),
                            "ai_exception_type": (
                                abstained_result.exception_type.value
                                if abstained_result.exception_type and hasattr(abstained_result.exception_type, "value")
                                else (str(abstained_result.exception_type) if abstained_result.exception_type else None)
                            ),
                            "confidence": 1.0,
                            "reasoning": "AI abstained from selecting candidate targets (e.g. POSSIBLE_DUPLICATE).",
                            "validation_status": "ABSTAINED",
                            "rejection_reason": None,
                        }
                    )
                else:
                    # Check failed cases
                    matching_failure = failed_sources.get(src_key)
                    if matching_failure:
                        fail_reason = matching_failure.failure_reason.lower()
                        if "collision" in fail_reason or "safety violation" in fail_reason or "invalid" in fail_reason:
                            status = "REJECTED"
                        elif "retries exhausted" in fail_reason or "timeout" in fail_reason or "parse" in fail_reason or "json" in fail_reason:
                            status = "CLASSIFICATION_FAILED"
                        elif "abstained" in fail_reason:
                            status = "ABSTAINED"
                        else:
                            status = "REJECTED"

                        decisions.append(
                            {
                                "anchor_record_id": anchor_id,
                                "candidate_options": options_json,
                                "selected_candidate_index": None,
                                "ai_outcome": None,
                                "ai_exception_type": None,
                                "confidence": 0.0,
                                "reasoning": matching_failure.failure_reason,
                                "validation_status": status,
                                "rejection_reason": matching_failure.failure_reason,
                            }
                        )
                    else:
                        decisions.append(
                            {
                                "anchor_record_id": anchor_id,
                                "candidate_options": options_json,
                                "selected_candidate_index": None,
                                "ai_outcome": None,
                                "ai_exception_type": None,
                                "confidence": 0.0,
                                "reasoning": "Candidate pool remained unresolved.",
                                "validation_status": "UNRESOLVED",
                                "rejection_reason": None,
                            }
                        )

        return decisions
