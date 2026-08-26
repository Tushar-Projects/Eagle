# Eagle Synthetic Test-Case Matrix

## 1. Purpose

This document specifies every reconciliation scenario that the Eagle benchmark
dataset must contain. It is the version-controlled design contract between:

- **this specification** (what to generate),
- **the future data generator** (produces source records), and
- **the future ground-truth file** (`ground_truth.json`).

No actual records or ground-truth entries are created yet.
This is a design-phase deliverable only.

---

## 2. Dataset Scale Target

| Metric | Target |
|---|---|
| Total relationships | ~38 |
| Total source records (gateway) | ~39 |
| Total target records (bank) | ~40 |
| **Total records** | **~79** |
| Minimum required | 50 |

The count exceeds 50 because 1:N and N:1 relationships consume multiple
records per relationship, and adversarial scenarios require additional
distractor records.

---

## 3. Coverage Categories

| Category | Relationships | Records (approx.) | % of relationships |
|---|---|---|---|
| **A** — Clean deterministic matches | 8 | 16 | 21% |
| **B** — Legitimate matched classifications | 8 | 16 | 21% |
| **C** — Relationship complexity (1:N, N:1) | 6 | 20 | 16% |
| **D** — Missing / exception cases | 9 | 12 | 24% |
| **E** — Adversarial / ambiguous cases | 7 | 15 | 18% |
| **Total** | **38** | **79** | |

Categories overlap by design.  For example, a 1:N adversarial split
(E-01) exercises both relationship complexity and adversarial matching.

The matrix intentionally contains a substantial set of cases that should
reach the AI exception classifier.  The approximate distribution below
is **descriptive of the current matrix design**, not a fixed
architectural target.  The actual AI invocation rate is an empirical
result of the deterministic engine's coverage and must not be treated
as a percentage to achieve.

- Deterministic match coverage (A + B + C + deterministic D/E): ~63%
- AI exception classifier cases: ~16%
- Post-match deterministic resolution (MISSING_RECORD): ~11%
- Pre-matching validation: ~3%

---

## 4. Detailed Case Matrix

### Legend

- **Matching stage**: the hierarchy step expected to resolve the pair.
  1 = Exact ID, 2 = Normalized ID, 3 = Amount/date/currency,
  4 = Fee/net-settlement, 5 = Aggregation (1:N / N:1),
  6 = AI exception classifier, V = Pre-matching validation,
  POST = Post-match deterministic resolution (all stages exhausted,
  no counterpart found).
- **Responsibility**: `DET` = deterministic engine, `AI` = AI classifier,
  `VAL` = validation layer.

---

### A — Clean Deterministic Matches

These cases exercise the deterministic matching hierarchy and should
produce `MATCHED` with no exception classification.

| case_id | scenario_name | rel_type | src | tgt | outcome | exception_type | severity | flag | stage | resp | purpose |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A-01 | Exact ID match — standard payment | 1:1 | 1 | 1 | MATCHED | — | — | — | 1 | DET | Baseline: identical `transaction_id` on both sides, identical amount |
| A-02 | Exact reference match — refund | 1:1 | 1 | 1 | MATCHED | — | — | — | 1 | DET | Reference-based match on a refund transaction type |
| A-03 | Normalized ID — case difference | 1:1 | 1 | 1 | MATCHED | — | — | — | 2 | DET | Gateway uses `PAY-1001`, bank uses `pay-1001` |
| A-04 | Normalized ID — prefix/format | 1:1 | 1 | 1 | MATCHED | — | — | — | 2 | DET | Gateway uses `pay_ABC123`, bank uses `PAY_abc123` |
| A-05 | Amount/date/currency match — no ID overlap | 1:1 | 1 | 1 | MATCHED | — | — | — | 3 | DET | Different reference systems, matched by amount + date + currency + counterparty |
| A-06 | Amount/date match — different reference formats | 1:1 | 1 | 1 | MATCHED | — | — | — | 3 | DET | References are completely unrelated strings, matched on financial attributes |
| A-07 | Exact match — all optional fields populated | 1:1 | 1 | 1 | MATCHED | — | — | — | 1 | DET | Both records carry `gross_amount`, `fee_amount`, `net_amount` |
| A-08 | Exact match — large transaction | 1:1 | 1 | 1 | MATCHED | — | — | — | 1 | DET | High-value transaction (>₹100,000) to verify no precision issues |

