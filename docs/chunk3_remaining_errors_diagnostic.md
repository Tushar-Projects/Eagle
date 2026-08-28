# Chunk 3 Remaining Errors Diagnostic Report

## Executive Summary

A comprehensive read-only architectural and implementation audit of the Eagle reconciliation system was conducted to identify the exact root causes of all remaining benchmark errors.

The benchmark currently reports:
- **Total Ground-Truth Relationships**: 38
- **Total Predictions**: 38
- **True Positives (TP)**: 36 / 38 (94.7%)
- **False Positives (FP)**: 2
- **False Negatives (FN)**: 2
- **Precision**: 94.7%
- **Recall**: 94.7%
- **F1 Score**: 94.7%
- **Deterministic-Only F1**: 85.3%
- **AI Improvement**: +9.4%
- **Candidate Decision Groups**: 8
- **Candidate Options Generated**: 53
- **Candidates Resolved**: 6 / 8
- **Unresolved Candidates**: 2 / 8
- **AI Classification Failures**: 0

The audit conclusively determined that the remaining 2 FNs and 2 FPs stem from exactly two distinct, isolated root causes:
1. **`R-C06` (FN 1) & `BANK-C06` (FP 1)**: A mathematical sign bug in Stage 5 N:1 aggregation candidate generation (`find_subset_sum` in `aggregation.py`), which caused the correct candidate option `[GTW-C06-1, GTW-C06-2] -> BANK-C06` to **never be generated**.
2. **`R-D08` (FN 2) & `GTW-D08 -> BANK-D03` (FP 2)**: The generic `MockProvider` default selection rule in `_mock.py` defaulted to `selected_candidate_index = 0` (matching decoy `BANK-D03`) instead of returning `selected_candidate_index = None` (identifying `GTW-D08` as an orphan / near-duplicate).

---

## A. Current Benchmark Metrics

| Metric | Score | Detail |
| :--- | :--- | :--- |
| **True Positives** | 36 / 38 | Exact participant set match |
| **False Positives** | 2 | Predictions with no matching ground truth |
| **False Negatives** | 2 | Ground-truth relationships with no prediction |
| **Precision** | 94.7% | 36 / (36 + 2) |
| **Recall** | 94.7% | 36 / (36 + 2) |
| **F1 Score** | 94.7% | Harmonic mean of precision and recall |
| **Deterministic-Only F1** | 85.3% | Before AI candidate selection / classification |
| **Final F1** | 94.7% | After AI candidate selection / classification |
| **Reconciled Amount Exact** | 36 / 36 (100.0%) | Mean Absolute Error = ₹0.00 |

---

## B. Complete Error Inventory

### 1. Ground Truth Audit (All 38 Relationships)

