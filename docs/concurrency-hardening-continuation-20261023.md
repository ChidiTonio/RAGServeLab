# Offline concurrency hardening — continuation record

Record date: 2026-10-23.

Status: Source changes committed locally; scoped control evidence reviewed;
durable evidence copies created and manifest verification reported successful.
Publication-content review, regression execution, and final closeout remain pending.


## Relationship to earlier project work

This work continues RAGServeLab's evidence-length research and adds the
offline implementation and validation controls needed for the
[concurrency protocol v1](concurrency-protocol-v1.md).

Earlier research records:
- [Evidence-length pilot](evidence-length-pilot-20261019.md)
- [Repeated evidence-length protocol](evidence-length-repeated-protocol-v1.md)
- [Repeated evidence-length observations and analysis](evidence-length-repeated-20261019.md)

These records provide project context. Earlier observations are not pooled
with the concurrency experiment. Client concurrency does not establish
server parallelism, and sandbox checks are not inference measurements.

## Verified local commit lineage

| Commit | Contribution |
|---|---|
| `d9564de` | Repeated evidence-length experiment and reviewed analysis; recorded `origin/main` reference |
| `1deae5d` | Offline concurrency protocol implementation and regression coverage |
| `3d344dd` | Offline calibration adapter and fail-stop regression tests |
| `b1ba8c3` | Offline input validation and preservation of synthetic test dependencies |
| `8ceaca8` | Rejection of overflowing JSON numbers in offline preflight evidence |

Overflow-fix commit:
`8ceaca89b4e77d04a50c24430eb272fdbb40ca62`.

Preparation baseline:
`b1ba8c345407dda3655a1b23c8ebd61dedc55fa0`.

Local ancestry verification confirmed the preparation baseline is an
ancestor of HEAD. Four commits are beyond the recorded `origin/main`
reference. Current GitHub publication has not been verified.

## Implemented JSON hardening

`ReportStore`-backed persistence rejects non-finite output values using
`allow_nan=False`. The standalone probe's report writer is outside this
hardening scope. Offline preflight float parsing rejects literals that
overflow to non-finite values, including `1e400`.

The scoped regression target is `OfflineInputValidationTests`: four test
methods with seven non-finite-input subcases. These regressions have not
been executed in this closeout.

## Preparation bundle

Original location: `/tmp/rag-offline-preparation.vNDPly5I`.

All nine entries in `MANIFEST.sha256` passed checksum verification.
The reviewed launcher expects this manifest digest:

`e9c34f5b36b753d53cb3c5d483bf934dfe7e5d1629dd5870fe25b3887bc01fdf`

Preparation provenance describes a locally resolved baseline plus two
hash-pinned patches, not an independently authenticated pristine baseline.
The original blocked-status records must remain unchanged as historical
evidence. Later progress is recorded separately.

## Sandbox implementation and filter revision

The reviewed launcher uses Bubblewrap namespaces, read-only snapshot and
control mounts, private temporary storage, no repository or home mount,
isolated Python startup (`-I -S -B`), and bounded time and resources.

Startup filter v2 adds Linux x86-64 `wait4` (syscall 61) after an observed
startup failure. The build record states that the locked filter remained
byte-for-byte unchanged.

Setting sandbox `HOME=/tmp/tests` avoided the observed import-time socket
failure. Native-call attribution remains unresolved. That limitation does
not block regression preparation, but does not waive authentication or
execution-authorization requirements.

## Reviewed instrumented control evidence

Runner location: `/tmp/rag-sandbox-full-smoke.Fcy4q7Ko`.

Runner manifest SHA-256:
`51c2e25a19c40e512e9c37be2c4320fa9ce00a7d38fa6a9540e178853af6135a`

Results location: `/tmp/rag-sandbox-smoke-results.IlXt6btp`.

Results manifest SHA-256:
`4384c212642e8e3695b1a4e370120433e1574a7b29678fb5310755e52310f49c`

All six runner-manifest entries and all six result logs passed checksum
verification.

| Case | Saved-log observation | Launcher-required exit |
|---|---|---:|
| allowed | `SMOKE_ALLOWED_PASS`; snapshot read-only and write-denial checkpoints | 0 |
| startup-socket | Expected seccomp-termination marker | 159 |
| locked-socket | Expected seccomp-termination marker | 159 |
| locked-fork | Expected seccomp-termination marker | 159 |
| locked-exec | Expected seccomp-termination marker | 159 |
| locked-x32 | Expected seccomp-termination marker | 159 |

