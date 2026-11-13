# TestNova LLM evaluation and benchmarking

## Dataset format and versioning

The versioned dataset is
[`backend/evaluation_datasets/test_case_generation_v1.json`](../backend/evaluation_datasets/test_case_generation_v1.json).
It contains deterministic, synthetic software examples, not claims about a real
TestNova deployment. Each example includes a stable ID, scenario type,
requirements prompt, evidence chunks with integer IDs, expected requirement and
category coverage, explicit unsupported behaviors, known constraints, and
reference annotations.

Annotations include exact evidence quotations. The loader rejects duplicate
example/evidence IDs, unknown annotation evidence references, untraceable
quotes, unsupported requirement annotations, and malformed dataset versions.
Published datasets are immutable: make a new file/version when changing any
example, evidence, reference, or scoring guidance. Reports record the dataset
version, a canonical-content SHA-256 digest, and selected IDs.

Examples cover positive, negative, boundary, edge, multi-chunk, and
insufficient-evidence cases. All product details are explicitly synthetic.

## Evaluation dimensions and score interpretation

- **Structured output:** parse JSON without repairs and validate against the
  existing `GeneratedTestCase` schema. The wrapper must contain `test_cases`.
  This enforces required fields, categories/priorities/severities, positive
  evidence IDs, non-empty steps, and step action/expected-result fields.
  Dataset-aware structured-output validity additionally requires every evidence
  reference to exist in the example's supplied chunks; JSON/schema validity is
  reported separately.
- **Evidence accuracy proxy:** citation precision checks whether supplied IDs
  were used; relevant-evidence recall checks use against the dataset's
  annotated relevant IDs; cited-text token overlap checks lexical relevance
  between generated case text and cited chunks. Their arithmetic mean is
  reported as an evidence accuracy score. This is a deterministic proxy, not
  semantic proof that a cited passage entails every test-case assertion.
- **Unsupported-claim proxy:** detects only exact normalized phrase matches
  against each example's explicit `unsupported_behaviors`. It is a lower-bound
  detector and cannot establish that all unsupported inventions were found.
- **Requirement/category coverage:** compares generated requirement keys and
  categories against dataset expectations. Unexpected keys/categories and
  missing coverage are reported separately.
- **Deterministic usefulness proxy:** unweighted mean of requirement coverage,
  action/expected-result length heuristics, schema-based step testability,
  evidence-token overlap, expected-category coverage, and pairwise similarity
  non-redundancy. It is not a validated quality score.
- **Human review:** subjective usefulness dimensions—scenario relevance,
  realistic execution, clarity in context, expected-result observability,
  and whether the evidence genuinely supports each claim—must be scored by
  reviewers. Reports leave `human_review_scores` and
  `human_reviewed_usefulness_score` unset; do not treat the deterministic proxy
  as a substitute.
- **Latency, usage, and cost:** per-attempt latency and available token counts
  come from the Stage 4 router telemetry. Overall latency spans the full
  benchmark request. Missing usage remains `null`. Cost uses only configured
  provider/model input/output rates and their declared currency; there are no
  baked-in prices. Cost is an estimate, never a provider invoice. Each cost
  record includes exact input/output rates, currency, and a pricing version or
  deterministic configuration fingerprint.

## Offline validation

From PowerShell, use the existing virtual environment and a temporary working
directory so tests do not load a workspace `.env`:

```powershell
$python = 'C:\PRODUCTS\TestNova\myenv\Scripts\python.exe'
Set-Location $env:TEMP
$env:PYTHONPATH = 'C:\PRODUCTS\TestNova\backend'
$env:DATABASE_URL = 'sqlite:///unused-llm-evaluation-tests.db'
$env:GEMINI_API_KEY = 'test-only-not-a-real-key'
$env:JWT_SECRET_KEY = 'test-only-signing-key-not-for-deployment'
$env:LLM_TELEMETRY_PATH = Join-Path $env:TEMP `
  'testnova-llm-evaluation-tests.jsonl'
& $python -m pytest C:\PRODUCTS\TestNova\backend\tests\test_llm_benchmark.py -q
```

Tests use fake services/providers and never make an external request.

## Explicit live benchmark opt-in

The CLI never performs provider calls without `--live`. Live runs use the
configured credentials through the normal provider adapters, incur provider
charges where applicable, and write raw model output to the chosen local output
directory. They use temperature zero by default, disable provider fallback so
each selected provider is measured independently, and do not write to the
application database.

Run one selected provider/model from the backend directory:

```powershell
Set-Location C:\PRODUCTS\TestNova\backend
..\myenv\Scripts\python.exe -m app.evaluation.benchmark_cli run `
  --provider gemini `
  --model YOUR_CONFIGURED_GEMINI_MODEL `
  --dataset evaluation_datasets\test_case_generation_v1.json `
  --dataset-version 1.0.0 `
  --output-dir evaluation_results\gemini-run `
  --live
```

Groq is selected explicitly with `--provider groq` and a configured Groq model.
Credentials are taken from the project's normal runtime configuration and
should never be included in command-line arguments. A single-example run can
use one or more `--example-id SYN-AUTH-POS-001` arguments. Omit these flags to
run the entire dataset. Each run writes `<run-id>.json` and `<run-id>.md`;
JSON preserves each raw output and per-attempt telemetry.

Compare runs only after executing the same dataset version and selected example
IDs for each provider:

```powershell
..\myenv\Scripts\python.exe -m app.evaluation.benchmark_cli compare `
  evaluation_results\gemini-run\RUN_ID.json `
  evaluation_results\groq-run\RUN_ID.json `
  --output-dir evaluation_results\comparison
```