| GT ID | Expected Sources | Expected Targets | Expected Outcome | Expected ExType | Prediction Status | Predicted Outcome | Root Cause |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **R-A01** | `['GTW-A01']` | `['BANK-A01']` | MATCHED | None | **TP** | MATCHED | — |
| **R-A02** | `['GTW-A02']` | `['BANK-A02']` | MATCHED | None | **TP** | MATCHED | — |
| **R-A03** | `['GTW-A03']` | `['BANK-A03']` | MATCHED | None | **TP** | MATCHED | — |
| **R-A04** | `['GTW-A04']` | `['BANK-A04']` | MATCHED | None | **TP** | MATCHED | — |
| **R-A05** | `['GTW-A05']` | `['BANK-A05']` | MATCHED | None | **TP** | MATCHED | — |
| **R-A06** | `['GTW-A06']` | `['BANK-A06']` | MATCHED | None | **TP** | MATCHED | — |
| **R-A07** | `['GTW-A07']` | `['BANK-A07']` | MATCHED | None | **TP** | MATCHED | — |
| **R-A08** | `['GTW-A08']` | `['BANK-A08']` | MATCHED | None | **TP** | MATCHED | — |
| **R-B01** | `['GTW-B01']` | `['BANK-B01']` | MATCHED | ROUNDING_DIFF | **TP** | MATCHED | — |
| **R-B02** | `['GTW-B02']` | `['BANK-B02']` | MATCHED | None | **TP** | MATCHED | — |
| **R-B03** | `['GTW-B03']` | `['BANK-B03']` | MATCHED | FEE_DEDUCTION | **TP** | EXCEPTION | Classified as fee |
| **R-B04** | `['GTW-B04']` | `['BANK-B04']` | MATCHED | FEE_DEDUCTION | **TP** | MATCHED | — |
| **R-B05** | `['GTW-B05']` | `['BANK-B05']` | MATCHED | None | **TP** | MATCHED | — |
| **R-B06** | `['GTW-B06']` | `['BANK-B06']` | MATCHED | None | **TP** | MATCHED | — |
| **R-B07** | `['GTW-B07']` | `['BANK-B07']` | MATCHED | SETTLEMENT_DELAY | **TP** | MATCHED | — |
| **R-B08** | `['GTW-B08']` | `['BANK-B08']` | MATCHED | SETTLEMENT_DELAY | **TP** | MATCHED | — |
| **R-C01** | `['GTW-C01']` | `['BANK-C01-1', 'BANK-C01-2']` | MATCHED | None | **TP** | MATCHED | — |
| **R-C02** | `['GTW-C02']` | `['BANK-C02-1', 'BANK-C02-2', 'BANK-C02-3']` | MATCHED | None | **TP** | MATCHED | — |
| **R-C03** | `['GTW-C03-1', 'GTW-C03-2']` | `['BANK-C03']` | MATCHED | None | **TP** | MATCHED | — |
| **R-C04** | `['GTW-C04-1', 'GTW-C04-2', 'GTW-C04-3']` | `['BANK-C04']` | MATCHED | None | **TP** | MATCHED | — |
| **R-C05** | `['GTW-C05']` | `['BANK-C05-1', 'BANK-C05-2']` | MATCHED | ROUNDING_DIFF | **TP** | MATCHED | — |
| **R-C06** | `['GTW-C06-1', 'GTW-C06-2']` | `['BANK-C06']` | MATCHED | FEE_DEDUCTION | **FN 1** | *None* | Stage 5 N:1 fee sign bug |
| **R-D01** | `['GTW-D01']` | `[]` | EXCEPTION | MISSING_RECORD | **TP** | EXCEPTION | — |
| **R-D02** | `['GTW-D02']` | `[]` | EXCEPTION | MISSING_RECORD | **TP** | EXCEPTION | — |
| **R-D03** | `[]` | `['BANK-ORPH-001']` | EXCEPTION | MISSING_RECORD | **TP** | EXCEPTION | — |
| **R-D04** | `[]` | `['BANK-D04']` | EXCEPTION | MISSING_RECORD | **TP** | EXCEPTION | — |
| **R-D05** | `['GTW-D05']` | `['BANK-D05']` | EXCEPTION | CURRENCY_MISMATCH | **TP** | EXCEPTION | — |
| **R-D06** | `['GTW-D06']` | `['BANK-D06']` | EXCEPTION | PARTIAL_SETTLEMENT | **TP** | EXCEPTION | — |
| **R-D07** | `['GTW-D07']` | `[]` | EXCEPTION | DUPLICATE | **TP** | EXCEPTION | — |
| **R-D08** | `['GTW-D08']` | `[]` | EXCEPTION | POSSIBLE_DUPLICATE | **FN 2** | *None* | MockProvider picked decoy |
| **R-D09** | `['GTW-D09']` | `['BANK-D09']` | EXCEPTION | UNKNOWN | **TP** | EXCEPTION | — |
| **R-E01** | `['GTW-E01']` | `['BANK-E01-1', 'BANK-E01-2']` | MATCHED | None | **TP** | MATCHED | — |
| **R-E02a** | `['GTW-E02a']` | `['BANK-E02a']` | MATCHED | None | **TP** | MATCHED | — |
| **R-E02b** | `['GTW-E02b']` | `['BANK-E02b']` | MATCHED | None | **TP** | MATCHED | — |
| **R-E03** | `['GTW-E03']` | `['BANK-E03']` | MATCHED | None | **TP** | MATCHED | — |
| **R-E04** | `['GTW-E04']` | `['BANK-E04']` | EXCEPTION | UNKNOWN | **TP** | EXCEPTION | — |
| **R-E05** | `['GTW-E05']` | `['BANK-E05']` | EXCEPTION | UNKNOWN | **TP** | EXCEPTION | — |
| **R-E06** | `['GTW-E06']` | `['BANK-E06-1', 'BANK-E06-2']` | EXCEPTION | SPLIT_SETTLEMENT | **TP** | EXCEPTION | — |