**Subtotal: 8 relationships, 16 records.**

---

### B — Legitimate Matched Classifications

These cases match deterministically but carry a classification due to
amount differences or settlement timing.  Outcome remains `MATCHED`.

| case_id | scenario_name | rel_type | src | tgt | outcome | exception_type | severity | flag | stage | resp | purpose |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B-01 | Rounding difference — ₹0.50 | 1:1 | 1 | 1 | MATCHED | ROUNDING_DIFFERENCE | LOW | false | 1 | DET | Difference within ROUNDING_TOLERANCE (₹1.00) |
| B-02 | Rounding difference — ₹0.99 (boundary) | 1:1 | 1 | 1 | MATCHED | ROUNDING_DIFFERENCE | LOW | false | 1 | DET | Boundary case: maximum rounding tolerance |
| B-03 | Fee deduction — ₹1.50 | 1:1 | 1 | 1 | MATCHED | FEE_DEDUCTION | LOW | false | 4 | DET | Diff exceeds rounding tol (₹1.00) but within FEE_MATCH_TOLERANCE (₹2.00); record carries explicit fee evidence |
| B-04 | Fee deduction — with gross/fee/net | 1:1 | 1 | 1 | MATCHED | FEE_DEDUCTION | LOW | false | 4 | DET | Target has `gross_amount`, `fee_amount`, `net_amount` that explain the difference |
| B-05 | Settlement — 0 days (same day) | 1:1 | 1 | 1 | MATCHED | — | — | — | 1 | DET | `settlement_date == transaction_date`; within NORMAL_WINDOW (≤3 days) |
| B-06 | Settlement — 2 days (normal window) | 1:1 | 1 | 1 | MATCHED | — | — | — | 1 | DET | Within NORMAL_WINDOW; no classification needed |
| B-07 | Settlement — 5 days (medium delay) | 1:1 | 1 | 1 | MATCHED | SETTLEMENT_DELAY | MEDIUM | false | 1 | DET | 4–7 day range; SETTLEMENT_DELAY_MEDIUM |
| B-08 | Settlement — 10 days (high delay) | 1:1 | 1 | 1 | MATCHED | SETTLEMENT_DELAY | HIGH | true | 1 | DET | ≥8 days; SETTLEMENT_DELAY_HIGH; `flag_for_review=true` |

**Subtotal: 8 relationships, 16 records.**

**Notes:**
- B-01 and B-02 exercise the `ROUNDING_TOLERANCE = ₹1.00` constant.
- B-03 and B-04 exercise the `FEE_MATCH_TOLERANCE = ₹2.00` constant.
- B-05 and B-06 produce no classification because settlement is ≤3 days.
- B-07 exercises `SETTLEMENT_DELAY_MEDIUM_MIN_DAYS=4` / `MAX=7`.
- B-08 exercises `SETTLEMENT_DELAY_HIGH_MIN_DAYS=8` and `flag_for_review`.

---

### C — Relationship Complexity (1:N and N:1)

These cases test aggregation matching.  A 1:N or N:1 relationship can be
fully `MATCHED` when sub-amounts sum correctly.

