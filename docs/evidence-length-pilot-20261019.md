# Evidence-length calibration pilot — 2026-10-19

## Scope and protocol

Three fixed synthetic evidence workloads contained 0, 8, or 24 distractor
passages. The answer-bearing passage E001 remained first; distractors were
nested. Instructions and question were identical across levels.

Each level received one sequential A–B–C trial. Execution order was
24 → 0 → 8 distractors. This was calibration, not a replicated comparison.

Fixtures and scoring rubric were committed at ca1459c.
Workload controls were committed at e75337a.

Settings: qwen2.5:3b, temperature 0, seed 42, num_ctx 4096,
num_predict 64. Server version: 0.40.6.

Model digest:
357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b

## Validation and manual scoring

All reports, trials, conditions, and preparation steps reported success.
Exact report prompts and options matched the committed fixtures.
A verified model absence; B verified absence, preloaded, then verified
presence; C verified presence before repeating B's prompt.

B/C residency observations reported context_length 4096 and equal size
and size_vram values of 2163568803 bytes. This is server accounting,
not independent operation-level GPU telemetry.

All nine responses passed fact correctness, citation correctness, and
format compliance. No unsupported factual claims were observed.
Every response stated 17 days and cited E001.
Every completion reported done=true and done_reason="stop".
Outputs contained 26 tokens at 0/8 distractors and 28 at 24 distractors.

## Descriptive measurements

| Distractors | Prompt tokens | B first text (ms) | B prompt eval (ms) | C first text (ms) | C prompt eval (ms) |
|---|---:|---:|---:|---:|---:|
| 0 | 148 | 118.027 | 106.377 | 27.470 | 16.352 |
| 8 | 476 | 199.331 | 185.084 | 25.458 | 13.108 |
| 24 | 1132 | 390.319 | 369.939 | 42.473 | 17.283 |

A/B reported zero cached prompt tokens. C reported 147, 475, and 1131.
Cache-counter semantics remain unresolved.

B's first-text latency and prompt-evaluation duration increased with
evidence length in this pilot. C's prompt-evaluation duration remained
small. Generation throughput did not show a consistent repetition benefit.

A's server load durations were 4.476, 2.451, and 5.628 seconds at
0, 8, and 24 distractors respectively.

## Limitations

- One trial per level provides no estimate of between-trial variability.
- Run order and machine state may influence cross-level differences.
- Model nonresidency does not imply cold filesystem or OS caches.
- B's generation latency excludes its separately recorded preload.
- Target-to-question distance increases alongside evidence length.
- Output token counts differ between the longest and shorter workloads.
- Reported prompt counts alone do not independently rule out truncation.
- One synthetic question cannot establish general grounding quality.
- Independent GPU telemetry was not collected.

## Raw report provenance

Files below are under results/ and must remain unchanged.

- evidence-length-v1-d00-calibration-20261019T133539Z.json
  SHA-256: 1c93c6289556fbddaf89d36c74f8ebdc60b69d1eb181b3b3916c4d7a01c253b3
- evidence-length-v1-d08-calibration-20261019T133547Z.json
  SHA-256: b2d892dbf8c648000f58f44d66042d6fb02c7c87d43c02c2ad5cf7dfe9405d55
- evidence-length-v1-d24-calibration-20261019T132605Z.json
  SHA-256: 39af0692bcf1e52d38b03c4cc311e8533896c008308f00c3b2daa918ec6910c1
