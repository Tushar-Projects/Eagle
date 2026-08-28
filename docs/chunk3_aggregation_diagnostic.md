# Chunk 3 Stage 5 Aggregation Diagnostic Report

## 1. Safety Violation Traces

### The "Mixed IDs" Log Artifact
The log output displaying massively duplicated arrays like:
`['GTW-C03-1', 'GTW-C03-2', 'GTW-C03-1', 'GTW-C06-2', 'GTW-C03-2', 'GTW-C04-2', ...]` (21 elements)

**Cause**: This is a logging artifact in `_validate_candidate_decision`. The logger iterates over all options using a list comprehension:
```python
logger.warning(
    "Safety violation for %s: %s", 
    [sid for opt in evidence.candidate_options for sid in opt.source_record_ids], 
    e
)
```
This flattens all 9 valid subsets (which contain overlapping IDs) into a single duplicated list. 

**Integrity check**: The underlying `CandidateRelationshipOption` instances DO NOT contain duplicate IDs. Furthermore, `ClassificationCase.source_record_ids` uses a `set` comprehension to guarantee unique IDs during AI inference. The duplication is purely visual in the error log.

### The "7000.00 != 10000.00" Amount Failure
**Cause**: The N:1 target `BANK-C03` has an amount of `10000.00`. The deterministic engine identifies 9 valid source subsets that perfectly sum to `10000.00` (e.g., `GTW-C03-1` (3000) + `GTW-C03-2` (7000)).

When the Live AI Provider (Gemini/Claude) evaluates this N:1 case, it returns a decision with `reconciled_amount = "7000.00"` (likely hallucinating the amount of just one record, `GTW-C03-2`). 

The safety validator in `_validate_candidate_decision` correctly looks up the amounts of the AI's selected option sources (3000 + 7000), sums them to `10000.00`, and rejects the AI's `7000.00` output. The engine's safety barrier is working perfectly to prevent AI hallucinations.

## 2. Why are there 11 Candidate Pools?

Prior to the Chunk 3 correction, the deterministic engine greedily consumed records or overwrote evidence. Now that it preserves all deterministic ambiguities across all stages, the cross-product of matching characteristics results in 11 pools:

1. `GTW-C01` -> 1:N pool (6 options against C-01/C-02/C-05 targets)
2. `GTW-C02` -> 1:N pool (6 options against C-01/C-02/C-05 targets)
3. `GTW-C05` -> 1:N pool (6 options against C-01/C-02/C-05 targets)
4. `GTW-E01` -> 1:N pool (11 options against C/E targets)
5. `BANK-C03` -> N:1 pool (9 options against C-03/C-04/C-06 sources)
6. `BANK-C04` -> N:1 pool (9 options against C-03/C-04/C-06 sources)
7. `GTW-C01` -> 1:1 pool (2 options against BANK-C03 / BANK-C04)
8. `GTW-C02` -> 1:1 pool (2 options against BANK-C03 / BANK-C04)
9. `GTW-C05` -> 1:1 pool (2 options against BANK-C03 / BANK-C04)
10. `GTW-D08` -> 1:1 pool (2 options against BANK-D03 / BANK-E03)
11. `GTW-E03` -> 1:1 pool (2 options against BANK-D03 / BANK-E03)

Because `GTW-C01/C02/C05` have amount `10000.00`, they not only form valid 1:N aggregations but also 1:1 exact matches with `BANK-C03` and `BANK-C04`. The engine correctly preserves both topologies as separate candidate pools.

## 3. Case-by-Case Execution Trace (C-02 through C-06)

### GTW-C02 (Amount: 10,000.00)
- **1:N Candidate Pool**: 
  - Option 0: `BANK-C01-1`, `BANK-C01-2`
  - Option 1: `BANK-C01-1`, `BANK-C05-2`
  - Option 2: `BANK-C01-2`, `BANK-C05-1`
  - Option 3: `BANK-C05-1`, `BANK-C05-2`
  - Option 4: `BANK-C01-2`, `BANK-C02-3`, `BANK-C05-2`
  - Option 5: `BANK-C02-1`, `BANK-C02-2`, `BANK-C02-3`
- **1:1 Candidate Pool**:
  - Option 0: `BANK-C03`
  - Option 1: `BANK-C04`

### BANK-C03 (Amount: 10,000.00)
- **N:1 Candidate Pool**:
  - Option 0: `GTW-C03-1`, `GTW-C03-2`
  - Option 1: `GTW-C03-1`, `GTW-C06-2`
  - Option 2: `GTW-C03-2`, `GTW-C04-2`
  - Option 3: `GTW-C03-2`, `GTW-C06-1`
  - Option 4: `GTW-C04-2`, `GTW-C06-2`
  - Option 5: `GTW-C06-1`, `GTW-C06-2`
  - Option 6: `GTW-C03-1`, `GTW-C04-1`, `GTW-C04-3`
  - Option 7: `GTW-C04-1`, `GTW-C04-2`, `GTW-C04-3`
  - Option 8: `GTW-C04-1`, `GTW-C04-3`, `GTW-C06-1`

### BANK-C04 (Amount: 10,000.00)
- Identical N:1 pool to BANK-C03.

### GTW-C05 (Amount: 10,000.00)
- Identical 1:N and 1:1 pools to GTW-C02.

### C-06 Series
- The C-06 sources (`GTW-C06-1`, `GTW-C06-2`) are evaluated as part of the N:1 combinations for `BANK-C03` and `BANK-C04` since their amounts perfectly substitute for C-03 sources.

## Conclusion
- **Unique IDs**: Guaranteed within AI models via set comprehensions.
- **Valid Cardinality**: Guaranteed by deterministic engine generation limits.
- **Amount Consistency**: The deterministic engine only produces mathematically valid subsets. AI hallucinations are correctly intercepted and blocked by `_validate_candidate_decision`. No production logic changes are required for the evidence contract itself, though the logging artifact could be cleaned up.