Comparison refuses different dataset contents/versions, selected example sets,
prompt hashes, or generation settings and never declares a winner. Mocked runs
may be compared for harness/scoring tests, but their latency and cost are
explicitly unavailable and must not be interpreted as provider measurements.

## Verified pricing configuration

No provider prices are included in TestNova defaults. An administrator must
verify rates from an approved, current provider price sheet and configure both
input and output price per million tokens for the exact provider/model name.
Rates use the configured currency and must be finite non-negative numbers.
Configure `LLM_PRICING_CURRENCY` and optionally an operator-managed
`LLM_PRICING_VERSION` (for example an internal price-sheet ID and effective
date). If no explicit version is given, telemetry records a SHA-256 fingerprint
of the exact configured rates and currency. Attempt records retain both rates,
the version/fingerprint, and the calculated estimate.

Configuration template only—replace quoted placeholders with the exact
configured model identifiers and verified numeric rates before enabling it.
Do not use the placeholders as prices:

```json
{
  "gemini": {
    "<configured-gemini-model>": {
      "input_per_million_tokens": "<verified numeric input rate>",
      "output_per_million_tokens": "<verified numeric output rate>"
    }
  },
  "groq": {
    "<configured-groq-model>": {
      "input_per_million_tokens": "<verified numeric input rate>",
      "output_per_million_tokens": "<verified numeric output rate>"
    }
  }
}
```

Set the JSON mapping in private runtime configuration as `LLM_PRICING`; do not
commit credentials or runtime `.env` files. Set `LLM_PRICING_CURRENCY` and
`LLM_PRICING_VERSION` alongside it. If rates or usage counts are missing, the
estimate stays `null`; zero is reported only when configured rates and actual
token counts calculate to zero.

Historical benchmark re-pricing is an explicit offline operation. It reads a
saved benchmark report and writes a separate cost sidecar; it does not edit the
original measurements and does not make provider calls:

```powershell
Set-Location C:\PRODUCTS\TestNova\backend
$pricingVersion = 'replace-with-verified-price-sheet-version'
..\myenv\Scripts\python.exe -m app.evaluation.benchmark_cli cost `
  evaluation_results\gemini-real-run\gemini-real-20261113.json `
  --output "evaluation_results\comparison\gemini-real-20261113-cost-$pricingVersion.json"
```

The sidecar stores the original report SHA-256, dataset/run attribution, exact
pricing configuration, per-attempt token counts and estimates, and coverage.
Use a new output filename for each pricing version; existing outputs are not
overwritten. Partial cost totals are marked with coverage and currency; mixed
currencies are never combined into a single amount.

## Durable LLM telemetry

Application calls append safe per-request telemetry events to the configured
`LLM_TELEMETRY_PATH`. The default is
`backend/data/llm_telemetry.jsonl`; relative configured paths resolve beneath
the backend directory. `LLM_TELEMETRY_MAX_BYTES` defaults to 10 MiB and
`LLM_TELEMETRY_BACKUP_COUNT` defaults to five rotated files. Only attempt
metadata, token counts, safe error categories, pricing metadata, and correlation
IDs are stored—never prompts, raw model content, credentials, or authorization
headers. POSIX files use owner-only mode where supported; on Windows, access is
inherited from the containing directory's ACL.

`get_persisted_telemetry_summary()` is a read-only backend service function that
loads active and retained rotated files and returns the aggregate summary. No
monitoring API endpoint or frontend integration is added. Malformed or
incomplete historical JSONL records are skipped and logged without printing
their contents. Retention bounds local disk use but eventually drops older
telemetry.

Writes are coordinated between threads and service instances in one process.
The file store does not provide cross-process or multi-machine locking, shared
rotation, or distributed durability; deployment must remain single-process
unless a separately designed shared telemetry service is approved. A telemetry
write failure is logged by exception type and does not fail a successful model
call.

## Existing real-run review status

The first five-example live runs and their raw outputs are retained under
`backend/evaluation_results/{gemini-real-run,groq-real-run}/`. The structured
preliminary review is in
[`quality_review.json`](../backend/evaluation_results/comparison/quality_review.json)
and
[`quality_review.md`](../backend/evaluation_results/comparison/quality_review.md).
It records per-case evidence, coverage, correctness, clarity, specificity,
assumptions, redundancy, usefulness, and automated findings. It is explicitly
assistant-generated, not human-reviewed; reviewer decision, comments, dimension
ratings, and final rating remain blank. Valid citation IDs and lexical overlap
are not semantic proof. The original reports and raw outputs are unchanged.

## Reproducibility and limitations

The runner supplies identical system/user prompt templates and evidence ordering
for every provider/model. It records dataset version and content hash, example
IDs, provider, model, temperature, fallback setting, and prompt-template
hashes. Use a fixed dataset version, selected examples, model identifier, and
run configuration to compare future prompt, retrieval, model, or adapter
changes. Model output may
still vary between live calls; temperature zero does not guarantee bitwise
repeatability.

Evaluation is limited by the small synthetic dataset and lexical deterministic
checks. Semantic evidence entailment and subjective usefulness need human
review. Latency and model-returned token usage are provider-reported run
measurements, not a standardized independent load test. Application telemetry
is durable only within the configured local JSONL file and its retained
rotations; benchmark result files remain explicit local artifacts, and there
is no database-backed evaluation history. Mocked output is never a valid basis
for model-performance or cost claims.