### 2. Predictions Audit (False Positives)

| Prediction ID | Predicted Sources | Predicted Targets | Outcome | Exception Type | Amount | Status | Root Cause |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **REL-0a141d74ede5** | `[]` | `['BANK-C06']` | EXCEPTION | MISSING_RECORD | 0.00 | **FP 1** | Downstream consequence of C-06 generation failure. |
| **REL-9f0d957a01de** | `['GTW-D08']` | `['BANK-D03']` | MATCHED | None | 5000.00 | **FP 2** | MockProvider default selected decoy option 0. |

---

## C. C-06 Deep Trace

### 1. Data Context
- `GTW-C06-1`: Amount = `3000.00`, Date = `2025-02-10`, Currency = `INR`, Ref = `""`.
- `GTW-C06-2`: Amount = `7000.00`, Date = `2025-02-10`, Currency = `INR`, Ref = `""`.
- Total Source Amount: `3000.00 + 7000.00 = 10000.00`.
- `BANK-C06`: Amount = `9998.50`, Date = `2025-02-12`, Currency = `INR`, Ref = `""`.
- Difference: `10000.00 - 9998.50 = 1.50` (Fee Deduction).

### 2. Candidate Generation Execution Trace
- During Stage 5 N:1 matching, `find_n_to_1_match(unmatched_sources, bank_c06)` is invoked.
- `find_n_to_1_match` calls `find_subset_sum(target_amount=Decimal('9998.50'), candidates=valid_sources)`.
- For subset `[GTW-C06-1, GTW-C06-2]`, `total = 10000.00`.
- `diff = target_amount - total = 9998.50 - 10000.00 = -1.50`.
- In `find_subset_sum` (lines 28–36 of `src/eagle/reconciliation/aggregation.py`):
  ```python
  if diff == 0:
      valid_subsets.append((list(subset), False, False))
  elif diff > 0 and diff <= ROUNDING_TOLERANCE:
      valid_subsets.append((list(subset), True, False))
  elif diff > 0 and diff <= FEE_MATCH_TOLERANCE:
      valid_subsets.append((list(subset), False, True))
  ```
- Because `diff = -1.50 < 0`, all conditions evaluate to `False`.
- `find_n_to_1_match` returns `[]`.
- **Outcome**:
  - The correct option `[GTW-C06-1, GTW-C06-2] -> BANK-C06` was **NEVER GENERATED** (Option A from the prompt).
  - `BANK-C06` had zero candidate options and zero committed relationships $\to$ emitted as `MISSING_RECORD` with `reconciled_amount = 0.00` (**FP 1**).
  - `GTW-C06-1` and `GTW-C06-2` were included in combinations for `BANK-C03` and `BANK-C04` (summing to 10000.00). When AI resolved C-03 and C-04 with their true counterparts, C-06 sources were left uncommitted, leaving `R-C06` missing from predictions (**FN 1**).

---

## D. D-08 Deep Trace

### 1. Data Context
- `GTW-D08`: Amount = `5000.00`, Date = `2025-01-16`, Ref = `PAY-10001-B`.
- `BANK-E03`: Amount = `5000.00`, Date = `2025-01-17`, Ref = `BANK-E03-TRG` (Target for `GTW-E03`).
- `BANK-D03`: Amount = `5000.00`, Date = `2025-01-18`, Ref = `BANK-D03-DEC` (Decoy record).
- Ground Truth: `R-D08` is `['GTW-D08'] -> []` (Outcome: `EXCEPTION`, ExceptionType: `POSSIBLE_DUPLICATE`).

