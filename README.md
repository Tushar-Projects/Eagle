# 🦅 Eagle — AI Financial Reconciliation Engine

[![CI Tests](https://img.shields.io/badge/pytest-242%20passed-brightgreen.svg)]()
[![Benchmark F1](https://img.shields.io/badge/Benchmark%20F1-100.0%25-blue.svg)]()
[![Architecture](https://img.shields.io/badge/Architecture-Deterministic%20Core%20%2B%20AI%20Classifier-indigo.svg)]()
[![License](https://img.shields.io/badge/License-Proprietary-gray.svg)]()

> **Eagle** is a high-assurance financial reconciliation and exception classification system designed for mission-critical ledger settlement between payment gateways, merchant systems, and banking networks.

---

## 1. Executive Summary & Problem Statement

Financial ledger reconciliation across multiple transaction sources (e.g., Payment Gateways vs. Core Banking Systems) is prone to:
- **Topology Mismatches**: Batch payouts (1:N), split settlements, and consolidated merchant deposits (N:1).
- **Financial Variations**: Small rounding discrepancies, variable merchant fee deductions, and currency conversions.
- **Timing & Settlement Delays**: Weekend processing windows, bank holidays, and cut-off delays.
- **Data Ambiguity & Decoys**: Competing transaction candidate pools that cannot be disambiguated by simple SQL joins alone.

**Why Pure LLM Reconciliation Fails**: Traditional generative LLMs cannot be trusted to perform financial arithmetic or invent transaction IDs. They suffer from hallucinations, non-deterministic outputs, floating-point drift, and inability to enforce single-assignment accounting invariants.

**The Eagle Solution**: Eagle combines a **deterministic multi-stage reconciliation core** with **bounded semantic AI exception classification** and an uncompromising **Global Commit Safety Validator**. The AI model never invents participant IDs, never overrides financial facts, and is restricted strictly to choosing within deterministically proven candidate options.

---

## 2. High-Level Architecture

```mermaid
flowchart TD
    subgraph INGESTION["1. Ingestion Layer"]
        CSV[Gateway / Bank CSV] --> PARSE[CsvExtractor / JsonExtractor]
        JSON[Direct JSON Payloads] --> PARSE
        PARSE --> CANON[CanonicalRecord (Decimal Precision)]
    end

    subgraph ENGINE["2. Deterministic Reconciliation Core"]
        CANON --> S1[Stage 1: Exact Reference Match]
        S1 --> S2[Stage 2: Normalized Match]
        S2 --> S3[Stage 3: Amount + Date Tolerance Match]
        S3 --> S4[Stage 4: Fee & Rounding Matching]
        S4 --> S5[Stage 5: 1:N & N:1 Aggregation Engine]
        S5 --> DET_RES[Committed Deterministic Results]
        S5 --> CAND_EVID[Anchor-Based Decision Groups]
    end

    subgraph AI_LAYER["3. Semantic AI Classification Layer"]
        CAND_EVID --> CASE_GEN[Structured Candidate Options]
        CASE_GEN --> LLM[Local llama-server / MockProvider]
        LLM --> DECISION[Structured Decision (Index Selection)]
        DECISION --> IND_VAL[Individual Decision Validator]
    end

    subgraph SAFETY["4. Global Safety Commit Layer"]
        IND_VAL --> GCV[GlobalCommitValidator]
        DET_RES --> GCV
        GCV -->|Safe & Disjoint| COMMIT[Committed Results]
        GCV -->|Collision / Violation| REJECT[Rejected / Failed Case]
    end

    subgraph PERSISTENCE["5. Persistence & Delivery"]
        COMMIT --> DB[(SQLite Database)]
        REJECT --> DB
        DB --> API[FastAPI REST Server]
        API --> UI[Interactive Dashboard]
        API --> EXP[CSV / JSON Certified Exports]
    end
```

---

## 3. End-to-End Pipeline & Safety Invariants

### Deterministic Matching Stages
1. **Stage 1 (Exact Match)**: Exact transaction reference, matching amount, matching currency.
2. **Stage 2 (Normalized Match)**: Case-insensitive, hyphen-stripped reference matching.
3. **Stage 3 (Financial & Timing Match)**: Date-window tolerance (0 to 5 days settlement delay) and exact amounts.
4. **Stage 4 (Fee & Rounding Match)**: Explicit merchant fee deduction detection (`source - fee == bank`) and rounding tolerance (`±0.01` to `±0.50`).
5. **Stage 5 (1:N & N:1 Aggregation)**: Combinatorial subset sum solver discovering exact and near-exact multi-record split settlements.

### Anchor-Based Candidate Decision Groups
When multiple competing subsets sum to the same amount, Eagle bundles them into **Anchor-Based Decision Groups** (`CandidateRelationshipEvidence`). Each group contains:
- An anchor transaction record.
- A discrete, bounded array of legal candidate options (`source_record_ids` $\to$ `target_record_ids`).
- Contextual timing and amount evidence.

### AI Role & Hardened Boundaries
The AI provider (external `llama-server` running Gemma or offline deterministic `MockProvider`) is invoked **only** to evaluate semantic counterparty notes, merchant narrations, or tie-break candidate pools:
- **No Hallucinated IDs**: The model selects an option by integer index (`selected_candidate_index`). It cannot output raw transaction IDs.
- **No Amount Overrides**: The reconciled amount is derived strictly from the canonical source records.
- **Explicit Abstentions**: If ambiguous, the model selects `selected_candidate_index = None` (e.g., `POSSIBLE_DUPLICATE`), resulting in a safe exception without a fake counterparty.

### GlobalCommitValidator & Single-Assignment Invariant
Before any AI proposal enters final results, `GlobalCommitValidator` verifies:
- **Source Single-Assignment**: No source record can participate in more than one committed relationship.
- **Target Single-Assignment**: No target record can participate in more than one committed relationship.
- **Disjoint Partitioning**: Any candidate colliding with a previously committed relationship is immediately **REJECTED** and logged as a safety violation.

---

## 4. Status Semantics

| Status | Meaning |
|---|---|
| **`COMMITTED`** | Verified relationship selected from candidate options, passed safety validation, and entered final results. |
| **`ABSTAINED`** | The AI explicitly returned `selected_candidate_index = None`. The decision was valid and committed as an orphan exception. |
| **`REJECTED`** | Candidate selection was rejected by `GlobalCommitValidator` or individual safety checks (collision, amount mismatch, invalid topology). |
| **`CLASSIFICATION_FAILED`** | AI structured response could not be parsed or timed out after retries were exhausted. |
| **`UNRESOLVED`** | Candidate evidence exists, but no valid committed relationship resulted. |
| **`REVIEW REQUIRED`** | Human operator review flag (`flag_for_review = True`) for audit review. |

---

## 5. Reviewer Quick-Start Guide

### Prerequisites
- Python 3.11+
- Windows PowerShell or Unix/macOS Bash

### Step 1: Environment Setup

```powershell
# 1. Clone / navigate to repository root
cd d:\Development\buildathon\Eagle

# 2. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate       # On Linux/macOS: source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -e .
```

### Step 2: Configure Environment

Copy the template configuration:
```powershell
cp .env.example .env
```

For **100% offline deterministic execution** (zero external dependencies):
```env
AI_PROVIDER=mock
```

For **local LLM execution** via externally managed `llama-server`:
```env
AI_PROVIDER=llama_server
AI_MODEL=google_gemma-4-E2B-it-Q8_0
LLAMA_SERVER_URL=http://127.0.0.1:8000
```

*(If running local LLM, start `llama-server.exe` in a separate terminal:)*
```powershell
llama-server.exe -m "path\to\google_gemma-4-E2B-it-Q8_0.gguf" --port 8000
```

### Step 3: Launch Interactive Demo

Run the unified demo launcher:
```powershell
python run_demo.py
```

The script will:
1. Validate dependencies and AI provider connectivity.
2. Resolve port assignments (automatically avoiding collisions with `llama-server`).
3. Start the FastAPI server.
4. Launch the **Eagle Web Dashboard** in your default browser at `http://127.0.0.1:8000/`.

---

## 6. Demonstration Workflow

Once the dashboard opens:
1. Click **"New Reconciliation"** in the top header.
2. Click **"⚡ Quick-Load Synthetic Sample Data"** to automatically populate sample Gateway & Bank batches.
3. Click **"Run Reconciliation"**.
4. **Inspect KPI Summary**: Real-time cards displaying match rate, exception rate, orphan volume, and total reconciled amounts.
5. **Inspect All Results**: Search and filter by outcome (`MATCHED` vs `EXCEPTION`) and topology (`1:1`, `1:N`, `N:1`).
6. **Inspect Exceptions**: Review high/medium/low severity exceptions color-coded by category.
7. **Inspect AI Candidate Inspector**: Review candidate trees, deterministic search spaces, AI selections, and `GlobalCommitValidator` verdicts.
8. **Inspect Audit Trail**: Review step-by-step pipeline timestamps (`RUN_CREATED` $\to$ `RUN_COMPLETED`).
9. **Export Results**: Click **"Export CSV"** or **"Export JSON"** to download certified reconciliation files.

---

## 7. REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Server liveness and active AI provider info |
| `POST` | `/runs` | Multipart CSV file upload & reconciliation execution |
| `POST` | `/runs/json` | Direct JSON payload reconciliation execution |
| `GET` | `/runs` | List historical runs with pagination |
| `GET` | `/runs/{run_id}` | Retrieve run metadata and summary |
| `GET` | `/runs/{run_id}/results` | Query reconciled relationships with filtering |
| `GET` | `/runs/{run_id}/exceptions` | Query exceptions filtered by severity and type |
| `GET` | `/runs/{run_id}/candidates` | Query candidate pools, AI decisions, and validation verdicts |
| `GET` | `/runs/{run_id}/metrics` | Query operational financial KPI metrics |
| `GET` | `/runs/{run_id}/audit-logs` | Retrieve chronological pipeline audit trail |
| `GET` | `/runs/{run_id}/export?format=csv` | Download CSV reconciliation report |
| `GET` | `/runs/{run_id}/export?format=json` | Download JSON reconciliation report |
| `GET` | `/demo/synthetic-data` | Retrieve packaged synthetic demo datasets |

---

## 8. Verification & Benchmarking

### Running the Full Test Suite
To run all 242 unit, integration, persistence, and reliability hardening tests:
```powershell
python -m pytest -v
```
*Expected Result: `242 passed, 1 warning` in ~6.5 seconds.*

### Running the Synthetic Evaluation Benchmark
To run the evaluation harness against the 38 ground-truth benchmark relationships:
```powershell
$env:AI_PROVIDER="mock"; python -m eagle.evaluation
```

*Benchmark Results*:
```
═══════════════════════════════════════════════════════
              EAGLE RECONCILIATION BENCHMARK
═══════════════════════════════════════════════════════
  Dataset:  38 ground-truth relationships
  Total Predictions: 38

─── RELATIONSHIP DETECTION ───────────────────────────
  True Positives:    38/38
  False Positives:   0
  False Negatives:   0
  Precision:         100.0%
  Recall:            100.0%
  F1 Score:          100.0%

─── CLASSIFICATION ACCURACY ──────────────────────────
  Outcome:           37/38  (97.4%)
  Exception Type:    32/38  (84.2%)
  Relationship Type: 38/38  (100.0%)

─── RECONCILED AMOUNT ────────────────────────────────
  Exact Match:       38/38  (100.0%)
  Within Tolerance:  38/38  (100.0%)
  Mean Abs Error:    ₹0.00

─── DETERMINISTIC vs AI ──────────────────────────────
  Deterministic-Only F1:   86.6%
  Final (Det + AI) F1:     100.0%
  AI Improvement (F1):     +13.4%
═══════════════════════════════════════════════════════
```

---

## 9. Performance Benchmarks

Measured on standard workstation hardware:

| Operation | Latency |
|---|---|
| Health Check (`GET /health`) | **16.5 ms** |
| Sample Data Loading | **3.2 ms** |
| Full Pipeline (81 records, Ingestion $\to$ Core $\to$ AI $\to$ Persistence) | **12.5 ms** |
| KPI Metrics Calculation | **3.5 ms** |
| Reconciled Results Table Query | **3.9 ms** |
| Candidate Tree Query | **3.8 ms** |
| CSV Report Serialization | **3.3 ms** |
| JSON Report Serialization | **2.7 ms** |

---

## 10. Repository Structure

```
Eagle/
├── demo_data/                     # Packaged reviewer datasets
│   ├── bank.csv                   # Sample bank statement ledger
│   ├── gateway.csv                # Sample gateway settlement batch
│   └── README.md                  # Dataset documentation
├── src/
│   └── eagle/
│       ├── agents/                # AI Exception Classifier & LLM Providers
│       │   ├── classifier.py      # AI Classifier & Global Safety Commit
│       │   ├── provider.py        # Abstract LLM provider contract
│       │   ├── _llama_server.py   # Externally managed llama-server client
│       │   └── _mock.py           # Deterministic offline MockProvider
│       ├── api/                   # FastAPI Web & REST Layer
│       │   ├── main.py            # Application factory & static mounts
│       │   ├── routes.py          # REST endpoints
│       │   ├── schemas.py         # Pydantic v2 schemas
│       │   └── static/            # Self-contained Web Dashboard SPA
│       │       ├── index.html     # Semantic HTML5 markup
│       │       ├── styles.css     # Dark financial controller theme
│       │       └── app.js         # Reactive UI client controller
│       ├── core/                  # Configuration & logging
│       ├── export/                # CSV & JSON export serializers
│       ├── extraction/            # CSV & JSON extractors
│       ├── models/                # Frozen domain contracts
│       ├── reconciliation/        # Deterministic multi-stage matching engine
│       │   ├── engine.py          # Stage 1-5 coordinator
│       │   ├── aggregation.py     # 1:N / N:1 subset-sum solver
│       │   └── matching.py        # Predicates for exact, fee, rounding
│       ├── services/              # Application service boundary
│       │   └── reconciliation_service.py
│       └── storage/               # SQLite persistence layer
│           ├── database.py        # ACID connection & schema
│           └── repository.py      # Run, result, candidate, & audit CRUD
├── tests/                         # 242 automated pytest tests
├── run_demo.py                    # Reviewer interactive launcher
├── README.md                      # Reviewer documentation
├── requirements.txt               # Python package dependencies
├── pyproject.toml                 # Project packaging metadata
├── .env.example                   # Environment configuration template
└── .gitignore                     # Git exclusion rules
```

---

## 11. Known Limitations & Deliberately Deferred Features

To maintain high stability and zero scope creep during the buildathon submission window, the following capabilities were deliberately deferred to post-submission roadmaps:
- **Cloud Deployment & Multi-Tenancy**: The current distribution is optimized for local workstation execution and reviewer demonstration.
- **Model Migration to Qwen 3.5 9B**: Evaluated in architectural audits; deferred to avoid benchmark overfitting.
- **OCR / Vision Ingestion**: PDF invoice parsing is staged for future enterprise ingestion pipelines.
- **Vector Search (ChromaDB)**: Retrieval augmented rule synthesis is deferred to Phase 2.
