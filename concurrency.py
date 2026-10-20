"""Finite concurrent batches; standard library only.

Workers own their HTTP state. Only the coordinator invokes checkpoints.
This module performs no residency operations and has no live CLI.
"""

import copy
import json
import threading
import time
from statistics import median
from urllib.request import Request, urlopen

from probe import BASE_URL, runtime_metrics


def serialize_request(payload):
    """Serialize before worker release; never mutate the caller's payload."""
    return Request(
        BASE_URL + "/api/generate",
        data=json.dumps(payload, allow_nan=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def measure_request(request, request_id, *, opener=urlopen,
                    clock=time.perf_counter):
    """Retain partial output and events on expected or unexpected exceptions."""
    result = {
        "request_id": request_id,
        "status": "error",
        "answer": "",
        "events": [],
        "final_event": None,
        "client_first_text_s": None,
        "client_total_s": None,
        "transport_timeout_s": 180,
    }
    fragments = []
    started = clock()
    result["request_started_monotonic_s"] = started
    try:
        with opener(request, timeout=180) as response:
            for raw in response:
                if not raw.strip():
                    continue
                event = json.loads(raw)
                result["events"].append(event)
                if not isinstance(event, dict):
                    raise RuntimeError("Stream event is not a JSON object.")
                if "error" in event:
                    raise RuntimeError(str(event["error"]))
                text = event.get("response", "")
                if not isinstance(text, str):
                    raise RuntimeError("Response fragment is not a string.")
                if text:
                    if result["client_first_text_s"] is None:
                        result["first_text_monotonic_s"] = clock()
                        result["client_first_text_s"] = (
                            result["first_text_monotonic_s"] - started
                        )
                    fragments.append(text)
                if event.get("done") is True:
                    result["final_event"] = event
                    break

            completed = clock()
            if result["final_event"] is None:
                raise RuntimeError("Stream ended without a completion event.")
            if result["client_first_text_s"] is None:
                raise RuntimeError("Completed request produced no generated text.")
            result["completion_monotonic_s"] = completed
            result["client_total_s"] = completed - started
            result["runtime_metrics"] = runtime_metrics(result["final_event"])
            result["status"] = "success"
    except BaseException as exc:
        result["status"] = (
            "error" if isinstance(exc, Exception) else "interrupted"
        )
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["answer"] = "".join(fragments)
        result["terminal_monotonic_s"] = clock()
        result["client_terminal_s"] = (
            result["terminal_monotonic_s"] - started
        )
    return result


def summarize_batch(batch):
    """Derive metrics only after every released worker has terminated."""
    release = batch["release_monotonic_s"]
    requests = batch["requests"]
    successes = [r for r in requests if r["status"] == "success"]
    starts = [r["request_started_monotonic_s"] for r in requests]
    end = max(r["terminal_monotonic_s"] for r in requests)
    duration = end - release
    for result in requests:
        result["release_to_start_s"] = (
            result["request_started_monotonic_s"] - release
        )
        result["release_to_terminal_s"] = (
            result["terminal_monotonic_s"] - release
        )
        for source, target in (
            ("first_text_monotonic_s", "release_to_first_text_s"),
            ("completion_monotonic_s", "release_to_completion_s"),
        ):
            value = result.get(source)
            result[target] = None if value is None else value - release

    complete = len(successes) == batch["concurrency"]
    counts = [r["runtime_metrics"]["eval_count"] for r in successes]
    valid_counts = bool(successes) and all(
        type(count) is int and count >= 0 for count in counts
    )
    interrupted = any(
        r["status"] == "interrupted" for r in requests
    )
    batch["status"] = (
        "interrupted" if interrupted else
        ("success" if complete else "error")
    )
    batch["metrics"] = {
        "batch_duration_s": duration,
        "successful_requests": len(successes),
        "completion_requests_per_s": (
            len(successes) / duration if duration > 0 else None
        ),
        "aggregate_output_tokens_per_s": (
            sum(counts) / duration
            if valid_counts and duration > 0 else None
        ),
        "dispatch_skew_s": max(starts) - min(starts),
        # Primary latency comparisons require a wholly successful batch.
        "median_first_text_s": (
            median(r["client_first_text_s"] for r in successes)
            if complete else None
        ),
        "maximum_completion_s": (
            max(r["client_total_s"] for r in successes)
            if complete else None
        ),
        "median_completion_s": (
            median(r["client_total_s"] for r in successes)
            if complete else None
        ),
        "maximum_first_text_s": (
            max(r["client_first_text_s"] for r in successes)
            if complete else None
        ),
        "earliest_start_to_latest_completion_s": (
            max(r["completion_monotonic_s"] for r in successes) - min(starts)
            if complete else None
        ),
    }


def run_batch(payload, concurrency, *, checkpoint,
              opener=urlopen, clock=time.perf_counter, readiness_timeout_s=5):
    """Run one finite batch, with no retries and no writes during measurement.

    checkpoint receives independent snapshots before launch and after join.
    Serialization and the initial checkpoint precede thread creation.
    A broken readiness barrier releases no HTTP requests.
    """
    if type(concurrency) is not int or concurrency not in (1, 2, 4):
        raise ValueError("Concurrency must be 1, 2, or 4.")
    if not 0 < readiness_timeout_s < float("inf"):
        raise ValueError("Readiness timeout must be finite and positive.")

    prepared = [
        serialize_request(copy.deepcopy(payload))
        for _ in range(concurrency)
    ]
    batch = {
        "schema_version": "0.1",
        "experiment": "finite_concurrent_batch",
        "concurrency": concurrency,
        "status": "pending",
        "request": copy.deepcopy(payload),
        "requests": [
            {"request_id": number, "status": "pending"}
            for number in range(1, concurrency + 1)
        ],
    }
    checkpoint(copy.deepcopy(batch))

    ready = threading.Barrier(concurrency + 1, timeout=readiness_timeout_s)
    release_gate = threading.Event()
    abort = threading.Event()
    results = [None] * concurrency
    worker_done = [threading.Event() for _ in range(concurrency)]

    def worker(index):
        try:
            ready.wait()
            release_gate.wait()
            if abort.is_set():
                return
            results[index] = measure_request(
                prepared[index], index + 1, opener=opener, clock=clock
            )
        except BaseException as exc:
            # Capture worker-level failures without hanging the coordinator.
            ready.abort()
            results[index] = {
                "request_id": index + 1,
                "status": (
                    "error" if isinstance(exc, Exception) else "interrupted"
                ),
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            # This signal, not Thread.is_alive(), establishes that the
            # worker's result-handling path has finished.
            worker_done[index].set()

    threads = [
        threading.Thread(target=worker, args=(index,),
                         name=f"ragserve-request-{index + 1}")
        for index in range(concurrency)
    ]
    attempted_threads = []
    coordinator_errors = []
    coordinator_interrupted = False
    released = False

    def record_coordinator_error(exc, phase):
        nonlocal coordinator_interrupted
        coordinator_interrupted |= not isinstance(exc, Exception)
        coordinator_errors.append({
            "phase": phase,
            "status": (
                "error" if isinstance(exc, Exception) else "interrupted"
            ),
            "error": f"{type(exc).__name__}: {exc}",
        })

    phase = "thread_start"
    try:
        for index, thread in enumerate(threads):
            # Track before start: start() can raise after launching a worker.
            attempted_threads.append((index, thread))
            thread.start()
        phase = "readiness"
        ready.wait()
        phase = "release"
        batch["release_monotonic_s"] = clock()
        release_gate.set()
        released = True
        phase = "join"
        for _, thread in attempted_threads:
            thread.join()
    except threading.BrokenBarrierError as exc:
        abort.set()
        record_coordinator_error(exc, phase)
        batch["error"] = "Worker readiness failed; no batch released."
    except BaseException as exc:
        abort.set()
        record_coordinator_error(exc, phase)
    finally:
        # Observe the gate before cleanup opens it. An interruption can
        # occur after set() opens the gate but before released is assigned.
        # Cleanup-only gate opening must not count as coordinated release.
        if phase == "release" and release_gate.is_set():
            released = True

        if abort.is_set():
            while True:
                try:
                    ready.abort()
                    break
                except BaseException as exc:
                    record_coordinator_error(exc, "cleanup_abort")
                    if isinstance(exc, Exception):
                        # Retain an ordinary abort failure without endlessly
                        # retrying a potentially invalid operation. Workers
                        # still have the configured readiness timeout.
                        break
        # Cleanup must open the gate before collecting workers.
        # Retain interruptions whether set() raised before or after
        # opening it; an already-open gate needs no further retry.
        while True:
            try:
                release_gate.set()
                break
            except BaseException as exc:
                record_coordinator_error(exc, "cleanup_release")
                if release_gate.is_set():
                    break

        for index, thread in attempted_threads:
            # A failed start may leave a genuinely unstarted Thread.
            # On CPython 3.14, the native handle can expose launch evidence
            # before bootstrap publishes Thread.ident. Its unstarted
            # identity is zero. This private API is version-specific.
            native_handle = getattr(thread, "_os_thread_handle", None)
            native_ident = getattr(native_handle, "ident", 0)
            if thread.ident is None and not native_ident:
                continue

            # An interrupted Thread.join() can make thread liveness
            # reporting unreliable on some Python versions. Wait for the
            # worker-owned completion signal before persisting results.
            while True:
                try:
                    worker_done[index].wait()
                    break
                except BaseException as exc:
                    record_coordinator_error(exc, "cleanup_wait")

            while True:
                try:
                    thread.join()
                    break
                except BaseException as exc:
                    record_coordinator_error(exc, "cleanup_join")
                    if isinstance(exc, Exception):
                        # The worker completion signal is already set.
                        # Retain the join failure without retrying a
                        # permanently invalid join operation.
                        break

    if not released:
        batch.pop("release_monotonic_s", None)
        batch["requests"] = [
            {
                "request_id": index + 1,
                "status": "not_released",
                "error": "Batch stopped before coordinated release.",
            }
            for index in range(concurrency)
        ]
        batch["status"] = "error"
    else:
        batch["requests"] = [
            result if isinstance(result, dict) else {
                "request_id": index + 1,
                "status": "error",
                "error": "Worker terminated without a result record.",
            }
            for index, result in enumerate(results)
        ]
        if all(
            "terminal_monotonic_s" in result
            for result in batch["requests"]
        ):
            try:
                summarize_batch(batch)
            except BaseException as exc:
                record_coordinator_error(exc, "summarize")
                batch["status"] = "error"
        else:
            batch["status"] = (
                "interrupted" if any(
                    result["status"] == "interrupted"
                    for result in batch["requests"]
                ) else "error"
            )
            batch["error"] = "Worker terminated without complete timing record."

    if coordinator_errors:
        batch["coordinator_errors"] = coordinator_errors
        batch.setdefault("error", coordinator_errors[0]["error"])
        if coordinator_interrupted:
            batch["status"] = "interrupted"
        elif batch["status"] != "interrupted":
            batch["status"] = "error"

    # Persistence failures deliberately propagate. Do not retry writes or
    # report success when the final snapshot could not be saved.
    checkpoint(copy.deepcopy(batch))
    return batch
