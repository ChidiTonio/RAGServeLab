# Initial smoke observations

## Provenance

Recorded on 2026-10-19 UTC using probe.py.
Supporting local reports:

- results/smoke-001.json
- results/smoke-002.json

Harness commit: 04a2bb7.
All five standard-library unit tests passed after this commit was pushed.

The reports have not yet been added to version control.

## Shared request conditions

- Model: qwen2.5:3b; reported 3.1B parameters, Q4_K_M quantization.
- Model digest:
  357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b
- Prompt: "Explain retrieval-augmented generation in three concise sentences."
- Prompt SHA-256:
  2800cb94d71fa012f4fc3a4f2a791ab66fa1ea95232ba6e1b216f506e7d6fc70
- Temperature 0; seed 42; num_ctx 2048; num_predict 128.
- Streaming enabled; keep_alive 5m.
- Ollama reported version 0.40.6.
- Client: Python 3.14.4 on WSL2 Linux.

## Observed measurements

| Metric | smoke-001 | smoke-002 |
|---|---:|---:|
| Model listed as resident before request | No | Yes |
| Client first non-empty text (s) | 60.669345 | 0.027148 |
| Client total (s) | 61.465164 | 0.754205 |
| Server total (s) | 61.461285 | 0.750153 |
| Server load duration (s) | 41.378475 | 0.004964 |
| Server prompt evaluation (s) | 19.261104 | 0.012695 |
| Reported prompt token count | 41 | 41 |
| Reported cached prompt token count | 0 | 40 |
| Generated token count | 57 | 58 |
| Server generation duration (s) | 0.793292 | 0.724965 |
| Generation throughput (tokens/s) | 71.85 | 80.00 |

## Interpretation

For smoke-001, reported loading plus prompt evaluation totals approximately
60.640 seconds, close to the 60.669-second client first-text latency.
Most observed delay occurred before sustained output generation.

The immediate repeat was faster, but both model residency and reported
prompt-cache reuse changed. This pair does not isolate residency's effect.

Client totals exceeded server totals by approximately 3.88 ms and 4.05 ms.
These differences are not measurements of network latency alone.

After both requests, Ollama reported model size and size_vram as
2,085,974,179 bytes. This is consistent with full GPU residency as reported
by the server, but is not independent operation-level placement verification.

## Quality observations

Both streams completed successfully with non-empty text.
Both answers had two sentences despite the instruction to produce three.
The answers differed despite identical request settings.

No retrieved evidence was supplied, so grounding was not evaluated.

## Limitations and follow-up

- One observation per condition; no variance or percentile estimates.
- No explicit unload/preload protocol.
- Residency and prompt-cache state changed together.
- No independent GPU telemetry or server-log capture.
- The 19.261-second prompt evaluation duration needs investigation.
- Output length differed slightly: 57 versus 58 generated tokens.

Next, define repeated trials that separate residency from prompt-cache reuse,
record the achieved state, and preserve failures as well as successful runs.
