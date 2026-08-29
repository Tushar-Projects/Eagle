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