| case_id | scenario_name | rel_type | src | tgt | outcome | exception_type | severity | flag | stage | resp | purpose |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C-01 | 1:N split — 2 bank entries | 1:N | 1 | 2 | MATCHED | — | — | — | 5 | DET | Gateway ₹10,000 settled as two bank entries (₹6,000 + ₹4,000) |
| C-02 | 1:N split — 3 bank entries | 1:N | 1 | 3 | MATCHED | — | — | — | 5 | DET | Gateway amount settled as three bank entries summing exactly |
| C-03 | N:1 batch — 2 gateway txns | N:1 | 2 | 1 | MATCHED | — | — | — | 5 | DET | Two gateway payments combined in one bank settlement |
| C-04 | N:1 batch — 3 gateway txns | N:1 | 3 | 1 | MATCHED | — | — | — | 5 | DET | Three gateway payments combined in one bank settlement |
| C-05 | 1:N with rounding in one component | 1:N | 1 | 2 | MATCHED | ROUNDING_DIFFERENCE | LOW | false | 5 | DET | Sub-amounts sum to within ₹1.00 of gateway amount |
| C-06 | N:1 with fee deduction | N:1 | 2 | 1 | MATCHED | FEE_DEDUCTION | LOW | false | 5 | DET | Sum of gateway amounts minus bank amount is within FEE_MATCH_TOLERANCE |

**Subtotal: 6 relationships, 20 records.**

**Notes:**
- C-01 and C-02 verify that the aggregation matcher sums target records
  correctly.
- C-03 and C-04 verify the reverse direction.
- C-05 and C-06 combine aggregation with tolerance-based classification.
- All sub-amounts must be source-evidence-based; the expected result
  belongs only in ground truth.

---

### D — Missing / Exception Cases

These cases produce `EXCEPTION` outcome.  They exercise the closed
exception taxonomy and the MISSING_RECORD symmetric convention.
MISSING_RECORD cases are resolved deterministically (post-match); other
exception types may require the AI exception classifier.

| case_id | scenario_name | rel_type | src | tgt | outcome | exception_type | severity | flag | stage | resp | purpose |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D-01 | Orphan gateway — no bank match | 1:1 | 1 | 0 | EXCEPTION | MISSING_RECORD | HIGH | true | POST | DET | `source_record_ids=["GTW-…"]`, `target_record_ids=[]` |
| D-02 | Orphan gateway — recent transaction | 1:1 | 1 | 0 | EXCEPTION | MISSING_RECORD | MEDIUM | true | POST | DET | Same convention; recent date suggests settlement pending |
| D-03 | Orphan bank — no gateway match | 1:1 | 0 | 1 | EXCEPTION | MISSING_RECORD | HIGH | true | POST | DET | `source_record_ids=[]`, `target_record_ids=["BANK-…"]` |
| D-04 | Orphan bank — small amount | 1:1 | 0 | 1 | EXCEPTION | MISSING_RECORD | MEDIUM | false | POST | DET | Same convention; low severity due to small amount |
| D-05 | Currency mismatch | 1:1 | 1 | 1 | EXCEPTION | CURRENCY_MISMATCH | HIGH | true | 3 | AI | Same logical transaction, gateway=INR, bank=USD |
| D-06 | Partial settlement | 1:1 | 1 | 1 | EXCEPTION | PARTIAL_SETTLEMENT | HIGH | true | 4 | AI | Bank settled significantly less than gateway amount (outside both tolerances) |
| D-07 | Deterministic duplicate | 1:1 | 1 | 0 | EXCEPTION | DUPLICATE | MEDIUM | true | 1 | DET | Identical `transaction_id`, amount, date as another gateway record; `target_record_ids=[]` |
| D-08 | Possible duplicate — AI suspicion | 1:1 | 1 | 0 | EXCEPTION | POSSIBLE_DUPLICATE | MEDIUM | true | 6 | AI | Similar but not identical to another record; insufficient deterministic evidence |
| D-09 | Unknown / ambiguous | 1:1 | 1 | 1 | EXCEPTION | UNKNOWN | HIGH | true | 6 | AI | Cannot be explained by any deterministic rule; requires human review |

**Subtotal: 9 relationships, 12 records.**

MISSING_RECORD is **deterministic post-match resolution**, not an AI
classification.  After all matching stages (1–5) are exhausted and no
counterpart is found, the system deterministically classifies the
unresolved record as MISSING_RECORD.  No AI inference is needed.