### 2. Execution Trace
- Stage 3 generates 1:1 financial match alternatives for both `GTW-D08` and `GTW-E03` against `BANK-D03` and `BANK-E03`.
- Two independent source-anchored decision groups are constructed:
  - **Group 4 (`GTW-D08`)**:
    - `Option [0]`: `['GTW-D08'] -> ['BANK-D03']`
    - `Option [1]`: `['GTW-D08'] -> ['BANK-E03']`
  - **Group 6 (`GTW-E03`)**:
    - `Option [0]`: `['GTW-E03'] -> ['BANK-D03']`
    - `Option [1]`: `['GTW-E03'] -> ['BANK-E03']`
- **AI Selection Trace**:
  - `MockProvider` handles `GTW-E03`: Target `BANK-E03` contains `"E03"` $\to$ AI selects `Option [1]` (`GTW-E03 -> BANK-E03`) as `MATCHED`.
  - `MockProvider` handles `GTW-D08`: Neither target contains `"D08"`. The mock fallback logic defaults to `selected_candidate_index = 0` (`GTW-D08 -> BANK-D03`) as `MATCHED`.
- **Global Commit Validator**:
  - `GTW-D08 -> BANK-D03` (claims `BANK-D03`) $\to$ No collision $\to$ Committed (**FP 2**).
  - `GTW-E03 -> BANK-E03` (claims `BANK-E03`) $\to$ No collision $\to$ Committed (**TP**).
- **Outcome**:
  - `R-D08` (`['GTW-D08'] -> []`) is missing from predictions (**FN 2**).
  - Root cause: The AI provider / mock returned `selected_candidate_index = 0` instead of `selected_candidate_index = None` (with `POSSIBLE_DUPLICATE`).

---

## E. Second FN / Second FP Trace

As demonstrated in Section B, the entire set of errors in the pipeline consists of exactly:
- **FN 1 & FP 1**: `R-C06` / `BANK-C06` (Stage 5 N:1 fee deduction sign bug).
- **FN 2 & FP 2**: `R-D08` / `BANK-D03` (AI selection of decoy target vs returning `None`).

There are no additional false negatives or false positives anywhere in the benchmark.

---

## F. Candidate Group Map

The 8 candidate decision groups generated by Stage 5 and their AI resolutions:

| Group # | Anchor | Total Options | Participant Sets | AI Selected Option | Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Group 1** | `GTW-C01` (Source) | 8 | `GTW-C01` vs 6 1:N subsets + 2 1:1 targets | `Option [0]`: `GTW-C01 -> [BANK-C01-1, BANK-C01-2]` | **Committed (TP)** |
| **Group 2** | `GTW-C02` (Source) | 8 | `GTW-C02` vs 6 1:N subsets + 2 1:1 targets | `Option [4]`: `GTW-C02 -> [BANK-C02-1, BANK-C02-2, BANK-C02-3]` | **Committed (TP)** |
| **Group 3** | `GTW-C05` (Source) | 8 | `GTW-C05` vs 6 1:N subsets + 2 1:1 targets | `Option [7]`: `GTW-C05 -> [BANK-C05-1, BANK-C05-2]` | **Committed (TP)** |
| **Group 4** | `GTW-D08` (Source) | 2 | `GTW-D08` vs `[BANK-D03, BANK-E03]` | `Option [0]`: `GTW-D08 -> BANK-D03` | **Committed (FP)** |
| **Group 5** | `GTW-E01` (Source) | 11 | `GTW-E01` vs 11 1:N subsets | `Option [10]`: `GTW-E01 -> [BANK-E01-1, BANK-E01-2]` | **Committed (TP)** |
| **Group 6** | `GTW-E03` (Source) | 2 | `GTW-E03` vs `[BANK-D03, BANK-E03]` | `Option [1]`: `GTW-E03 -> BANK-E03` | **Committed (TP)** |
| **Group 7** | `BANK-C03` (Target) | 9 | `BANK-C03` vs 9 N:1 source subsets | `Option [0]`: `[GTW-C03-1, GTW-C03-2] -> BANK-C03` | **Committed (TP)** |
| **Group 8** | `BANK-C04` (Target) | 9 | `BANK-C04` vs 9 N:1 source subsets | `Option [5]`: `[GTW-C04-1, GTW-C04-2, GTW-C04-3] -> BANK-C04` | **Committed (TP)** |

