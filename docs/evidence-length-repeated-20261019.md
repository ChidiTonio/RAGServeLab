# Repeated evidence-length experiment — 2026-10-19

## Design

Protocol: `docs/evidence-length-repeated-protocol-v1.md`.

Six balanced, nonrandomized blocks covered all six permutations of
0, 8, and 24 distractors. There were 18 sequential A–B–C trials and
54 measured generations, excluding preparation requests.

- A: model unloaded and absence verified before generation.
- B: model separately preloaded and residency verified; workload prompt
  not prewarmed. Measured latency excludes preparation.
- C: residency verified, then B's prompt repeated.

Configuration: `qwen2.5:3b`, temperature 0, seed 42,
`num_ctx=4096`, `num_predict=64`.

Model digest:
`357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`

## Execution provenance

Run: `results/evidence-length-v1-repeated-20261019T150106461228Z/`

Analysis subdirectory: `analysis-20261019T170642069989Z/`

Recorded execution commit:
`9534ee8e66fba27a9d738f601c52d3ccdba5bdd0`

Journal start: `2026-10-19T15:01:06.462653+00:00`.
Completion: `2026-10-19T15:03:12.853769+00:00`.

The journal records 18 invocations, all with exit code 0 and validation
passes, followed by a complete event. No failure or replacement is
recorded. The prior analysis reported 18/18 reports passing hash and
protocol checks. All 54 measured generations ended with `done_reason=stop`.

Recorded SHA-256 values:

- Journal: `18a82d6f45832420172590cc6a9484e971d93719ee4ff29d4313f9180ff7de7c`
- Runner: `e4507b2dfec440467d9ff37885274a2cacff9cafb3f63389ad824868cdc96ac9`
- Protocol: `8343115eeadc7bc6811cca3cb02c8402cdc0ac6fa6ac1244c4117f6c9579ee2d`
- Analysis script: `f34e6a91283a5b3b45e9f2d9a219d1da7afbda6a722a09d93e8dd01d570d87c1`

The inspected current analysis-script hash matched its recorded hash.
Execution provenance comes from the journal, not the current checkout.

## Primary findings

B measurements are median [minimum, maximum], in milliseconds,
with six observations per evidence level.

| Distractors | Client first-text latency | Server prompt evaluation |
|---|---:|---:|
| 0 | 115.1 [111.8, 121.4] | 101.4 [98.4, 110.1] |
| 8 | 202.5 [193.1, 207.4] | 188.4 [181.0, 192.5] |
| 24 | 395.3 [384.1, 404.6] | 374.9 [358.2, 385.1] |

Both measures increased with evidence level, with nonoverlapping
observed ranges. This is descriptive, not a confirmatory test or
evidence of linear scaling.

## Secondary findings

A median first-text latencies were 2,495.1, 2,630.0, and 2,764.8 ms.
A/B ratios of group medians were 21.7×, 13.0×, and 7.0×, respectively;
these are not median paired speedups. A median server load durations
were approximately 2.38–2.44 seconds, versus 4.6–5.7 ms for B.

Median within-trial B-minus-C reductions, in milliseconds:

| Distractors | First text | Total latency | Prompt evaluation |
|---|---:|---:|---:|
| 0 | 89.8 | 105.1 | 88.0 |
| 8 | 176.4 | 185.4 | 174.8 |
| 24 | 358.7 | 365.9 | 360.8 |

C was faster on these three measures in all 18 pairs. Timing and
cache-counter patterns are consistent with prompt-cache reuse;
exact counter semantics remain unresolved.

Median paired C-minus-B generation-throughput differences were
approximately +2.95, +3.61, and +2.47 tokens/s. Each evidence level's
paired range included negative and positive differences: repetition
did not uniformly improve generation throughput.

## Elevated first observation

Block 1, position 1, 0-distractor A had first-text latency of 6,758.8 ms,
server load duration of 6,609.8 ms, and prompt evaluation of 141.1 ms.
Loading accounted for approximately 97.8% of first-text latency.
The cause is unknown; the observation is retained without replacement.

Report: `b01-p1-d00-20261019T150106468198Z.json`.

## Answer review

Assistant-assisted conversation review against the manifest rubric
found 54/54 answers fact correct, citation correct (`[E001]`), and
format compliant. No extra/conflicting citations or unsupported claims
were identified. A/B/C text was identical within each trial.

Exact saved text was checked against reviewed variants before persistence.
This is not independent human scoring or an independent automated
quality assessment.

Reviewed file: `answer-scoring-assistant-reviewed.csv` in the analysis
subdirectory.

SHA-256:
`4444bb9e8fe2439665b78f66d6504ce8e69b759484bd5fb50fb4f2256fffedb4`

The original scoring template and analysis provenance remain unchanged.
The original provenance's pending-review status is historical;
this section records the subsequent assistant-assisted review.

## Limitations and environment

Original analysis provenance states that other-client activity,
power settings, and additional interruptions require operator
confirmation and were not independently verified. Terminal output
showed typed `q` and `exit`; measurement impact is undetermined.

Balanced order does not eliminate time or machine-state effects.
A–B–C order is fixed. Model absence does not imply cold OS/file caches.
Server residency accounting is not independent GPU telemetry.
Prompt counts alone do not prove absence of truncation.
Added evidence also increases target-to-question distance.
Output length may affect generation comparisons.
One synthetic question does not establish general grounding quality.
The 54 generations are not 54 independent experimental replicates.

## Retained outputs

Raw reports and the execution journal remain in the run directory.
Observations, paired differences, summaries, report hashes, provenance,
original scoring template, and separate reviewed scores remain in the
analysis subdirectory. Pilot and calibration data are excluded from
repeated-run summaries.
