# First sequential A-B-C baseline

## Provenance

- Report filename timestamp: 2026-10-19 at 12:33:50 UTC.
- Benchmark implementation commit: `fd5f175`.
- Raw report: `results/abc-qwen2.5-3b-20261019T123350Z.json`.
- Raw report SHA-256:
  `c7d5976693666b4615c00a2d53728fd90acc0c7018abe5eb9eb4d85b3808dbdf`.
- Server-reported Ollama version: `0.40.6`.
- Model: `qwen2.5:3b`, server-reported 3.1B parameters, Q4_K_M.
- Model digest:
  `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`.
- Live outcome: five successful trials, 15 successful measured generations,
  CLI exit code 0.

## Request settings

Prompt: "Explain retrieval-augmented generation in three concise sentences."

- `temperature`: 0
- `seed`: 42
- `num_ctx`: 2048
- `num_predict`: 128
- `keep_alive`: `"5m"`
- Streaming enabled.

## Protocol and measurement boundary

Each trial ran sequentially:

- **A — nonresident:** unload, verify target digest absent, then generate.
- **B — resident, unwarmed:** unload again, verify absent, preload with the
  workload's context setting, verify present, then generate.
- **C — resident, repeated:** verify present, then repeat B's request without
  an intervening generation or residency-control request.

Every required preparation operation reported success.

Client generation latency includes connection setup and stream consumption.
It excludes metadata queries, preparation operations, and report persistence.
First-text latency measures arrival of the first non-empty response fragment,
not independently instrumented server time to first token.

Preloading shifts model-loading cost into preparation; it does not remove
that cost from the system.

## Descriptive results

Values below are per-condition medians across five requests.

| Metric | A | B | C |
|---|---:|---:|---:|
| Client first-text latency (s) | 2.5840 | 0.0950 | 0.0288 |
| Client total latency (s) | 3.3119 | 0.8211 | 0.7852 |
| Server-reported load duration (s) | 2.5011 | 0.0052 | 0.0050 |
| Server-reported prompt evaluation duration (s) | 0.0758 | 0.0813 | 0.0128 |
| Server-reported generation throughput (tokens/s) | 77.8477 | 78.5099 | 77.2606 |

Comparisons of these medians show:

- A's first-text latency was approximately 27 times B's.
- C's first-text latency was approximately 70% lower than B's.
- C's prompt evaluation duration was approximately 84% lower than B's.
- C's total latency was approximately 4.4% lower than B's.

These are ratios of condition medians, not medians of paired-trial changes.

A's reported load duration accounts for most of its time before first text.
A trial 1 was notably slower: 6.7736 s to first text and 6.6314 s reported
loading duration. Subsequent A first-text latencies ranged from 2.3935 to
2.6046 s. Trial 1 is retained; its additional cost has not been attributed
to a verified mechanism.

## Cache telemetry

Every request reported `prompt_eval_count=41`.

- All A and B requests reported `prompt_eval_cached_count=0`.
- All C requests reported `prompt_eval_cached_count=40`.

This supports prompt-cache reuse in C, alongside reduced prompt-processing
duration. Counter semantics have not been independently verified; subtracting
cached count from prompt count is not used to infer newly evaluated tokens.

## Generation and output behavior

- All ten A/B answers were identical in the inspected output and reported
  57 generated tokens.
- All five C answers were identical in the inspected output, differed from
  A/B, and reported 58 generated tokens.
- Every answer contained two sentences, failing the three-sentence instruction.
- C had greater total latency than B in trials 1 and 4.
- Median generation throughput showed no clear improvement from repetition.

Identical request settings did not guarantee identical output across serving
conditions. The output difference coincided with cache reuse, but its cause
is unresolved. No cache-specific numerical mechanism has been established.

## Limits and interpretation

This is a preliminary descriptive baseline for one model, one short prompt,
and five fixed-order sequential trials.

- Verified nonresidency does not establish a cold filesystem cache or reset
  all server and operating-system state.
- Residency snapshots establish observed state at query time, not continued
  residency or independently verified GPU execution.
- Fixed ordering leaves possible order and system-state effects unresolved.
- Generated output lengths differ between B and C, affecting completion-time
  comparisons.
- The short warm-request latency is largely generation time, limiting the
  effect of prompt-processing savings on total latency.
- The prompt supplies no retrieved evidence: this is not an evidence-grounding
  evaluation or an end-to-end retrieval benchmark.
- This run does not characterize long-context workloads or concurrency.
- No confidence intervals or general causal estimates are claimed.

## Summary

Verified model residency substantially reduced first-text latency in this
run. Repeated resident requests consistently reported prompt-cache reuse and
reduced prompt-processing latency, without a clear generation-throughput
improvement. Outputs repeated within conditions but differed across repeated
and non-repeated conditions, and all failed the sentence-count instruction.

The raw report is preserved unchanged.