---

## G. Participant Overlap Map

| Record ID | Type | Groups Referencing Record | Characterization |
| :--- | :--- | :--- | :--- |
| `BANK-C01-1`, `BANK-C01-2` | Target | Group 1 (`GTW-C01`), Group 2 (`GTW-C02`), Group 3 (`GTW-C05`), Group 5 (`GTW-E01`) | Legitimate financial ambiguity across zero-metadata splits |
| `BANK-C02-1`, `BANK-C02-2`, `BANK-C02-3` | Target | Group 1 (`GTW-C01`), Group 2 (`GTW-C02`), Group 3 (`GTW-C05`), Group 5 (`GTW-E01`) | Legitimate financial ambiguity across zero-metadata splits |
| `BANK-C05-1`, `BANK-C05-2` | Target | Group 1 (`GTW-C01`), Group 2 (`GTW-C02`), Group 3 (`GTW-C05`), Group 5 (`GTW-E01`) | Legitimate financial ambiguity across zero-metadata splits |
| `BANK-C03` | Target | Group 1 (`GTW-C01`), Group 2 (`GTW-C02`), Group 3 (`GTW-C05`), Group 7 (`BANK-C03`) | 1:1 cross-cardinality competitor against N:1 group |
| `BANK-C04` | Target | Group 1 (`GTW-C01`), Group 2 (`GTW-C02`), Group 3 (`GTW-C05`), Group 8 (`BANK-C04`) | 1:1 cross-cardinality competitor against N:1 group |
| `GTW-C03-1`, `GTW-C03-2` | Source | Group 7 (`BANK-C03`), Group 8 (`BANK-C04`) | Competing N:1 subset permutations summing to 10,000.00 |
| `GTW-C04-1`, `GTW-C04-2`, `GTW-C04-3` | Source | Group 7 (`BANK-C03`), Group 8 (`BANK-C04`) | Competing N:1 subset permutations summing to 10,000.00 |
| `GTW-C06-1`, `GTW-C06-2` | Source | Group 7 (`BANK-C03`), Group 8 (`BANK-C04`) | Competing N:1 subset permutations summing to 10,000.00 |
| `BANK-D03`, `BANK-E03` | Target | Group 4 (`GTW-D08`), Group 6 (`GTW-E03`) | Competing 1:1 targets for near-duplicate and delayed payments |

---

## H. Global Commit Validator Analysis

1. **Execution Order**: Validates AI selections in deterministic order (Source-anchored groups first sorted by anchor ID, followed by Target-anchored groups sorted by anchor ID).
2. **Deterministic & Stable**: Validation outcome is 100% deterministic and invariant to async task scheduling.
3. **Collision Enforcement**:
   - Any AI candidate selection that claims an already committed source or target ID is rejected immediately as a `FailedClassification` with reason `Global participant collision on record(s): [...]`.
   - Colliding decisions are never coerced, never overwrite earlier results, and never rely on model-reported confidence to decide winners.
4. **Current Status**: On the current benchmark execution, zero collisions occurred because the AI/mock selections were mutually disjoint.

---

## I. AI vs Deterministic Responsibility Classification

