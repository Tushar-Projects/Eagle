"""Integration tests for the FastAPI REST API endpoints."""

import io
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eagle.agents._mock import MockProvider
from eagle.api.main import app
from eagle.api.routes import get_service
from eagle.core.config import Settings
from eagle.services.reconciliation_service import ReconciliationService
from eagle.storage.database import Database
from eagle.storage.repository import Repository


@pytest.fixture
def api_client():
    """Create a TestClient with an isolated in-memory service override."""
    db = Database(":memory:")
    repo = Repository(db)
    provider = MockProvider()
    settings = Settings(DATABASE_PATH=":memory:", AI_PROVIDER="mock")
    service = ReconciliationService(repository=repo, provider=provider, settings=settings)

    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


class TestFastApiEndpoints:
    """Test suite for FastAPI reconciliation endpoints."""

    def test_health_check(self, api_client):
        response = api_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "provider" in data

    def test_dashboard_ui_and_static_serving(self, api_client):
        # Serve index.html at root
        res_root = api_client.get("/")
        assert res_root.status_code == 200
        assert "EAGLE" in res_root.text
        assert "AI Financial Reconciliation Engine" in res_root.text

        # Serve styles.css
        res_css = api_client.get("/static/styles.css")
        assert res_css.status_code == 200
        assert "var(--bg-app)" in res_css.text

        # Serve app.js
        res_js = api_client.get("/static/app.js")
        assert res_js.status_code == 200
        assert "API" in res_js.text

    def test_demo_synthetic_data_endpoint(self, api_client):
        res_demo = api_client.get("/demo/synthetic-data")
        assert res_demo.status_code == 200
        data = res_demo.json()
        assert "gateway_content" in data
        assert "bank_content" in data
        assert "GTW-A01" in data["gateway_content"]
        assert "BANK-A01" in data["bank_content"]

    def test_post_runs_multipart_success(self, api_client):
        gtw_csv = (
            "payment_id,merchant_txn_ref,amount,currency,created_at,merchant_name\n"
            "GTW-01,REF-01,1000.00,INR,2025-01-15,Acme\n"
            "GTW-02,REF-02,2000.00,INR,2025-01-15,Globex\n"
        )
        bank_csv = (
            "bank_reference,narration,settlement_amount,currency,posting_date,counterparty\n"
            "BANK-01,REF-01,1000.00,INR,2025-01-16,Acme\n"
            "BANK-02,REF-02,2000.00,INR,2025-01-16,Globex\n"
        )

        files = {
            "gateway_file": ("gateway.csv", io.BytesIO(gtw_csv.encode("utf-8")), "text/csv"),
            "bank_file": ("bank.csv", io.BytesIO(bank_csv.encode("utf-8")), "text/csv"),
        }

        response = api_client.post("/runs", files=files)
        assert response.status_code == 201
        data = response.json()

        assert "run_id" in data
        assert data["status"] == "COMPLETED"
        assert data["total_records"] == 4
        assert data["matched_count"] == 2
        assert data["exception_count"] == 0

    def test_post_runs_json_endpoint(self, api_client):
        payload = {
            "source_records": [
                {
                    "payment_id": "GTW-J1",
                    "merchant_txn_ref": "REF-J1",
                    "amount": "500.00",
                    "currency": "INR",
                    "created_at": "2025-01-15",
                }
            ],
            "target_records": [
                {
                    "bank_reference": "BANK-J1",
                    "narration": "REF-J1",
                    "settlement_amount": "500.00",
                    "currency": "INR",
                    "posting_date": "2025-01-16",
                }
            ],
        }

        response = api_client.post("/runs/json", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "COMPLETED"
        assert data["matched_count"] == 1

    def test_get_runs_and_get_run_by_id(self, api_client):
        # Create a run first
        payload = {
            "source_records": [
                {"payment_id": "G-1", "amount": "100.00", "created_at": "2025-01-01"}
            ],
            "target_records": [
                {"bank_reference": "B-1", "settlement_amount": "100.00", "posting_date": "2025-01-01"}
            ],
        }
        res_post = api_client.post("/runs/json", json=payload)
        run_id = res_post.json()["run_id"]

        # List runs
        res_list = api_client.get("/runs")
        assert res_list.status_code == 200
        runs_data = res_list.json()
        assert runs_data["total"] >= 1
        assert any(r["run_id"] == run_id for r in runs_data["runs"])

        # Get run by ID
        res_get = api_client.get(f"/runs/{run_id}")
        assert res_get.status_code == 200
        run_data = res_get.json()
        assert run_data["run_id"] == run_id
        assert run_data["status"] == "COMPLETED"

    def test_unknown_run_returns_404(self, api_client):
        response = api_client.get("/runs/NON-EXISTENT-RUN")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_run_results_and_filtering(self, api_client):
        # Ingest synthetic files
        gtw_path = Path("data/synthetic/gateway.csv")
        bank_path = Path("data/synthetic/bank.csv")

        if not (gtw_path.exists() and bank_path.exists()):
            pytest.skip("Synthetic CSVs missing")

        with open(gtw_path, "rb") as gf, open(bank_path, "rb") as bf:
            res_post = api_client.post(
                "/runs",
                files={
                    "gateway_file": ("gateway.csv", gf, "text/csv"),
                    "bank_file": ("bank.csv", bf, "text/csv"),
                },
            )
        run_id = res_post.json()["run_id"]

        # Get all results
        res_results = api_client.get(f"/runs/{run_id}/results")
        assert res_results.status_code == 200
        data = res_results.json()
        assert data["total"] > 30
        assert len(data["results"]) > 0

        # Filter by outcome=MATCHED
        res_matched = api_client.get(f"/runs/{run_id}/results?outcome=MATCHED")
        assert res_matched.status_code == 200
        assert all(r["outcome"] == "MATCHED" for r in res_matched.json()["results"])

        # Filter by outcome=EXCEPTION
        res_exc = api_client.get(f"/runs/{run_id}/results?outcome=EXCEPTION")
        assert res_exc.status_code == 200
        assert all(r["outcome"] == "EXCEPTION" for r in res_exc.json()["results"])

    def test_get_run_exceptions(self, api_client):
        gtw_path = Path("data/synthetic/gateway.csv")
        bank_path = Path("data/synthetic/bank.csv")

        if not (gtw_path.exists() and bank_path.exists()):
            pytest.skip("Synthetic CSVs missing")

        with open(gtw_path, "rb") as gf, open(bank_path, "rb") as bf:
            res_post = api_client.post(
                "/runs",
                files={
                    "gateway_file": ("gateway.csv", gf, "text/csv"),
                    "bank_file": ("bank.csv", bf, "text/csv"),
                },
            )
        run_id = res_post.json()["run_id"]

        res_exc = api_client.get(f"/runs/{run_id}/exceptions")
        assert res_exc.status_code == 200
        data = res_exc.json()
        assert data["total"] >= 10

    def test_get_run_candidates(self, api_client):
        gtw_path = Path("data/synthetic/gateway.csv")
        bank_path = Path("data/synthetic/bank.csv")

        if not (gtw_path.exists() and bank_path.exists()):
            pytest.skip("Synthetic CSVs missing")

        with open(gtw_path, "rb") as gf, open(bank_path, "rb") as bf:
            res_post = api_client.post(
                "/runs",
                files={
                    "gateway_file": ("gateway.csv", gf, "text/csv"),
                    "bank_file": ("bank.csv", bf, "text/csv"),
                },
            )
        run_id = res_post.json()["run_id"]

        res_cand = api_client.get(f"/runs/{run_id}/candidates")
        assert res_cand.status_code == 200
        cand_data = res_cand.json()
        assert cand_data["total"] == 9
        first_cand = cand_data["candidates"][0]
        assert "anchor_record_id" in first_cand
        assert "candidate_options" in first_cand
        assert "validation_status" in first_cand
        assert len(first_cand["candidate_options"]) > 0

    def test_get_run_metrics(self, api_client):
        payload = {
            "source_records": [
                {"payment_id": "G-1", "amount": "100.00", "created_at": "2025-01-01"}
            ],
            "target_records": [
                {"bank_reference": "B-1", "settlement_amount": "100.00", "posting_date": "2025-01-01"}
            ],
        }
        res_post = api_client.post("/runs/json", json=payload)
        run_id = res_post.json()["run_id"]

        res_metrics = api_client.get(f"/runs/{run_id}/metrics")
        assert res_metrics.status_code == 200
        metrics = res_metrics.json()
        assert metrics["run_id"] == run_id
        assert metrics["total_records"] == 2
        assert metrics["matched_count"] == 1
        assert metrics["match_rate"] == 100.0
        assert metrics["total_reconciled_amount"] == "100.00"

    def test_get_run_audit_logs(self, api_client):
        payload = {
            "source_records": [
                {"payment_id": "G-1", "amount": "100.00", "created_at": "2025-01-01"}
            ],
            "target_records": [
                {"bank_reference": "B-1", "settlement_amount": "100.00", "posting_date": "2025-01-01"}
            ],
        }
        res_post = api_client.post("/runs/json", json=payload)
        run_id = res_post.json()["run_id"]

        res_logs = api_client.get(f"/runs/{run_id}/audit-logs")
        assert res_logs.status_code == 200
        logs = res_logs.json()
        assert len(logs) >= 5
        event_types = [l["event_type"] for l in logs]
        assert "RUN_CREATED" in event_types
        assert "RUN_COMPLETED" in event_types

    def test_export_csv_and_json(self, api_client):
        payload = {
            "source_records": [
                {"payment_id": "G-1", "amount": "500.00", "created_at": "2025-01-01"}
            ],
            "target_records": [
                {"bank_reference": "B-1", "settlement_amount": "500.00", "posting_date": "2025-01-01"}
            ],
        }
        res_post = api_client.post("/runs/json", json=payload)
        run_id = res_post.json()["run_id"]

        # CSV export
        res_csv = api_client.get(f"/runs/{run_id}/export?format=csv")
        assert res_csv.status_code == 200
        assert res_csv.headers["content-type"].startswith("text/csv")
        assert "relationship_id,source_record_ids" in res_csv.text

        # JSON export
        res_json = api_client.get(f"/runs/{run_id}/export?format=json")
        assert res_json.status_code == 200
        assert res_json.headers["content-type"].startswith("application/json")
        json_data = res_json.json()
        assert "results" in json_data
        assert len(json_data["results"]) == 1

    def test_export_invalid_format_returns_400(self, api_client):
        payload = {
            "source_records": [{"payment_id": "G-1", "amount": "100.00", "created_at": "2025-01-01"}],
            "target_records": [{"bank_reference": "B-1", "settlement_amount": "100.00", "posting_date": "2025-01-01"}],
        }
        res_post = api_client.post("/runs/json", json=payload)
        run_id = res_post.json()["run_id"]

        res = api_client.get(f"/runs/{run_id}/export?format=xml")
        assert res.status_code == 400
        assert "unsupported export format" in res.json()["detail"].lower()

    def test_malformed_csv_upload_returns_400(self, api_client):
        files = {
            "gateway_file": ("gateway.csv", io.BytesIO(b"bad_csv_header\nonly_one_col"), "text/csv"),
            "bank_file": ("bank.csv", io.BytesIO(b""), "text/csv"),
        }
        response = api_client.post("/runs", files=files)
        assert response.status_code == 400
        assert "failed" in response.json()["detail"].lower()

    def test_get_run_records_and_filtering(self, api_client):
        payload = {
            "source_records": [
                {"payment_id": "G-REC-1", "amount": "150.00", "created_at": "2025-01-01"}
            ],
            "target_records": [
                {"bank_reference": "B-REC-1", "settlement_amount": "150.00", "posting_date": "2025-01-01"}
            ],
        }
        res_post = api_client.post("/runs/json", json=payload)
        assert res_post.status_code == 201
        run_id = res_post.json()["run_id"]


        # 1. Fetch all records
        res_all = api_client.get(f"/runs/{run_id}/records")
        assert res_all.status_code == 200
        data_all = res_all.json()
        assert data_all["total"] == 2
        sources = {r["source"] for r in data_all["records"]}
        assert sources == {"GATEWAY", "BANK"}

        # 2. Filter by GATEWAY
        res_gtw = api_client.get(f"/runs/{run_id}/records?source=GATEWAY")
        assert res_gtw.status_code == 200
        data_gtw = res_gtw.json()
        assert data_gtw["total"] == 1
        assert data_gtw["records"][0]["record_id"] == "G-REC-1"

        # 3. Filter by BANK
        res_bank = api_client.get(f"/runs/{run_id}/records?source=BANK")
        assert res_bank.status_code == 200
        data_bank = res_bank.json()
        assert data_bank["total"] == 1
        assert data_bank["records"][0]["record_id"] == "B-REC-1"

        # 4. Unknown run returns 404
        res_404 = api_client.get("/runs/RUN-NONEXISTENT/records")
        assert res_404.status_code == 404

    def test_dashboard_correction_and_rules_elements(self, api_client):
        res = api_client.get("/")
        assert res.status_code == 200
        html = res.text

        # Tab button & rerun button
        assert 'data-tab="tab-corrections"' in html
        assert 'id="btnRerunWithRules"' in html
        assert 'id="btnTabRerunWithRules"' in html
        assert 'id="btnOpenAddRuleModal"' in html
        assert 'id="statActiveRules"' in html
        assert 'id="statCorrections"' in html
        assert 'id="ruleScopeIndicator"' in html

        # Table Action headers
        assert "<th>Action</th>" in html

        # Panes & tables
        assert 'id="tab-corrections"' in html
        assert 'id="correctionsTable"' in html
        assert 'id="rulesTable"' in html
        assert 'id="ruleImpactContainer"' in html

        # Modals
        assert 'id="correctionModal"' in html
        assert 'id="origRelId"' in html
        assert 'id="corrOutcome"' in html
        assert 'id="corrExceptionType"' in html
        assert 'id="corrReason"' in html
        assert 'id="corrGenerateRule"' in html
        assert 'id="corrSourcePicker"' in html
        assert 'id="corrTargetPicker"' in html
        assert 'id="rerunConfirmModal"' in html
        assert 'id="correctionDetailModal"' in html
        assert 'id="addRuleModal"' in html
        assert 'id="ruleName"' in html
        assert 'id="ruleCounterparty"' in html
        assert 'id="rulePreviewContent"' or 'id="rulePreviewBody"' in html
        assert 'id="btnValidateRule"' in html
        assert 'id="btnSubmitAddRule"' in html
        assert 'id="ruleDetailModal"' in html

        # Cache-busting version check
        assert 'styles.css?v=202609' in html
        assert 'app.js?v=202609' in html

    def test_static_assets_contain_correction_and_rule_handlers(self, api_client):
        res_js = api_client.get("/static/app.js")
        assert res_js.status_code == 200
        js = res_js.text
        assert "openCorrectionModal" in js
        assert "submitCorrectionForm" in js
        assert "openRerunModal" in js
        assert "executeRerun" in js
        assert "renderRuleImpact" in js
        assert "renderRulesTable" in js
        assert "renderCorrectionsHistory" in js
        assert "submitCorrection" in js
        assert "rerunWithRules" in js
        assert "RULE APPLIED" in js
        assert "openAddRuleModal" in js
        assert "closeAddRuleModal" in js
        assert "updateRulePreview" in js
        assert "validateRuleForm" in js
        assert "submitAddRuleForm" in js
        assert "openRuleDetailModal" in js

        res_css = api_client.get("/static/styles.css")
        assert res_css.status_code == 200
        css = res_css.text
        assert ".btn-correct" in css
        assert ".modal-lg" in css
        assert ".original-result-box" in css
        assert ".record-picker-container" in css
        assert ".impact-card" in css
        assert ".impact-table" in css
        assert ".switch-toggle" in css
        assert ".badge-pill-purple" in css
        assert ".panel-header-banner" in css
        assert ".rule-preview-card" in css

    def test_structured_rule_validation_and_creation(self, api_client):
        # 1. Validation of valid rule definition
        valid_payload = {
            "name": "Merchant Gamma Tolerance Rule",
            "description": "Allows INR 2 tolerance for Merchant Gamma",
            "source_counterparty_pattern": "Merchant Gamma",
            "currency": "INR",
            "max_amount_difference": "2.00",
            "max_settlement_delay_days": 1,
            "target_action": "PREFER_CANDIDATE",
            "resulting_outcome": "MATCHED",
            "confidence": 1.0,
            "is_active": True,
        }
        res_val = api_client.post("/rules/validate", json=valid_payload)
        assert res_val.status_code == 200
        val_data = res_val.json()
        assert val_data["valid"] is True
        assert "Merchant Gamma" in val_data["summary"]

        # 2. Validation of invalid rule with record ID memorization
        bad_id_payload = dict(valid_payload)
        bad_id_payload["source_counterparty_pattern"] = "GTW-101"
        res_val_bad = api_client.post("/rules/validate", json=bad_id_payload)
        assert res_val_bad.status_code == 200
        assert res_val_bad.json()["valid"] is False
        assert any("memorize exact record ids" in e.lower() for e in res_val_bad.json()["errors"])

        # 3. Validation of rule with no predicates
        empty_pred_payload = {
            "name": "Empty Predicate Rule",
            "target_action": "PREFER_CANDIDATE",
            "resulting_outcome": "MATCHED",
            "confidence": 1.0,
        }
        res_val_empty = api_client.post("/rules/validate", json=empty_pred_payload)
        assert res_val_empty.status_code == 200
        assert res_val_empty.json()["valid"] is False

        # 4. Successful rule creation
        res_create = api_client.post("/rules", json=valid_payload)
        assert res_create.status_code == 201
        created_rule = res_create.json()
        assert created_rule["rule_id"].startswith("RULE-")
        assert created_rule["name"] == "Merchant Gamma Tolerance Rule"
        assert created_rule["is_active"] is True
        rule_id = created_rule["rule_id"]

        # 5. Rule appears in GET /rules
        res_list = api_client.get("/rules")
        assert res_list.status_code == 200
        rule_ids = [r["rule_id"] for r in res_list.json()["rules"]]
        assert rule_id in rule_ids

        # 6. Rule can be toggled to inactive
        res_toggle = api_client.post(f"/rules/{rule_id}/toggle", json={"is_active": False})
        assert res_toggle.status_code == 200
        assert res_toggle.json()["is_active"] is False

        # 7. Check GET /rules?active_only=true excludes inactive rule
        res_active_only = api_client.get("/rules?active_only=true")
        active_ids = [r["rule_id"] for r in res_active_only.json()["rules"]]
        assert rule_id not in active_ids

        # Toggle back to active
        api_client.post(f"/rules/{rule_id}/toggle", json={"is_active": True})

        # 8. Creation rejection for exact record ID
        res_create_bad = api_client.post("/rules", json=bad_id_payload)
        assert res_create_bad.status_code == 422

    def test_delete_run_endpoint_success_and_isolation(self, api_client):
        # Create Run 1
        res1 = api_client.post(
            "/runs/json",
            json={
                "source_records": [{"payment_id": "G-1", "amount": "100.00", "created_at": "2025-01-01"}],
                "target_records": [{"bank_reference": "B-1", "settlement_amount": "100.00", "posting_date": "2025-01-01"}],
            },
        )
        run1_id = res1.json()["run_id"]

        # Create Run 2
        res2 = api_client.post(
            "/runs/json",
            json={
                "source_records": [{"payment_id": "G-2", "amount": "200.00", "created_at": "2025-01-01"}],
                "target_records": [{"bank_reference": "B-2", "settlement_amount": "200.00", "posting_date": "2025-01-01"}],
            },
        )
        run2_id = res2.json()["run_id"]

        # Delete Run 1
        del_res = api_client.delete(f"/runs/{run1_id}")
        assert del_res.status_code == 200
        del_data = del_res.json()
        assert del_data["status"] == "DELETED"
        assert del_data["run_id"] == run1_id

        # Verify Run 1 is no longer found
        assert api_client.get(f"/runs/{run1_id}").status_code == 404
        assert api_client.get(f"/runs/{run1_id}/records").status_code == 404
        assert api_client.get(f"/runs/{run1_id}/results").status_code == 404

        # Repeated delete returns 404
        assert api_client.delete(f"/runs/{run1_id}").status_code == 404

        # Run 2 remains completely intact
        res_run2 = api_client.get(f"/runs/{run2_id}")
        assert res_run2.status_code == 200
        assert res_run2.json()["run_id"] == run2_id

    def test_delete_run_endpoint_404(self, api_client):
        res = api_client.delete("/runs/NON-EXISTENT-RUN")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()

    def test_delete_rule_endpoint_success(self, api_client):
        # Create a rule
        rule_payload = {
            "name": "Deletion Test Rule",
            "source_counterparty_pattern": "TestCP",
            "resulting_outcome": "MATCHED",
            "target_action": "PREFER_CANDIDATE",
        }
        res_create = api_client.post("/rules", json=rule_payload)
        assert res_create.status_code == 201
        rule_id = res_create.json()["rule_id"]

        # Delete rule
        del_res = api_client.delete(f"/rules/{rule_id}")
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "DELETED"
        assert del_res.json()["rule_id"] == rule_id

        # Verify rule is gone
        assert api_client.get(f"/rules/{rule_id}").status_code == 404

        # Repeated delete returns 404
        assert api_client.delete(f"/rules/{rule_id}").status_code == 404

    def test_delete_rule_endpoint_404(self, api_client):
        res = api_client.delete("/rules/NON-EXISTENT-RULE")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()

    def test_delete_run_partial_chroma_failure_handling(self, api_client):
        # Create a run
        res = api_client.post(
            "/runs/json",
            json={
                "source_records": [{"payment_id": "G-FAIL", "amount": "100.00", "created_at": "2025-01-01"}],
                "target_records": [{"bank_reference": "B-FAIL", "settlement_amount": "100.00", "posting_date": "2025-01-01"}],
            },
        )
        run_id = res.json()["run_id"]

        # Simulate Chroma failure on active service instance
        service = app.dependency_overrides[get_service]()
        if service.vector_store:
            def broken_delete_run(r_id):
                raise RuntimeError("Chroma connection timed out")
            service.vector_store.delete_run = broken_delete_run

        del_res = api_client.delete(f"/runs/{run_id}")
        assert del_res.status_code == 200
        del_data = del_res.json()
        assert del_data["status"] == "PARTIALLY_DELETED"
        assert del_data["chroma_deleted"] is False
        assert "ChromaDB index cleanup failed" in del_data["warning"]




