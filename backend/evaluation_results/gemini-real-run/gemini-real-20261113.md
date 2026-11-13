# LLM Benchmark gemini-real-20261113

- Dataset: TestNova synthetic evidence-grounded test-case generation v1.0.0
- Provider/model: gemini / gemini-3.5-flash-lite
- Execution mode: live
- Examples: 5 total, 5 completed, 0 failed, 0 skipped

| Metric | Value |
|---|---:|
| Structured-output validity (schema + evidence refs) | 100.00% |
| JSON/schema validity | 100.00% |
| Evidence accuracy proxy | 0.8181 |
| Unsupported-claim phrase-match rate | 0.00% |
| Requirement coverage | 1.0000 |
| Deterministic usefulness proxy | 0.8936 |
| Average attempt latency (ms) | 1579.5010 ms |
| Median attempt latency (ms) | 1311.0075 ms |
| Average overall request latency (ms) | 1579.6362 ms |
| Median overall request latency (ms) | 1311.1294 ms |
| Failed provider calls | 0 |
| Input tokens (coverage) | 1602 (100.0% coverage) |
| Output tokens (coverage) | 892 (100.0% coverage) |
| Total tokens (coverage) | 2494 (100.0% coverage) |
| Estimated cost (coverage) | n/a |

## Per-example status

| Example | Status | Structure valid | Evidence proxy | Usefulness proxy |
|---|---|---:|---:|---:|
| SYN-AUTH-POS-001 | completed | True | 0.8627 | 0.9412 |
| SYN-AUTH-NEG-002 | completed | True | 0.8889 | 0.9524 |
| SYN-CART-BOUNDARY-003 | completed | True | 0.6721 | 0.8952 |
| SYN-RESET-EDGE-004 | completed | True | 0.6667 | 0.7857 |
| SYN-EXPORT-INSUFFICIENT-005 | completed | True | 1.0000 | n/a |

## Limitations

- Evidence and unsupported-claim checks are deterministic lexical/reference checks, not semantic proof.
- Usefulness score is a deterministic proxy; human review is required for subjective quality.
- Metrics from mocked services are not model performance measurements.
- Telemetry and benchmark results are local files and in-memory during the run, not database-persisted.

No model winner is declared by this report. Review sample size, score coverage, and human annotations before comparing providers.
