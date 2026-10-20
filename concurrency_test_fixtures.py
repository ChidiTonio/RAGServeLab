"""Deterministic simulated success evidence for offline tests only."""

import copy
import io

from concurrency import measure_request, serialize_request, summarize_batch


def successful_batch(payload, concurrency):
    batch = {
        "schema_version": "0.1",
        "experiment": "finite_concurrent_batch",
        "status": "pending",
        "concurrency": concurrency,
        "request": copy.deepcopy(payload),
        "release_monotonic_s": 10.0,
        "requests": [],
    }
    for request_id in range(1, concurrency + 1):
        start = 11.0 + request_id / 10
        ticks = iter([start, start + 0.25, start + 1, start + 1.1])
        result = measure_request(
            serialize_request(payload), request_id,
            opener=lambda request, timeout: io.BytesIO(
                b'{"response":"Answer","done":true,"eval_count":2}\n'
            ),
            clock=lambda: next(ticks),
        )
        batch["requests"].append(result)
    summarize_batch(batch)
    return batch
