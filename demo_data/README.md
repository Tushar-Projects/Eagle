# Eagle Demo Datasets

This directory contains packaged synthetic datasets designed for demonstrating the Eagle Financial Reconciliation Engine.

## Files

1. **`gateway.csv`**: Payment Gateway Settlement Batch (41 records)
   - Columns: `payment_id`, `merchant_txn_ref`, `amount`, `currency`, `created_at`, `merchant_name`, `gross_amount`, `fee`, `net_amount`
   - Features: Standard payments, refunds, fee deductions, rounding variations, split settlements, duplicate submissions, and missing counterpart records.

2. **`bank.csv`**: Core Banking Statement Ledger (42 records)
   - Columns: `bank_reference`, `narration`, `settlement_amount`, `currency`, `posting_date`, `counterparty`, `fee`
   - Features: Settlement delays, grouped deposits (1:N and N:1), currency mismatches, bank charges, and unallocated deposits.

## Usage

These files can be loaded into the Eagle dashboard via:
- **Interactive UI**: Click **"⚡ Quick-Load Synthetic Sample Data"** in the **New Reconciliation** modal.
- **REST API**: Upload directly via `POST /runs` multipart file upload.
- **CLI**: Reconcile via `scripts/run_evaluation.py`.
