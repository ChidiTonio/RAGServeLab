# RAGServeLab Project Summary

## Scope and status

This week's work includes offline input-validation and reporting improvements
for the RAG/inference experiment workflow.

The three experiment levels were reported as completed by the project owner.
Their detailed results have not been supplied in this handoff, so their
performance and quality outcomes remain unverified here.

Custom sandbox development is deferred to the separate
`inference-regression-guard` project. It is not a requirement for this
week's closeout unless the original acceptance criteria explicitly require it.

## Results supported by the available evidence

Source inspection confirms that the offline validation suite covers:

- Valid offline plans for calibration and measured modes.
- Twelve malformed-manifest cases, including missing fields,
  duplicate target entries, invalid lengths, and incorrect hash types.
- Persistence of malformed-manifest failures as structured reports.
- Seven nonfinite JSON cases, including NaN, infinities, numerical
  overflow, and nested overflow values.
- Assertions that invalid evidence is rejected before downstream
  evidence validation and execution planning.
- Assertions that failure reports do not authorize live execution.

The suite contains four test methods and 33 intended subcases.
These are source-level coverage observations, not evidence that the
suite executed successfully.

The valid-plan test expects:
- Calibration: 3 batches and 7 requests.
- Measured: 18 batches and 42 requests.
- Live execution disabled in both offline plans.

## Improvement demonstrated

The concrete improvement visible in the code is a stronger offline
validation and failure-reporting contract:

- Invalid inputs are explicitly covered by regression assertions.
- Failure reports are checked for their error stage and type.
- Nonfinite evidence is expected to be rejected before downstream use.
- Offline planning is expected to remain non-authorizing.

This supports more reliable experiment preparation and clearer
diagnosis of invalid inputs.

It does not, by itself, demonstrate better retrieval, answer grounding,
latency, throughput, memory efficiency, or concurrency performance.
Those improvements require the completed experiment results and,
where appropriate, a comparable baseline.

## Recorded experiment configuration

The workload manifest records the following PLANNED pilot settings:

| Setting | Recorded value |
|---|---|
| Workload | evidence-length-v1 |
| Model tag | qwen2.5:3b |
| Temperature | 0 |
| Seed | 42 |
| Context setting (`num_ctx`) | 4096 |
| Output limit (`num_predict`) | 64 |
| Trials per level | 1 |
| Conditions | A, B, C |
| Answer passage position | First |
| Distractor construction | Nested |
| Expected answer | 17 days, supported by E001 |

The manifest labels these settings "Not executed; settings subject
to calibration." They must not be presented as the actual settings
of the completed runs without checking those run records.

## Fixture provenance

The manifest declares these prompt fixtures:

| Fixture | UTF-8 bytes | Characters |
|---|---:|---:|
| distractors-00.txt | 608 | 608 |
| distractors-08.txt | 2176 | 2176 |
| distractors-24.txt | 5312 | 5312 |

Declared SHA-256 values:

- distractors-00.txt:
  e0cb1b9b3bea653221c650479235d7004da12f0fcd0e9d35d0faebe900e273d9
- distractors-08.txt:
  50d4fc87d0f9c7ca2ea79ae9317477250f8ecad5fe8968e7d8f5533223a3d6b3
- distractors-24.txt:
  d74da707c2be86d8398002f18fe458bca0fb4fdd2d3dde347ea1c0c00d42f18e

The copied distractors-08.txt hash matches its manifest declaration.
The other two fixture hashes were not independently verified in the
available output.

## Source provenance

Original repository:
`/home/chidinzoms/ragservelab`

SHA-256 values reported for staged source copies:

- concurrency_preflight.py:
  7a2b73bb4f51f3696c8391bc46326f371cb5e6eba54e597dfd5100d01255e004
- concurrency_run_store.py:
  23e0607b50234357ab1c42b06ed0a05698bf990a8754fc77fc78d55d914861e6
- concurrency_experiment.py:
  9e819ca3e043229591801eff6a33355cbfd7096aa61209563e8d24455ac73f5f
- report_store.py:
  f836e8753758b53c90795047d820f81b544a402aa4eb0ef1230837bad791455d
- probe.py:
  74554894477a5cece6c2e988ea16d9d55903427b92bf17754f5ad84790d4b586
- test_concurrency_offline_input_validation.py:
  ecefaf8a169bc40d0829727ffeabda99c20da4ec51f279a2977dbd894c1757de

Manifest SHA-256:
95c8bfe9cbf3255a417c77c34dd937b311bf238db0108905e4e4036496180a86

These identify the staged files, not necessarily the source versions
used in earlier experiments.

## Reproduction records still needed

To reproduce the completed experiments, retain their existing:

- Run commands and actual configuration.
- Git commit and any relevant local changes.
- Model artifact digest, serving software version, and hardware details.
- Input fixture hashes and protocol version.
- Raw responses, timing records, token counts, and completion reasons.
- Scoring results and baseline, if claiming an improvement.

These records have not been supplied here. The planned manifest and
current source hashes are not substitutes for actual run provenance.

## Limitations

- One synthetic question cannot establish general RAG grounding quality.
- One trial per level is exploratory, not a statistical comparison.
- Increasing distractors also increases question-to-target distance.
- Bytes and characters are not model-token counts.
- Reported prompt counts alone do not prove absence of truncation.
- Successful transport does not establish a complete or correct answer.
- Test source inspection does not establish a passing test run.
- No measured quality or inference-performance improvement can be
  concluded from the evidence currently available.

##  conclusion

Reportable progress: source-level offline validation and reporting work,
explicit experiment configuration, and recorded fixture/source provenance.

Experiment outcomes: owner-reported completion of three levels; detailed
results pending review.

Security sandbox: deferred, not executed, and not counted as a completed
validation result.