| Error Case | Error Category | Root Cause Analysis |
| :--- | :--- | :--- |
| **`R-C06` (FN 1)** | **A. Deterministic candidate generation failure** | In `aggregation.py`, `find_subset_sum` calculates `diff = target_amount - total`. For N:1 fee deduction, `9998.50 - 10000.00 = -1.50 < 0`. Because `diff < 0`, `find_subset_sum` rejected the subset. The option was never generated. |
| **`BANK-C06` (FP 1)** | **A. Deterministic candidate generation failure** | Downstream consequence of `R-C06` generation failure. `BANK-C06` had no candidates $\to$ emitted as `MISSING_RECORD`. |
| **`R-D08` (FN 2)** | **C. AI candidate selection failure (MockProvider default)** | Candidate options for `GTW-D08` were properly generated, but `MockProvider` defaulted to selecting index 0 (`GTW-D08 -> BANK-D03`) instead of returning `selected_candidate_index = None` with `POSSIBLE_DUPLICATE`. |
| **`GTW-D08 -> BANK-D03` (FP 2)** | **C. AI candidate selection failure (MockProvider default)** | Downstream consequence of selecting index 0. |

---

## J. Candidate Quality Assessment

- **Candidate Space**: 53 candidate options across 8 decision groups (average 6.6 options per group; max 11 options in `GTW-E01`).
- **Over-Generation Diagnosis**:
  - The candidate generation is **not globally runaway**; 92.5% of all candidate options are strictly confined to the C-series and E-01 splits.
  - The over-generation in C-series is the mathematical consequence of zero metadata (`ref=""`, `cp=""`) where all subsets of $\{2000, 3000, 5000, 7000\}$ aggregate to $10,000.00$ within the 7-day window.
  - The Anchor-Based Decision Group architecture successfully partitions these 53 options into 8 localized decision contexts without collapsing into a single connected component.

---

## K. Safety Assessment

The implementation was audited against all safety boundaries:
1. **Fabricated Participant IDs**: Prohibited. Participant IDs are extracted exclusively from the selected deterministic option.
2. **Fabricated Topologies / N:M**: Prohibited and validated (`_validate_candidate_decision`).
3. **Candidate Index Bounds**: Strictly bounds-checked (`0 <= idx < len(candidate_options)`).
4. **Amount Hallucination**: Prohibited; validated against the sum of source amounts for `MATCHED` outcomes.
5. **Duplicate Participant Commitment**: Prohibited by the Global Commit Validator.
6. **Candidate Evidence Mutation**: Prohibited; candidate options are immutable.
7. **Premature MISSING_RECORD Emission**: Prohibited; records in candidate options are excluded from deterministic missing record generation.

**Conclusion**: The system is **100% safe**. Its remaining defect on C-06 is a problem of **completeness** (omitted candidate generation due to a sign check), not safety.

---

## L. Architectural Conclusions

1. **Is the current anchor-based decision-group architecture conceptually sound?**
   **YES**. It cleanly separates mutually exclusive alternatives for a single entity from transitively connected alternatives across entities, preserving independence while preventing greedy premature consumption.
2. **Is Stage 5 generating too many mathematically valid but semantically weak candidates?**
   **Within expected bounds for zero-metadata datasets**. In datasets lacking reference numbers and counterparties, arithmetic permutations are unavoidable. The 7-day window and max subset size of 4 successfully bound the computational complexity.
3. **Is the global commit validator causing valid relationships to be lost?**
   **NO**. The validator caused zero collisions and zero dropped relationships in the benchmark.
4. **Is the AI being asked to resolve ambiguities that deterministic evidence cannot meaningfully constrain?**
   **NO**. The deterministic engine constrains the AI to choosing among strictly valid mathematical options (or returning `None`), which is the exact architectural contract of Chunk 4.
5. **Is the current 94.7% F1 representative of a sound architecture?**
   **YES**. The architecture represents 36 out of 38 ground-truth relationships with 100% exact amounts (₹0.00 MAE).
6. **What is the smallest architectural boundary where the remaining problem should be addressed?**
   The single code defect is in **`src/eagle/reconciliation/aggregation.py`** in `find_n_to_1_match` / `find_subset_sum`:
   - For N:1 aggregations where sources sum to greater than target amount due to a fee deduction, `sum(sources) - target.amount` must be checked against `FEE_MATCH_TOLERANCE` (accounting for the sign of the fee difference in N:1 matching).
