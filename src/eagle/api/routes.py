"""FastAPI route handlers for reconciliation runs, results, and export."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import Response

from eagle.api.schemas import (
    AuditEventResponse,
    CandidateDecisionResponse,
    CandidateListResponse,
    CandidateOptionItem,
    CorrectionCreateRequest,
    CorrectionListResponse,
    JsonRunCreateRequest,
    OperatorCorrectionResponse,
    ReconciliationResultResponse,
    ResultsListResponse,
    RunListResponse,
    RunMetricsResponse,
    RunResponse,
)
from eagle.core.config import Settings, settings as global_settings
from eagle.export.csv_exporter import export_results_to_csv
from eagle.export.json_exporter import export_results_to_json
from eagle.extraction.json_extractor import JsonExtractor
from eagle.extraction.models import DocumentExtractionResult
from eagle.models.enums import ExceptionType, ReconciliationOutcome, RelationshipType, Severity
from eagle.rules.models import OperatorCorrection
from eagle.services.reconciliation_service import ReconciliationService
from eagle.storage.database import Database
from eagle.storage.repository import Repository

router = APIRouter()


# -------------------------------------------------------------------------
# Dependency Injection
# -------------------------------------------------------------------------

def get_service() -> ReconciliationService:
    """Dependency provider for ReconciliationService."""
    db = Database(global_settings.DATABASE_PATH)
    repo = Repository(db)
    return ReconciliationService(repository=repo, settings=global_settings)


# -------------------------------------------------------------------------
# Health & Status
# -------------------------------------------------------------------------

@router.get("/health", tags=["System"])
def health_check(service: ReconciliationService = Depends(get_service)):
    """Liveness probe returning engine health and active AI provider."""
    return {
        "status": "ok",
        "service": "Eagle Financial Reconciliation Engine",
        "provider": service.provider_name,
    }


@router.get("/demo/synthetic-data", tags=["System"])
def get_synthetic_data_sample():
    """Convenience endpoint returning the synthetic Gateway and Bank CSV samples for quick UI demonstration."""
    gtw_paths = [Path("demo_data/gateway.csv"), Path("data/synthetic/gateway.csv")]
    bank_paths = [Path("demo_data/bank.csv"), Path("data/synthetic/bank.csv")]

    gtw_path = next((p for p in gtw_paths if p.exists()), None)
    bank_path = next((p for p in bank_paths if p.exists()), None)

    if not (gtw_path and bank_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Synthetic dataset files not found on disk.",
        )

    return {
        "gateway_filename": "gateway.csv",
        "gateway_content": gtw_path.read_text(encoding="utf-8"),
        "bank_filename": "bank.csv",
        "bank_content": bank_path.read_text(encoding="utf-8"),
    }


# -------------------------------------------------------------------------
# Runs & Extraction
# -------------------------------------------------------------------------

@router.post(
    "/runs/extract-preview",
    response_model=DocumentExtractionResult,
    tags=["Extraction"],
)
async def extract_document_preview(
    file: UploadFile = File(..., description="Financial document (CSV, JSON, PDF, PNG, JPG)"),
    source_type: str = Query("GATEWAY", description="Designated source slot: 'GATEWAY' or 'BANK'"),
    service: ReconciliationService = Depends(get_service),
):
    """Extract transactions from an uploaded document for preview/inspection without committing to a run."""
    try:
        content = await file.read()
        return await service.extract_preview_async(
            file_input=content,
            source_type=source_type,
            filename=file.filename or "document",
            content_type=file.content_type,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extraction preview failed: {e}",
        ) from e


@router.post(
    "/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Runs"],
)
async def create_run_from_files(
    gateway_file: UploadFile = File(..., description="Gateway transaction file (CSV, JSON, PDF, PNG, JPG)"),
    bank_file: UploadFile = File(..., description="Bank transaction file (CSV, JSON, PDF, PNG, JPG)"),
    service: ReconciliationService = Depends(get_service),
):
    """Trigger a new reconciliation run by uploading Gateway and Bank files across supported formats."""
    try:
        gtw_bytes = await gateway_file.read()
        bank_bytes = await bank_file.read()

        result = await service.reconcile_files_async(
            gateway_input=gtw_bytes,
            bank_input=bank_bytes,
            gateway_filename=gateway_file.filename or "gateway",
            bank_filename=bank_file.filename or "bank",
            gateway_content_type=gateway_file.content_type,
            bank_content_type=bank_file.content_type,
        )
        return RunResponse.model_validate(result["summary"])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Reconciliation run failed: {e}",
        ) from e


@router.post(
    "/runs/json",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Runs"],
)
async def create_run_from_json(
    payload: JsonRunCreateRequest,
    service: ReconciliationService = Depends(get_service),
):
    """Trigger a reconciliation run by submitting structured JSON transaction records."""
    try:
        extractor = JsonExtractor()
        sources = extractor.extract(payload.source_records, source_type="GATEWAY")
        targets = extractor.extract(payload.target_records, source_type="BANK")

        result = await service.reconcile_records_async(sources, targets)
        return RunResponse.model_validate(result["summary"])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"JSON reconciliation run failed: {e}",
        ) from e


@router.get("/runs", response_model=RunListResponse, tags=["Runs"])
def list_runs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    service: ReconciliationService = Depends(get_service),
):
    """List historical reconciliation runs."""
    runs = service.repository.list_runs(limit=limit, offset=offset)
    return RunListResponse(
        runs=[RunResponse.model_validate(r) for r in runs],
        total=len(runs),
    )


@router.get("/runs/{run_id}", response_model=RunResponse, tags=["Runs"])
def get_run(
    run_id: str,
    service: ReconciliationService = Depends(get_service),
):
    """Retrieve run metadata and status by run_id."""
    run = service.repository.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation run '{run_id}' not found.",
        )
    return RunResponse.model_validate(run)


# -------------------------------------------------------------------------
# Results & Exceptions
# -------------------------------------------------------------------------

@router.get(
    "/runs/{run_id}/results",
    response_model=ResultsListResponse,
    tags=["Results"],
)
def get_run_results(
    run_id: str,
    outcome: Optional[str] = Query(None, description="Filter by MATCHED or EXCEPTION"),
    relationship_type: Optional[str] = Query(None, description="Filter by 1:1, 1:N, or N:1"),
    exception_type: Optional[str] = Query(None, description="Filter by exception classification"),
    flag_for_review: Optional[bool] = Query(None, description="Filter by review flag"),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    service: ReconciliationService = Depends(get_service),
):
    """Retrieve reconciled relationships for a run with optional filtering."""
    run = service.repository.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation run '{run_id}' not found.",
        )

    results = service.repository.get_results(run_id, outcome=outcome, exception_type=exception_type)

    # In-memory filter for additional criteria
    filtered = []
    for r in results:
        if relationship_type and (r.relationship_type.value if hasattr(r.relationship_type, "value") else str(r.relationship_type)) != relationship_type.upper():
            continue
        if flag_for_review is not None and r.flag_for_review != flag_for_review:
            continue
        filtered.append(r)

    paginated = filtered[offset : offset + limit]

    items = []
    for r in paginated:
        items.append(
            ReconciliationResultResponse(
                relationship_id=r.relationship_id,
                source_record_ids=r.source_record_ids,
                target_record_ids=r.target_record_ids,
                relationship_type=r.relationship_type.value if hasattr(r.relationship_type, "value") else str(r.relationship_type),
                outcome=r.outcome.value if hasattr(r.outcome, "value") else str(r.outcome),
                exception_type=r.exception_type.value if r.exception_type and hasattr(r.exception_type, "value") else (str(r.exception_type) if r.exception_type else None),
                severity=r.severity.value if r.severity and hasattr(r.severity, "value") else (str(r.severity) if r.severity else None),
                flag_for_review=r.flag_for_review,
                reconciled_amount=str(r.reconciled_amount) if r.reconciled_amount is not None else None,
            )
        )

    return ResultsListResponse(
        run_id=run_id,
        results=items,
        total=len(filtered),
    )


@router.get(
    "/runs/{run_id}/exceptions",
    response_model=ResultsListResponse,
    tags=["Results"],
)
def get_run_exceptions(
    run_id: str,
    exception_type: Optional[str] = Query(None, description="Filter by exception type"),
    severity: Optional[str] = Query(None, description="Filter by severity (LOW, MEDIUM, HIGH)"),
    flag_for_review: Optional[bool] = Query(None, description="Filter by review flag"),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    service: ReconciliationService = Depends(get_service),
):
    """Retrieve exception relationships for review."""
    run = service.repository.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation run '{run_id}' not found.",
        )

    exceptions = service.repository.get_exceptions(run_id)

    filtered = []
    for r in exceptions:
        if exception_type and (r.exception_type.value if r.exception_type and hasattr(r.exception_type, "value") else str(r.exception_type)) != exception_type.upper():
            continue
        if severity and (r.severity.value if r.severity and hasattr(r.severity, "value") else str(r.severity)) != severity.upper():
            continue
        if flag_for_review is not None and r.flag_for_review != flag_for_review:
            continue
        filtered.append(r)

    paginated = filtered[offset : offset + limit]

    items = []
    for r in paginated:
        items.append(
            ReconciliationResultResponse(
                relationship_id=r.relationship_id,
                source_record_ids=r.source_record_ids,
                target_record_ids=r.target_record_ids,
                relationship_type=r.relationship_type.value if hasattr(r.relationship_type, "value") else str(r.relationship_type),
                outcome=r.outcome.value if hasattr(r.outcome, "value") else str(r.outcome),
                exception_type=r.exception_type.value if r.exception_type and hasattr(r.exception_type, "value") else (str(r.exception_type) if r.exception_type else None),
                severity=r.severity.value if r.severity and hasattr(r.severity, "value") else (str(r.severity) if r.severity else None),
                flag_for_review=r.flag_for_review,
                reconciled_amount=str(r.reconciled_amount) if r.reconciled_amount is not None else None,
            )
        )

    return ResultsListResponse(
        run_id=run_id,
        results=items,
        total=len(filtered),
    )


# -------------------------------------------------------------------------
# Candidate Inspection
# -------------------------------------------------------------------------

@router.get(
    "/runs/{run_id}/candidates",
    response_model=CandidateListResponse,
    tags=["Candidates"],
)
def get_run_candidates(
    run_id: str,
    service: ReconciliationService = Depends(get_service),
):
    """Retrieve candidate decision groups, deterministic options, and validation verdicts."""
    run = service.repository.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation run '{run_id}' not found.",
        )

    candidates = service.repository.get_candidates(run_id)
    items = []
    for c in candidates:
        options = [
            CandidateOptionItem(
                index=opt["index"],
                source_record_ids=opt["source_record_ids"],
                target_record_ids=opt["target_record_ids"],
            )
            for opt in c.get("candidate_options", [])
        ]
        items.append(
            CandidateDecisionResponse(
                id=c.get("id"),
                run_id=run_id,
                anchor_record_id=c.get("anchor_record_id", ""),
                candidate_options=options,
                selected_candidate_index=c.get("selected_candidate_index"),
                ai_outcome=c.get("ai_outcome"),
                ai_exception_type=c.get("ai_exception_type"),
                confidence=c.get("confidence"),
                reasoning=c.get("reasoning", ""),
                validation_status=c.get("validation_status", "PENDING"),
                rejection_reason=c.get("rejection_reason"),
            )
        )

    return CandidateListResponse(
        run_id=run_id,
        candidates=items,
        total=len(items),
    )


# -------------------------------------------------------------------------
# Metrics & Audit Logs
# -------------------------------------------------------------------------

@router.get(
    "/runs/{run_id}/metrics",
    response_model=RunMetricsResponse,
    tags=["Metrics"],
)
def get_run_metrics(
    run_id: str,
    service: ReconciliationService = Depends(get_service),
):
    """Calculate and return operational KPI metrics and value-weighted rates for a run."""
    metrics_data = service.calculate_metrics(run_id)
    if not metrics_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation run '{run_id}' not found.",
        )

    return RunMetricsResponse.model_validate(metrics_data)


@router.get(
    "/runs/{run_id}/audit-logs",
    response_model=List[AuditEventResponse],
    tags=["Audit"],
)
def get_run_audit_logs(
    run_id: str,
    service: ReconciliationService = Depends(get_service),
):
    """Retrieve the chronological audit trail for a run."""
    run = service.repository.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation run '{run_id}' not found.",
        )

    logs = service.repository.get_audit_logs(run_id)
    return [AuditEventResponse.model_validate(l) for l in logs]


# -------------------------------------------------------------------------
# Export
# -------------------------------------------------------------------------

@router.get(
    "/runs/{run_id}/export",
    tags=["Export"],
)
def export_run_results(
    run_id: str,
    format: str = Query("csv", description="Export format: 'csv' or 'json'"),
    service: ReconciliationService = Depends(get_service),
):
    """Download reconciled relationships as CSV or JSON."""
    run = service.repository.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation run '{run_id}' not found.",
        )

    results = service.repository.get_results(run_id)
    fmt = format.lower().strip()

    if fmt == "csv":
        csv_content = export_results_to_csv(results)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=reconciliation_{run_id}.csv"
            },
        )
    elif fmt == "json":
        json_content = export_results_to_json(results, run_metadata=run)
        return Response(
            content=json_content,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=reconciliation_{run_id}.json"
            },
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export format '{format}'. Supported formats: 'csv', 'json'.",
        )


# -------------------------------------------------------------------------
# Operator Corrections & Review
# -------------------------------------------------------------------------

@router.post(
    "/runs/{run_id}/results/{relationship_id}/correct",
    response_model=OperatorCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Corrections"],
)
def submit_operator_correction(
    run_id: str,
    relationship_id: str,
    payload: CorrectionCreateRequest,
    service: ReconciliationService = Depends(get_service),
):
    """Submit a structured manual correction against an existing reconciliation result.

    The original reconciliation result remains completely immutable. The correction
    is persisted as an append-only auditable event.
    """
    # 1. Verify run exists
    run = service.repository.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation run '{run_id}' not found.",
        )

    # 2. Verify relationship exists in this run
    orig_result = service.repository.get_result(run_id, relationship_id)
    if not orig_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation relationship '{relationship_id}' not found in run '{run_id}'.",
        )

    # 3. Validate corrected outcome
    outcome_str = payload.corrected_outcome.strip().upper()
    valid_outcomes = {o.value for o in ReconciliationOutcome}
    if outcome_str not in valid_outcomes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid corrected outcome '{payload.corrected_outcome}'. Supported outcomes: {sorted(valid_outcomes)}.",
        )

    # 4. Validate corrected exception type if supplied
    ex_type_str = None
    if payload.corrected_exception_type:
        ex_type_str = payload.corrected_exception_type.strip().upper()
        valid_ex_types = {e.value for e in ExceptionType}
        if ex_type_str not in valid_ex_types:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid exception type '{payload.corrected_exception_type}'. Supported: {sorted(valid_ex_types)}.",
            )

    # 5. Validate participant record IDs exist in this run (no fabrication)
    run_records = service.repository.get_records(run_id)
    valid_record_ids = {r.record_id for r in run_records}

    if not payload.corrected_source_ids and not payload.corrected_target_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one source or target record ID must be specified in the correction.",
        )

    for sid in payload.corrected_source_ids:
        if sid not in valid_record_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Source record ID '{sid}' does not exist in run '{run_id}'. Record fabrication is prohibited.",
            )

    for tid in payload.corrected_target_ids:
        if tid not in valid_record_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Target record ID '{tid}' does not exist in run '{run_id}'. Record fabrication is prohibited.",
            )

    # 6. Validate topology: No N:M
    if len(payload.corrected_source_ids) > 1 and len(payload.corrected_target_ids) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="General N:M relationship topology is not supported for corrections. Topologies must be 1:1, 1:N, N:1, 1:0, or 0:1.",
        )

    # 7. Construct immutable correction record
    correction_id = f"CORR-{uuid.uuid4().hex[:8].upper()}"
    now_iso = datetime.now(timezone.utc).isoformat()

    orig_outcome_str = orig_result.outcome.value if hasattr(orig_result.outcome, "value") else str(orig_result.outcome)
    orig_ex_type_str = (
        orig_result.exception_type.value if orig_result.exception_type and hasattr(orig_result.exception_type, "value")
        else (str(orig_result.exception_type) if orig_result.exception_type else None)
    )

    correction = OperatorCorrection(
        correction_id=correction_id,
        run_id=run_id,
        relationship_id=relationship_id,
        original_outcome=orig_outcome_str,
        original_exception_type=orig_ex_type_str,
        original_source_ids=orig_result.source_record_ids,
        original_target_ids=orig_result.target_record_ids,
        corrected_outcome=outcome_str,
        corrected_exception_type=ex_type_str,
        corrected_source_ids=payload.corrected_source_ids,
        corrected_target_ids=payload.corrected_target_ids,
        operator_reason=payload.operator_reason.strip(),
        created_at=now_iso,
        generated_rule_id=None,
    )

    # 8. Persist correction & log audit event
    service.repository.save_correction(correction)
    service.repository.save_audit_event(
        run_id,
        "OPERATOR_CORRECTION_CREATED",
        {
            "correction_id": correction_id,
            "relationship_id": relationship_id,
            "original_outcome": orig_outcome_str,
            "corrected_outcome": outcome_str,
            "operator_reason": payload.operator_reason.strip(),
            "generate_rule_intent": payload.generate_rule,
        },
    )

    return OperatorCorrectionResponse(
        correction_id=correction.correction_id,
        run_id=correction.run_id,
        relationship_id=correction.relationship_id,
        original_outcome=correction.original_outcome,
        original_exception_type=correction.original_exception_type,
        original_source_ids=correction.original_source_ids,
        original_target_ids=correction.original_target_ids,
        corrected_outcome=correction.corrected_outcome,
        corrected_exception_type=correction.corrected_exception_type,
        corrected_source_ids=correction.corrected_source_ids,
        corrected_target_ids=correction.corrected_target_ids,
        operator_reason=correction.operator_reason,
        created_at=correction.created_at,
        status="COMMITTED",
        generated_rule_id=correction.generated_rule_id,
    )


@router.get(
    "/runs/{run_id}/corrections",
    response_model=CorrectionListResponse,
    tags=["Corrections"],
)
def get_run_corrections(
    run_id: str,
    service: ReconciliationService = Depends(get_service),
):
    """Retrieve all operator corrections submitted for a run."""
    run = service.repository.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation run '{run_id}' not found.",
        )

    corrections = service.repository.get_corrections(run_id)
    items = [
        OperatorCorrectionResponse(
            correction_id=c.correction_id,
            run_id=c.run_id,
            relationship_id=c.relationship_id,
            original_outcome=c.original_outcome,
            original_exception_type=c.original_exception_type,
            original_source_ids=c.original_source_ids,
            original_target_ids=c.original_target_ids,
            corrected_outcome=c.corrected_outcome,
            corrected_exception_type=c.corrected_exception_type,
            corrected_source_ids=c.corrected_source_ids,
            corrected_target_ids=c.corrected_target_ids,
            operator_reason=c.operator_reason,
            created_at=c.created_at,
            status="COMMITTED",
            generated_rule_id=c.generated_rule_id,
        )
        for c in corrections
    ]

    return CorrectionListResponse(
        run_id=run_id,
        corrections=items,
        total=len(items),
    )


@router.get(
    "/runs/{run_id}/corrections/{correction_id}",
    response_model=OperatorCorrectionResponse,
    tags=["Corrections"],
)
def get_run_correction_by_id(
    run_id: str,
    correction_id: str,
    service: ReconciliationService = Depends(get_service),
):
    """Retrieve a specific operator correction by ID."""
    run = service.repository.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation run '{run_id}' not found.",
        )

    corr = service.repository.get_correction(correction_id)
    if not corr or corr.run_id != run_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operator correction '{correction_id}' not found in run '{run_id}'.",
        )

    return OperatorCorrectionResponse(
        correction_id=corr.correction_id,
        run_id=corr.run_id,
        relationship_id=corr.relationship_id,
        original_outcome=corr.original_outcome,
        original_exception_type=corr.original_exception_type,
        original_source_ids=corr.original_source_ids,
        original_target_ids=corr.original_target_ids,
        corrected_outcome=corr.corrected_outcome,
        corrected_exception_type=corr.corrected_exception_type,
        corrected_source_ids=corr.corrected_source_ids,
        corrected_target_ids=corr.corrected_target_ids,
        operator_reason=corr.operator_reason,
        created_at=corr.created_at,
        status="COMMITTED",
        generated_rule_id=corr.generated_rule_id,
    )
