# Concurrency experiment — protocol v1

Status: Draft pending offline tests and separately authorized calibration.
Do not execute the measured schedule until protocol and implementation
are finalized and committed.

## Purpose and scope

Characterize client concurrency, client-observed latency, and aggregate
completion throughput for locally served RAG requests.

This is an exploratory finite-batch experiment, not sustained-load
capacity testing. Client concurrency does not establish server parallelism.
Earlier A-B-C observations are not pooled with this experiment.

## Fixed configuration

- Model: qwen2.5:3b
- Model digest:
  357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b
- Expected server version: 0.40.6
- Endpoint: http://127.0.0.1:11434
- Fixture: workloads/evidence-length-v1/distractors-08.txt
- Prompt SHA-256:
  50d4fc87d0f9c7ca2ea79ae9317477250f8ecad5fe8968e7d8f5533223a3d6b3
- temperature: 0
- seed: 42
- num_ctx: 4096
- num_predict: 64
- stream: true
- keep_alive: 5m

Preserve exact fixture bytes and validate against the existing manifest.
Each worker owns a fresh payload, request, connection, and parsing state.
Do not add identifiers or cache-busting text to prompts.

## Server configuration and environment

Before calibration, record available Windows serving-process configuration
and startup-log evidence for parallelism, queue limits, and device placement.
Distinguish explicit settings, observed effective settings, and unknowns.
WSL environment variables do not establish Windows server settings.
An unset variable is not evidence of its effective default.

Record server version, model metadata, client Python/platform, power
settings, other-client activity, and interruptions.
Keep serving configuration and power settings unchanged during a run.
Keep other Ollama clients idle; label operator statements as such.
Unknown effective parallelism limits interpretation but is not fabricated.

## Experimental unit and schedule

Each batch contains exactly C measured requests with C in {1, 2, 4}.
Prepare all workers before one coordinated release.
Do not replenish finished requests or overlap batches.

| Block | Position 1 | Position 2 | Position 3 |
|---|---:|---:|---:|
| 1 | 1 | 2 | 4 |
| 2 | 2 | 4 | 1 |
| 3 | 4 | 1 | 2 |
| 4 | 1 | 4 | 2 |
| 5 | 4 | 2 | 1 |
| 6 | 2 | 1 | 4 |

Execute in listed order: 18 batches and 42 measured requests.
Each concurrency appears twice in each within-block position.
The schedule is balanced, not randomized.
Batches are comparison units; requests within a batch are dependent.
Request count varies with concurrency, so this is not an equal-sized-job
comparison or a steady-state capacity estimate.

## Preparation and cache policy

Before EACH batch:
1. Ensure previous client workers have terminated.
2. Unload the target model.
3. Verify the target digest absent with bounded residency queries.
4. Preload using an empty prompt and num_ctx=4096.
5. Verify target digest present and reported context length=4096.
6. Prepare workers and release the batch.

Retain all preparation telemetry. Exclude preparation from measurements.
No workload-prompt warmups or unscheduled intentional cooling pauses.

Condition: resident, prompt-unwarmed finite batch.
This means the harness has not submitted the fixture after reset.
It does not independently prove zero cached tokens or cold OS caches.
Identical requests may affect cache state within a batch.

After each batch, verify residency and retain the snapshot.
A snapshot does not establish uninterrupted residency or GPU placement.
Retain reported load durations and evidence of allocation changes.

## Execution and timing

Use standard-library threads with exactly C ready workers.
Serialize requests before release.
Use one shared monotonic clock for release, starts, and terminal times.

Request timing preserves probe semantics:
- Start immediately before opening the HTTP request.
- First text after decoding the first nonempty response event.
- Completion after consuming a done=true event.
- Include connection setup and stream parsing.
- Exclude serialization, preparation, and report writing.

First text is not an independently measured first token.
Empty events do not qualify as first text.

Record release-to-start delays and earliest-to-latest start spread.
Record request-based and release-based latencies separately.
Coordinated release does not prove simultaneous server arrivals.

Batch duration is release to the latest worker terminal time.
Also retain earliest-start-to-latest-completion span for successful batches.

Only the coordinator writes reports.
Persist preparation and pending request identities before release.
No metadata queries, console output, or deliberate report writes between
release and the last worker terminal time.
Persist collected results after all workers terminate.

## Measurements and summaries

