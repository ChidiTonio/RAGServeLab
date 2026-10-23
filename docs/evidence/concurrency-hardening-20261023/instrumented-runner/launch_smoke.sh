#!/bin/bash
set -euo pipefail
umask 077
export LC_ALL=C

fail() {
    printf 'STOP: %s\n' "$*" >&2
    exit 1
}

[[ $# == 2 && "$1" == "--authorized-full-smoke" ]] ||
    fail "Separate full-smoke authorization and runner manifest pin required"

runner="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
runner_pin="$2"
[[ "$runner_pin" =~ ^[0-9a-f]{64}$ ]] ||
    fail "invalid runner manifest pin"

check_manifest() {
    local directory="$1" name="$2" expected="$3" digest
    [[ -d "$directory" && ! -L "$directory" ]] ||
        fail "missing or symlinked artifact directory"
    [[ -f "$directory/$name" && ! -L "$directory/$name" ]] ||
        fail "missing or symlinked manifest"
    digest="$(sha256sum -- "$directory/$name")"
    [[ "${digest%% *}" == "$expected" ]] ||
        fail "manifest pin mismatch"
    (
        cd -- "$directory"
        sha256sum --check --strict "$name"
    )
}

expected_paths="$(
    printf '%s\n' \
        RUNNER.sha256 STATUS.txt bootstrap.py launch_smoke.sh \
        locked.bpf smoke.py startup.bpf | sort
)"
actual_paths="$(find "$runner" -mindepth 1 -printf '%P\n' | sort)"
[[ "$actual_paths" == "$expected_paths" ]] ||
    fail "unexpected runner file set"
while IFS= read -r name; do
    [[ -f "$runner/$name" && ! -L "$runner/$name" ]] ||
        fail "unexpected runner filesystem object"
done <<< "$expected_paths"
check_manifest "$runner" RUNNER.sha256 "$runner_pin"

snapshot="/tmp/rag-offline-preparation.vNDPly5I"
snapshot_pin="e9c34f5b36b753d53cb3c5d483bf934dfe7e5d1629dd5870fe25b3887bc01fdf"
check_manifest "$snapshot" MANIFEST.sha256 "$snapshot_pin"

expected_snapshot="$(
    printf '%s\n' \
        MANIFEST.sha256 controls controls/execution-gate.sh \
        controls/provenance.txt controls/requirements.txt snapshot \
        snapshot/concurrency_experiment.py snapshot/concurrency_preflight.py \
        snapshot/concurrency_run_store.py snapshot/probe.py \
        snapshot/report_store.py \
        snapshot/test_concurrency_offline_input_validation.py | sort
)"
actual_snapshot="$(find "$snapshot" -mindepth 1 -printf '%P\n' | sort)"
[[ "$actual_snapshot" == "$expected_snapshot" ]] ||
    fail "unexpected snapshot path set"
[[ -z "$(find "$snapshot" -mindepth 1 ! -type f ! -type d -print)" ]] ||
    fail "unexpected snapshot filesystem object"

[[ "$(uname -m)" == x86_64 ]] || fail "unsupported architecture"
[[ "$(readlink -f /usr/bin/python3)" == /usr/bin/python3.14 ]] ||
    fail "interpreter resolution changed"
[[ -f /usr/bin/python3.14 && ! -L /usr/bin/python3.14 &&
   -x /usr/bin/python3.14 ]] || fail "unexpected interpreter"
[[ -d /usr/lib/python3.14 &&
   -d /usr/lib/x86_64-linux-gnu ]] ||
    fail "proposed runtime mount layout unavailable"
[[ -e /usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2 ]] ||
    fail "proposed dynamic-loader path unavailable"

for utility in /usr/bin/bwrap /usr/bin/timeout /usr/bin/prlimit; do
    [[ -x "$utility" ]] || fail "required utility missing: $utility"
done

results="$(mktemp -d /tmp/rag-sandbox-smoke-results.XXXXXXXX)"
printf 'Smoke result directory: %s\n' "$results"

run_case() {
    local mode="$1" expected="$2" status
    local log="$results/$mode.log"

    # A new sandbox is used for every check.
    # FD 3 carries the authenticated startup filter; bwrap consumes it.
    if /usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C \
        /usr/bin/timeout --signal=TERM --kill-after=2s 20s \
        /usr/bin/prlimit --as=536870912 --fsize=1048576 --nofile=64 -- \
        /usr/bin/bwrap \
            --unshare-all \
            --die-with-parent \
            --new-session \
            --cap-drop ALL \
            --clearenv \
            --setenv PATH /usr/bin \
            --setenv LC_ALL C \
            --setenv TMPDIR /tmp/tests \
            --setenv HOME /tmp/tests \
            --dir /usr \
            --dir /usr/bin \
            --dir /usr/lib \
            --ro-bind /usr/bin/python3.14 /usr/bin/python3.14 \
            --ro-bind /usr/lib/python3.14 /usr/lib/python3.14 \
            --ro-bind /usr/lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu \
            --symlink usr/lib /lib \
            --symlink usr/lib/x86_64-linux-gnu /lib64 \
            --ro-bind "$runner" /controls \
            --ro-bind "$snapshot/snapshot" /snapshot \
            --proc /proc \
            --dev /dev \
            --tmpfs /tmp \
            --dir /tmp/tests \
            --chdir /tmp/tests \
            --seccomp 3 \
            /usr/bin/python3.14 -I -S -B /controls/smoke.py "$mode" \
            3<"$runner/startup.bpf" >"$log" 2>&1
    then
        status=0
    else
        status=$?
    fi

    printf '%s: exit=%s; expected=%s\n' "$mode" "$status" "$expected"
    cat -- "$log"
    [[ "$status" == "$expected" ]] ||
        fail "smoke check failed: $mode; do not weaken controls"

    if [[ "$mode" == allowed ]]; then
        grep -qx 'SMOKE_ALLOWED_PASS' "$log" ||
            fail "allowed smoke success marker missing"
    else
        grep -qx "EXPECTED_SECCOMP_TERMINATION $mode" "$log" ||
            fail "forbidden syscall was not reached"
    fi
}

# Shell status 159 is 128 + Linux SIGSYS (31).
run_case allowed 0
run_case startup-socket 159
run_case locked-socket 159
run_case locked-fork 159
run_case locked-exec 159
run_case locked-x32 159

(
    cd -- "$results"
    sha256sum -- *.log > RESULTS.sha256
    sha256sum --check --strict RESULTS.sha256
)
printf '\nFULL_SMOKE_PASS — SIX CONTROL CASES — PROJECT TESTS NOT RUN\n'
sha256sum -- "$results/RESULTS.sha256"