The launcher schedules all six cases and checks exit statuses and markers
before producing the results manifest. The reviewed saved logs contain
markers, not exit-status records. An execution transcript binding these
results to the runner digest has not been supplied for this closeout.

Runner STATUS.txt retains earlier diagnostic and allowed-only preparation
text, while the actual launcher schedules a full suite. Preserve this
discrepancy explicitly; do not rewrite the historical status record.

This is instrumented, scoped control evidence. It is not an uninstrumented
acceptance run, exhaustive syscall-policy verification, or a project
regression result.

## Security and provenance limitations

- Checksum agreement establishes byte identity relative to a manifest,
  not safety or independent authenticity.
- The baseline was locally resolved, not independently pinned.
- Runtime library directories are trusted host inputs, not a minimal,
  independently authenticated runtime closure.
- Hash-before-use does not prevent concurrent same-user mutation.
- Python guards are defense in depth, not malicious-Python isolation.
- Seccomp is not pathname access control; namespace mounts are essential.
- No inference performance or grounding conclusions follow from these checks.

## Durable evidence copies

Selected evidence is archived under
[concurrency-hardening-20261023](evidence/concurrency-hardening-20261023/):

- [Preparation bundle](evidence/concurrency-hardening-20261023/preparation/)
- [Source controls](evidence/concurrency-hardening-20261023/source-controls/)
- [Filter source v2](evidence/concurrency-hardening-20261023/filter-source-v2/)
- [Filter build v2](evidence/concurrency-hardening-20261023/filter-build-v2/)
- [Instrumented runner](evidence/concurrency-hardening-20261023/instrumented-runner/)
- [Six-case results](evidence/concurrency-hardening-20261023/six-case-results/)

On 2026-10-23, the operator supplied successful checksum-verification
output for all six bundle-level manifests and the nested filter manifest,
covering 32 distinct archived payload files. Together with the six
bundle-level manifests, the archive contains 38 regular files. The copied
runner and results manifest digests match the values recorded above.

A separate archive inspection reported no symlinks or other non-regular
filesystem objects. These are operator-reported local checks, not
independent authentication.

Checksum-verification output was supplied during review but has not yet
been retained as a repository transcript. Original provenance, status
records, and historical paths remain unchanged. Archived scripts retain
their original path assumptions and are preserved as evidence, not
authenticated relocated execution entry points.

Publication-content review has identified the runner status/launcher
discrepancy and the unresolved runner-to-results linkage described above.
Final documentation reconciliation and publication remain pending.
Checksum agreement does not establish safety or independent authenticity.


### Publication scope and excluded local material

Publication candidates are `README.md`, this continuation record, and the
38-file durable evidence archive, subject to final diff and staging review.

The following local material is excluded from this publication:
`.offline-patch-backups/`; root file `0`; root backup and before-change
files; `docs/concurrency-environment-evidence-20261020.json`; `results/`;
and `validation-repair-*` directories.

Exclusion is a staging decision, not deletion or a determination that the
material lacks diagnostic value. These files remain local; their contents
have not been fully adjudicated in this closeout.

## Remaining closeout work

1. Complete publication-content review of the durable evidence copies;
   retain the verification record and account for any files excluded
   from publication without modifying historical manifests.
2. Review earlier failed/diagnostic bundles and untracked October 20 artifacts;
   account for retained, excluded, or superseded material explicitly.
3. Resolve the available execution-transcript and runner-linkage evidence.
4. Satisfy or explicitly adjudicate the baseline-authentication gate.
5. Prepare and authenticate a separately reviewed regression entry point,
   including review of `tempfile.NamedTemporaryFile()` descriptor-based I/O
   against the bootstrap-enforced syscall policy before execution.
6. Obtain separate authorization before executing the scoped regressions.
7. Record actual regression outcomes without treating pending checks as passes.
8. Update README scope and confirm GitHub publication after reviewed delivery.

Calibration and the measured concurrency schedule remain separately gated
by the concurrency protocol. No authorization is implied by this document.