Primary batch measures:
- Successful request count divided by batch duration.
- Within-batch median request first-text latency.
- Within-batch maximum request completion latency.

Secondary:
- Individual request and release-based latencies.
- Within-batch median completion and maximum first-text latency.
- Batch duration, dispatch skew, and successful completion count.
- Sum of successful eval_count divided by batch duration.
- Per-request server durations, token counts, and generation tokens/s.
- Prompt-evaluation and cached-token counts.
- Errors, completion reasons, output lengths, and answer scores.

Aggregate output rate is not the mean of per-request server rates.
Do not sum overlapping server durations to obtain batch elapsed time.
Missing metrics remain unknown; aggregate output rate is unknown if a
required successful-request token count is missing.
Report failed batches separately from successful comparisons.

Retain every request and batch observation.
Per concurrency, summarize batch metrics with median and minimum-to-maximum
range across six batches; report available and missing counts.
Compare C=2 and C=4 against C=1 within each block.
Retain paired latency differences and valid positive-denominator
throughput ratios.

Supplementary pooled request summaries must disclose dependence and
unequal sample sizes. Do not estimate reliable tail percentiles or
declare saturation from this small finite-wave experiment.

## Failures and stopping

Success requires a completed stream with generated text.
Retain unexpected done_reason values and incorrect answers.
Answer quality is not an execution exclusion gate.

Preserve partial text, parsed events, elapsed time, and error details.
Current probe exceptions discard partial output; add a separate
failure-recording path without changing archived sequential behavior.

The urllib timeout is 180 seconds, not a hard whole-request deadline.
Record it as a transport timeout.

On a worker failure, collect already-released workers without retries.
Do not launch another batch. Client termination alone does not prove
server-side cancellation; require a verified reset before any replacement.

Stop on failed preparation, batch, validation, or persistence.
Preserve incomplete reports and pending identities.
An interruption is unknown/interrupted, not success or an invented timeout.
Document replacements explicitly; never overwrite or silently substitute.

## Answer review

Apply the existing evidence-length manifest rubric to each saved answer.
Score fact correctness, E001 citation correctness, extra/conflicting
citations, unsupported claims, and format compliance separately.
Retain completion reasons.
Store scores separately from raw reports.
Identify human, assistant-assisted, or automated review accurately.
Blank scores are pending, not passing.

## Offline tests and calibration

Default CLI behavior is offline; live requests require an explicit flag.

Offline tests must cover:
- Fixture hashes and exact fixed payloads.
- Exactly C ready workers and one coordinated release.
- Independent worker state and pre-release serialization.
- Injected-clock request and batch timing boundaries.
- Empty events, completed/incomplete streams, malformed events.
- Partial output, transport failures, and missing metrics.
- No retries and no next batch after failure.
- Unique output paths, overwrite refusal, and journal integrity.
- Coordinator-only persistence outside the measured interval.
- Bounded readiness failure handling without releasing a partial batch.

After offline tests pass and explicit authorization is obtained, run
separate calibration batches in order C=1,2,4 with the same preparation.
Preserve and label calibration reports; exclude them from measured data.
Calibration checks operability, dispatch skew, configuration evidence,
residency, failure behavior, and report completeness.

Resolve changes, rerun affected checks, and commit the final protocol and
implementation before executing the measured schedule.

## Provenance

Execute from a committed revision without tracked modifications.
Record execution commit, module/protocol/fixture hashes, exact payloads,
schedule, and environment evidence.
Verify code, protocol, fixtures, and revision remain unchanged during run.

Use a unique timestamped run directory with journal and one report per batch.
Include block, position, concurrency, UTC timestamp, and request identities.
Record preparation, release, outcomes, validation, completion, or stopping.
Preserve final raw report bytes and SHA-256 hashes.
Store derived analysis and scoring separately.

## Interpretation limits

Server queue time and execution-slot assignment are not directly measured.
Client-minus-server durations are not automatically queue time.
Balanced order does not eliminate thermal or machine-state effects.
Model absence does not establish cold filesystem caches.
Identical prompts may introduce within-batch cache reuse.
Cache-counter semantics remain unresolved.
Residency accounting is not independent GPU telemetry.
Prompt counts do not prove absence of truncation.
Variable-length short answers and finite waves limit capacity conclusions.
One synthetic question does not establish general grounding quality.
