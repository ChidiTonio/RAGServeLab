# RAGServeLab

A research-led benchmarking project studying latency, concurrency, and
evidence-grounding trade-offs in locally served retrieval-augmented
generation (RAG) workloads.

## Current scope

The implementation includes a single-request streaming Ollama probe, evidence-length experiment records, and offline concurrency implementation, validation, and calibration-planning support.

Regression validation for the latest offline input-hardening changes remains pending. Live concurrency calibration and measured concurrency execution remain separately gated. Retrieval integration and evidence-grounding evaluation are not implemented.

See [the concurrency protocol](docs/concurrency-protocol-v1.md) and
[the hardening continuation record](docs/concurrency-hardening-continuation-20261023.md)
for scope, evidence, limitations, and outstanding validation.


Research directions:

- Residency: how model residency affects response latency.
- Context: how evidence length affects latency, throughput, and grounding.
- Concurrency: where increased client pressure improves throughput or
  increases waiting time.

## Requirements

- Python; the current harness was verified with Python 3.14.4.
- A reachable Ollama server at http://127.0.0.1:11434.
- An installed model, defaulting to qwen2.5:3b.

The probe and unit tests use only the Python standard library.
No pip dependencies are required for the current implementation.

The recorded smoke runs used a WSL2 Linux client and Ollama 0.40.6.
These are recorded environment details, not minimum version requirements.

## Setup and tests

From the repository root:

    python3 -m venv .venv
    source .venv/bin/activate

Test coverage has expanded beyond the initial probe suite. The latest offline input-validation regressions remain unexecuted; source coverage is not a passing-test result.

For the current hardening workflow, do not use unrestricted test discovery. Scoped regression execution requires a separately reviewed entry point and explicit authorization, as described in the hardening continuation record.

Unit tests do not independently verify a live server or GPU placement.

## Run a probe

Ensure Ollama is reachable and the selected model is installed.
For a server on another operating system, manage models on that server.

    python probe.py --help
    python probe.py --model qwen2.5:3b --out results/manual-001.json

Use a new output filename for each run. The probe rejects an output path
that already exists.

Only --model and --out are CLI options. The endpoint, prompt, and generation
settings are currently defined in probe.py:

- Prompt: "Explain retrieval-augmented generation in three concise sentences."
- Streaming: enabled.
- Keep-alive: 5m.
- Temperature: 0.
- Seed: 42.
- Context setting: 2048.
- Maximum predicted tokens: 128.

A fixed seed and temperature do not establish exact output reproducibility.

## Measurements and timing boundaries

The client clock starts immediately before opening the generation request.

- client_first_text_s: elapsed time until the first non-empty response
  fragment is parsed.
- client_total_s: elapsed time until the completion event is consumed.
- runtime_metrics: Ollama-reported durations converted from nanoseconds
  to seconds, token counts, and generation tokens per second.

Client measurements exclude pre-request metadata/residency queries,
post-request residency queries, and report-file writing. First text is a
stream-fragment measurement, not an exact token-arrival measurement.

Generation throughput is eval_count divided by eval_duration_s.
It is not end-to-end request throughput.

Metadata queries use a 10-second urllib timeout; generation uses 180 seconds.
These are blocking-operation timeouts, not a strict whole-run deadline.

## Reports and success criteria

Reports include the request, prompt hash, model metadata, server version,
residency snapshots, generated answer, final server event, and timings.

The raw final event preserves server fields such as prompt_eval_cached_count.
That field is not currently copied into runtime_metrics.

A successful report requires a completion event and non-empty generated text.
It does not establish instruction compliance, factual correctness, or grounding.

Reports can contain prompts, generated text, model metadata, and local
environment details. Review them before committing or publishing.

## Initial findings

See docs/smoke-baseline.md for the first two observations and limitations.
This pair is a smoke check, not a controlled experiment or latency distribution.

## Next milestones

1. Complete scoped regression validation for offline concurrency hardening.
2. Preserve and review experiment provenance and control evidence.
3. Authorize and run concurrency calibration and the measured schedule separately.
4. Verify placement using server logs and GPU telemetry.
5. Integrate retrieval and evaluate evidence-grounded answers.