**Notes:**
- D-01/D-02 and D-03/D-04 exercise the symmetric MISSING_RECORD convention
  in both directions.
- D-07's "original" record is the same gateway record that participates in a
  matched relationship elsewhere (e.g., A-01).  Only the duplicate record
  itself appears in this relationship.
- D-08 is intentionally distinct from D-07: the AI classifier must distinguish
  between deterministic and probabilistic duplicate signals.

---

### E — Adversarial / Ambiguous Cases

These cases deliberately stress the matching hierarchy with realistic
confounding patterns.

| case_id | scenario_name | rel_type | src | tgt | outcome | exception_type | severity | flag | stage | resp | purpose |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E-01 | Adversarial split — irregular sub-amounts | 1:N | 1 | 2 | MATCHED | — | — | — | 5 | DET | Gateway ₹15,000 settled as ₹9,237 + ₹5,763; non-obvious split |
| E-02a | Near-miss pair — transaction A | 1:1 | 1 | 1 | MATCHED | — | — | — | 3 | DET | Two similar-looking pairs (A→X, B→Y); amounts/dates nearly identical |
| E-02b | Near-miss pair — transaction B | 1:1 | 1 | 1 | MATCHED | — | — | — | 3 | DET | Must not cross-match with E-02a; tests matcher disambiguation |
| E-03 | Ambiguous candidate pool | 1:1 | 1 | 1 | MATCHED | — | — | — | 3 | DET | Multiple bank records with same amount/date; only one is the correct match |
| E-04 | Invalid settlement chronology | 1:1 | 1 | 1 | EXCEPTION | —² | — | — | V | VAL | `settlement_date` precedes `transaction_date`; validation exception |
| E-05 | Amount difference outside all tolerances | 1:1 | 1 | 1 | EXCEPTION | UNKNOWN | HIGH | true | 6 | AI | Difference (e.g. ₹200) exceeds both ROUNDING (₹1) and FEE (₹2) tolerances |
| E-06 | Problematic split settlement — aggregate shortfall | 1:N | 1 | 2 | EXCEPTION | SPLIT_SETTLEMENT | HIGH | true | 5→6 | AI | Gateway ₹10,000 split across 2 bank entries totaling ₹8,500; aggregate does not reconcile |

**Subtotal: 7 relationships, 15 records.**

