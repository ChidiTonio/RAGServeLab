# Repeated evidence-length experiment — protocol v1

## Purpose

Characterize client-observed latency and server-reported processing
durations across the existing 0-, 8-, and 24-distractor fixtures.
This is an exploratory repeated experiment, not a confirmatory test.

Calibration is preserved at commit 1c19cb6 and is excluded from
repeated-run summaries.

## Fixed configuration

- Model: qwen2.5:3b
- Model digest:
  357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b
- Server version expected: 0.40.6
- Endpoint: http://127.0.0.1:11434
- Temperature: 0
- Seed: 42
- num_ctx: 4096
- num_predict: 64
- Generation keep_alive: 5m
- One sequential A-B-C trial per length visit
- Fixtures and prompt hashes: workloads/evidence-length-v1/manifest.json

Verify each report's prompt and settings against the fixtures.
Record deviations rather than silently combining incompatible runs.

## Predetermined schedule

| Block | Position 1 | Position 2 | Position 3 |
|---|---:|---:|---:|
| 1 | 0 | 8 | 24 |
| 2 | 8 | 24 | 0 |
| 3 | 24 | 0 | 8 |
| 4 | 0 | 24 | 8 |
| 5 | 24 | 8 | 0 |
| 6 | 8 | 0 | 24 |

Execute blocks in the listed order.
This schedules six A-B-C trials per length: 18 trials and 54 measured
generations, excluding preparation requests.

Each length appears twice in each within-block position.
The schedule is balanced, not randomized.

## Condition preparation

A: unload and verify target digest absent, then generate.
B: unload and verify absent, preload with num_ctx 4096, verify present,
then generate without prewarming the workload prompt.
C: verify target digest present, then repeat B's prompt.

Preserve the harness's A-B-C ordering and preparation checks.
B's measured generation latency excludes its separate preload.

## Measurements and summaries

Primary:
- B client first-text latency.
- B server prompt-evaluation duration.

Secondary:
- Paired B-minus-C differences within each trial.
- Client total latency for each condition.
- Server generation tokens per second and generated token counts.
- A server load duration and client first-text latency.
- Reported prompt and cached-token counts.
- Completion reasons and answer scores.

Report individual observations plus median and minimum-to-maximum
range per length and condition. Do not pool A, B, and C.
Use within-trial pairs for B-C summaries.
Do not treat the 54 generations as independent replicates.

## Answer scoring

Apply the existing manifest rubric to every response.
Record fact correctness, citation correctness, unsupported factual
claims, and format compliance separately from raw reports.
Retain incorrect answers and unexpected completion reasons.

## Execution and provenance

Keep other Ollama clients idle and power settings unchanged.
Do not add unscheduled warmups or intentional pauses.
Record interruptions and observable environment changes.

Use one new report per length visit. Include block, position,
distractor level, and UTC timestamp in its filename.
Preserve report bytes and record SHA-256 hashes.
Record the harness commit used for execution.

Stop on a failed invocation or failed validation.
Preserve the failed report. Document any replacement and its schedule
position explicitly; never silently retry or overwrite reports.
Report failures alongside successful-run summaries.

## Interpretation limits

Balanced order does not eliminate thermal, filesystem-cache, or
other machine-state effects.
Model absence is not proof of cold filesystem or OS caches.
Cache-counter semantics remain unresolved.
Server residency accounting is not independent GPU telemetry.
Prompt counts alone do not independently prove absence of truncation.
Evidence length also changes target-to-question distance.
Output length can vary and affect generation comparisons.
One fixed synthetic question cannot establish general grounding quality.