² **Architectural note on E-04**: Validation exceptions are NOT part of the
AI exception taxonomy (`ExceptionType` enum).  See [§8 — Validation
Exception Representation](#validation-exception-representation) for the
ground-truth encoding decision.

**Notes:**
- E-01 tests that the aggregation matcher handles non-round sub-amounts.
  The key challenge is that ₹9,237 and ₹5,763 do not individually resemble
  the gateway amount.
- E-02a / E-02b create two transaction pairs where cross-matching is
  plausible.  The ground truth specifies the single correct pairing.
  Gateway A (₹10,000, Jan-15) / Bank X (₹10,000, Jan-17) and
  Gateway B (₹10,001, Jan-15) / Bank Y (₹10,001, Jan-18).
  Amounts differ by ₹1 (within ROUNDING_TOLERANCE), so a naïve matcher
  might swap them.
- E-03 introduces a "decoy" bank record (same amount and similar date as the
  correct match).  The decoy is accounted for elsewhere in the dataset
  (e.g., it matches a different gateway transaction or is an orphan).
- E-05 ensures the system does not force-match records with irreconcilable
  differences.
- **E-06** is the dedicated SPLIT_SETTLEMENT exception case.  It is
  distinct from PARTIAL_SETTLEMENT (D-06) — see the semantic distinction
  below.

**PARTIAL_SETTLEMENT vs SPLIT_SETTLEMENT distinction:**

| | PARTIAL_SETTLEMENT (D-06) | SPLIT_SETTLEMENT (E-06) |
|---|---|---|
| Structure | 1 source → 1 target | 1 source → multiple targets |
| Relationship type | 1:1 | 1:N |
| Evidence | Single counterpart with shortfall | Multiple counterpart records whose aggregate has shortfall |
| Key difference | No multi-record split structure | The multi-record split structure is itself part of the exception |

For E-06, deterministic aggregation (stage 5) establishes the evidence
(identifies the split sub-records and computes the aggregate), but the
AI exception classifier (stage 6) makes the semantic exception
classification because the aggregate does not reconcile and the engine
cannot determine the cause deterministically.

---

## 5. Relationship-Level Examples

### 1:1 Clean Match (A-01)

```
source:  GTW-001  amount=₹5,000.00  date=2025-01-15  ref="PAY-10001"
target:  BANK-001 amount=₹5,000.00  date=2025-01-17  ref="PAY-10001"

ground truth:
  relationship_id: "R-A01"
  relationship_type: "1:1"
  source_record_ids: ["GTW-001"]
  target_record_ids: ["BANK-001"]
  expected_outcome: "MATCHED"
  expected_exception_type: null
  expected_reconciled_amount: 5000.00
```

### 1:N Split Settlement (C-01)

```
source:  GTW-010  amount=₹10,000.00  date=2025-02-01
target:  BANK-010 amount=₹6,000.00   date=2025-02-03
target:  BANK-011 amount=₹4,000.00   date=2025-02-03

ground truth:
  relationship_id: "R-C01"
  relationship_type: "1:N"
  source_record_ids: ["GTW-010"]
  target_record_ids: ["BANK-010", "BANK-011"]
  expected_outcome: "MATCHED"
  expected_exception_type: null
  expected_reconciled_amount: 10000.00
```

### N:1 Batch Settlement (C-03)

```
source:  GTW-015  amount=₹3,000.00  date=2025-02-10
source:  GTW-016  amount=₹7,000.00  date=2025-02-10
target:  BANK-015 amount=₹10,000.00 date=2025-02-12

ground truth:
  relationship_id: "R-C03"
  relationship_type: "N:1"
  source_record_ids: ["GTW-015", "GTW-016"]
  target_record_ids: ["BANK-015"]
  expected_outcome: "MATCHED"
  expected_reconciled_amount: 10000.00
```

### MISSING_RECORD — Source Exists (D-01)

```
source:  GTW-030  amount=₹8,500.00  date=2025-03-01  (no bank counterpart)

ground truth:
  relationship_id: "R-D01"
  relationship_type: "1:1"
  source_record_ids: ["GTW-030"]
  target_record_ids: []
  expected_outcome: "EXCEPTION"
  expected_exception_type: "MISSING_RECORD"
  expected_reconciled_amount: 0.00
```

### MISSING_RECORD — Target Exists (D-03)

```
target:  BANK-033  amount=₹2,200.00  date=2025-03-05  (no gateway counterpart)

ground truth:
  relationship_id: "R-D03"
  relationship_type: "1:1"
  source_record_ids: []
  target_record_ids: ["BANK-033"]
  expected_outcome: "EXCEPTION"
  expected_exception_type: "MISSING_RECORD"
  expected_reconciled_amount: 0.00
```

### MATCHED + SETTLEMENT_DELAY (B-08)

```
source:  GTW-009  amount=₹12,000.00  transaction_date=2025-01-10
target:  BANK-009 amount=₹12,000.00  settlement_date=2025-01-20  (10 days)

ground truth:
  relationship_id: "R-B08"
  relationship_type: "1:1"
  source_record_ids: ["GTW-009"]
  target_record_ids: ["BANK-009"]
  expected_outcome: "MATCHED"
  expected_exception_type: "SETTLEMENT_DELAY"
  expected_reconciled_amount: 12000.00
  notes: "10-day delay; HIGH severity; flag_for_review=true"
```

### SPLIT_SETTLEMENT — Aggregate Shortfall (E-06)

```
source:  GTW-040  amount=₹10,000.00  date=2025-03-10
target:  BANK-040 amount=₹6,000.00   date=2025-03-12
target:  BANK-041 amount=₹2,500.00   date=2025-03-13
(aggregate bank = ₹8,500; shortfall = ₹1,500)

ground truth:
  relationship_id: "R-E06"
  relationship_type: "1:N"
  source_record_ids: ["GTW-040"]
  target_record_ids: ["BANK-040", "BANK-041"]
  expected_outcome: "EXCEPTION"
  expected_exception_type: "SPLIT_SETTLEMENT"
  expected_reconciled_amount: 10000.00
  notes: "Aggregate bank settlement ₹8,500 vs gateway ₹10,000.
          Distinct from PARTIAL_SETTLEMENT (D-06) which is 1:1."
```

---

## 6. Adversarial Case Requirements

The architecture requires at minimum these four adversarial patterns:

| # | Adversarial pattern | Matrix case(s) | Challenge |
|---|---|---|---|
| 1 | Duplicate transaction | D-07, D-08 | Distinguish deterministic duplicate from AI-suspected near-duplicate |
| 2 | Currency mismatch | D-05 | Same logical payment recorded in different currencies |
| 3 | Split payment / settlement | C-01, C-02, E-01, E-06 | Clean splits (C/E-01) and problematic split with shortfall (E-06) |
| 4 | Near-miss fraud-like pattern | E-02a, E-02b | Two pairs with nearly identical amounts/dates; matcher must not cross-match |

Additional adversarial coverage:

| # | Pattern | Matrix case(s) |
|---|---|---|
| 5 | Orphan gateway transaction | D-01, D-02 |
| 6 | Orphan bank settlement | D-03, D-04 |
| 7 | Partial settlement | D-06 |
| 8 | Suspicious near-duplicate | D-08 |
| 9 | Ambiguous candidate pool | E-03 |
| 10 | Invalid settlement chronology | E-04 |
| 11 | Amount outside all tolerances | E-05 |

---

## 7. Deterministic vs AI Responsibility

Each case is explicitly assigned to either the deterministic engine or
the AI exception classifier.

### Deterministic Engine (Stages 1–5)

| Cases | Rationale |
|---|---|
| A-01 through A-08 | Resolved by ID or attribute matching |
| B-01 through B-08 | Resolved by ID matching + tolerance/timing classification |
| C-01 through C-06 | Resolved by aggregation matching |
| D-07 | DUPLICATE detected by exact ID/amount/date identity |
| E-01 | Aggregation match with irregular sub-amounts |
| E-02a, E-02b | Attribute matching with disambiguation |
| E-03 | Attribute matching with candidate selection |

### Post-Match Deterministic Resolution

After all matching stages (1–5) are exhausted, records with no
counterpart are deterministically classified as MISSING_RECORD.
This does NOT route through the AI exception classifier.

| Cases | Rationale |
|---|---|
| D-01 through D-04 | MISSING_RECORD — no counterpart found after exhausting all stages |

### Pre-Matching Validation

| Cases | Rationale |
|---|---|
| E-04 | `settlement_date < transaction_date` caught before matching |

### AI Exception Classifier (Stage 6)

| Cases | Rationale |
|---|---|
| D-05 | Currency mismatch requires semantic understanding |
| D-06 | Partial settlement requires AI judgment that the shortfall is not noise |
| D-08 | POSSIBLE_DUPLICATE requires AI uncertainty assessment |
| D-09 | UNKNOWN requires AI to confirm no known pattern applies |
| E-05 | Amount difference outside all tolerances, no deterministic explanation |
| E-06 | Split settlement with aggregate shortfall; aggregation (stage 5) establishes evidence, AI classifies |

---

## 8. Ground-Truth Generation Rules

When the future generator creates `ground_truth.json`, these rules apply:

### Relationship ID Convention

`R-{case_id}` — e.g., `R-A01`, `R-C03`.

### Record ID Convention

- Gateway records: `GTW-NNN`
- Bank records: `BANK-NNN`

### MISSING_RECORD Encoding

Use the approved symmetric convention:

- Source exists, target missing: `target_record_ids = []`
- Target exists, source missing: `source_record_ids = []`
- Never use null, sentinels, or placeholder IDs.

### DUPLICATE Encoding

The duplicate record appears as:

```
source_record_ids: [duplicate_record_id]
target_record_ids: []
expected_outcome: EXCEPTION
expected_exception_type: DUPLICATE
```

The original record participates in a separate MATCHED relationship.

### SPLIT_SETTLEMENT Encoding

A problematic split settlement uses a 1:N relationship where the
aggregate of target amounts does not reconcile the source amount:

```
relationship_type: "1:N"
source_record_ids: [gateway_record_id]
target_record_ids: [bank_record_id_1, bank_record_id_2, ...]
expected_outcome: EXCEPTION
expected_exception_type: SPLIT_SETTLEMENT
```

This is distinct from PARTIAL_SETTLEMENT, which is a 1:1 relationship
where a single counterpart settled less than expected.

### expected_reconciled_amount

- For MATCHED relationships: the reconciled amount is the gateway/source
  amount (the authoritative amount).
- For 1:N: the source amount (sum of targets should equal it).
- For N:1: the bank/target amount (sum of sources should equal it).
- For MISSING_RECORD: `0.00` (no reconciliation occurred).
- For SPLIT_SETTLEMENT: the source amount (authoritative, even though
  the aggregate settlement falls short).
- For other EXCEPTION cases: the source amount where one exists,
  otherwise the target amount.

### <a name="validation-exception-representation"></a>Validation Exception Representation

E-04 (invalid settlement chronology) is a **validation exception**,
which is NOT part of the `ExceptionType` enum.

Ground-truth representation:

```
expected_outcome: EXCEPTION
expected_exception_type: null
notes: "Validation exception: settlement_date precedes transaction_date.
        Handled by pre-matching validation, not AI taxonomy."
```

Rationale: The domain models are frozen and correctly exclude
`VALIDATION_EXCEPTION` from the AI taxonomy.  Using
`expected_exception_type = null` with descriptive notes preserves the
architectural distinction while remaining representable in the
`GroundTruthRelationship` model.

The future evaluator must handle `expected_exception_type = null` with
`expected_outcome = EXCEPTION` as a validation-exception case.

### No Data Leakage

Source records must NOT contain fields that reveal expected outcomes.
Expected outcomes, classifications, and severity exist only in
`ground_truth.json`.

Source records should resemble realistic gateway exports and bank
statements with source-specific field names.

---

## 9. Explicit Invariants

These invariants must hold across all generated data:

1. **Outcome ≠ classification.**
   `MATCHED + ROUNDING_DIFFERENCE` is valid.
   `MATCHED + FEE_DEDUCTION` is valid.
   `EXCEPTION + MISSING_RECORD` is valid.

2. **Relationship type ≠ outcome.**
   `1:N + MATCHED` is valid.
   `N:1 + MATCHED` is valid.

3. **`DUPLICATE ≠ POSSIBLE_DUPLICATE`.**
   D-07 has deterministic evidence.
   D-08 has only AI suspicion.

4. **Validation exceptions ≠ AI taxonomy.**
   E-04 is caught by pre-matching validation and does NOT use
   `ExceptionType`.

5. **Extraction confidence ≠ calibrated probability.**
   If confidence values are included in source data, they are
   risk signals, not probabilities.

6. **`transaction_date ≠ settlement_date`.**
   Both are independently represented.  Settlement timing is
   evaluated after matching, not during.

7. **SQLite = authoritative state; ChromaDB = semantic retrieval only.**
   The dataset must not assume any particular storage ordering.

8. **Ground-truth `notes` must never influence evaluation.**
   Notes are documentation only.

9. **N:M is out of scope.**
   No relationship in the dataset requires N:M.

10. **Partial predicted relationships are incorrect.**
    If ground truth says `target_record_ids = ["BANK-010", "BANK-011"]`
    and the system predicts `target_record_ids = ["BANK-010"]`, the
    relationship-level evaluation should mark it as incorrect.

---

## 10. Coverage Checklist

### Matching Hierarchy Stages

- [x] Stage 1: Exact ID/reference (A-01, A-02, A-07, A-08, B-01–B-08)
- [x] Stage 2: Normalized ID/reference (A-03, A-04)
- [x] Stage 3: Amount/date/currency (A-05, A-06, E-02a, E-02b, E-03)
- [x] Stage 4: Fee/net-settlement (B-03, B-04)
- [x] Stage 5: 1:N / N:1 aggregation (C-01–C-06, E-01, E-06 evidence)
- [x] Stage 6: AI exception classifier (D-05, D-06, D-08, D-09, E-05, E-06)
- [x] Post-match deterministic resolution (D-01–D-04)
- [x] Validation layer (E-04)

### Exception Taxonomy Coverage

- [x] SETTLEMENT_DELAY (B-07, B-08)
- [x] FEE_DEDUCTION (B-03, B-04, C-06)
- [x] ROUNDING_DIFFERENCE (B-01, B-02, C-05)
- [x] PARTIAL_SETTLEMENT (D-06)
- [x] SPLIT_SETTLEMENT (E-06)
- [x] DUPLICATE (D-07)
- [x] MISSING_RECORD (D-01, D-02, D-03, D-04)
- [x] CURRENCY_MISMATCH (D-05)
- [x] POSSIBLE_DUPLICATE (D-08)
- [x] UNKNOWN (D-09, E-05)

**PARTIAL_SETTLEMENT vs SPLIT_SETTLEMENT**: D-06 is a 1:1 relationship
where a single counterpart settled less than expected.  E-06 is a 1:N
relationship where multiple counterpart records exist but their
aggregate does not reconcile the source amount.  Clean 1:N splits that
fully reconcile (C-01, C-02, E-01) remain `MATCHED` with no exception
classification.

### Relationship Types

- [x] 1:1 (A-*, B-*, D-*, E-02–E-05)
- [x] 1:N (C-01, C-02, C-05, E-01, E-06)
- [x] N:1 (C-03, C-04, C-06)

### Adversarial Requirements

- [x] Duplicate transaction (D-07)
- [x] Currency mismatch (D-05)
- [x] Split payment / split settlement (C-01, C-02, E-01, E-06)
- [x] Near-miss fraud-like pattern (E-02a, E-02b)
- [x] Orphan gateway (D-01, D-02)
- [x] Orphan bank (D-03, D-04)
- [x] Partial settlement (D-06)
- [x] Suspicious near-duplicate (D-08)
- [x] Ambiguous candidate pool (E-03)
- [x] Invalid settlement chronology (E-04)

### MISSING_RECORD Convention

- [x] Source exists, target missing (D-01, D-02)
- [x] Target exists, source missing (D-03, D-04)
- [x] Empty array (not null) on absent side
- [x] No placeholder IDs

### Settlement Timing Coverage

- [x] 0-day settlement (B-05)
- [x] 1–3 day normal window (B-06)
- [x] 4–7 day medium delay (B-07)
- [x] >7 day high delay (B-08)
- [x] Settlement before transaction (E-04)

### Amount Tolerance Coverage

- [x] Exact amount (A-01–A-08, B-05–B-08, C-01–C-04)
- [x] Within ROUNDING_TOLERANCE ≤₹1.00 (B-01, B-02, C-05)
- [x] Within FEE_MATCH_TOLERANCE ≤₹2.00 (B-03, B-04, C-06)
- [x] Outside both tolerances (D-06, E-05)

---

*This document is a design specification only.  Actual records and
ground-truth data will be generated in a subsequent task.*
