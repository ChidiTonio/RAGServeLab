"""Strict successful-batch evidence validation; no HTTP operations."""

import copy
import math

from concurrency import summarize_batch
from probe import runtime_metrics


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value, label):
    _require(
        type(value) in (int, float) and math.isfinite(value),
        f"{label} must be a finite number.",
    )
    return value


def _same(actual, expected, label):
    if expected is None:
        _require(actual is None, f"{label} must remain unknown.")
    elif type(expected) is int:
        _require(
            type(actual) is int and actual == expected,
            f"{label} integer mismatch.",
        )
    elif type(expected) is float:
        _number(actual, label)
        _require(
            math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9),
            f"{label} numeric mismatch.",
        )
    else:
        _require(actual == expected, f"{label} mismatch.")


def validate_successful_batch(batch, payload, concurrency):
    """Raise ValueError for missing or inconsistent success evidence.

    This validates the recorded contract, not server authenticity.
    Inputs are never mutated.
    """
    _require(
        type(concurrency) is int and concurrency in (1, 2, 4),
        "Invalid expected concurrency.",
    )
    _require(isinstance(batch, dict), "Batch must be an object.")
    _require(batch.get("status") == "success", "Batch is not successful.")
    _require(
        type(batch.get("concurrency")) is int
        and batch["concurrency"] == concurrency,
        "Batch concurrency mismatch.",
    )
    _require(batch.get("request") == payload, "Batch payload mismatch.")
    release = _number(batch.get("release_monotonic_s"), "release")
    requests = batch.get("requests")
    _require(
        isinstance(requests, list) and len(requests) == concurrency,
        "Request count mismatch.",
    )

    for index, result in enumerate(requests, 1):
        _require(isinstance(result, dict), "Request must be an object.")
        _require(
            type(result.get("request_id")) is int
            and result["request_id"] == index,
            "Request identity mismatch.",
        )
        _require(result.get("status") == "success", "Request failed.")
        _require("error" not in result, "Successful request contains an error.")

        start, first, completion, terminal = [
            _number(result.get(key), key)
            for key in (
                "request_started_monotonic_s",
                "first_text_monotonic_s",
                "completion_monotonic_s",
                "terminal_monotonic_s",
            )
        ]
        _require(
            release <= start <= first <= completion <= terminal,
            "Request timestamps are out of order.",
        )
        for field, expected in (
            ("client_first_text_s", first - start),
            ("client_total_s", completion - start),
            ("client_terminal_s", terminal - start),
            ("release_to_start_s", start - release),
            ("release_to_first_text_s", first - release),
            ("release_to_completion_s", completion - release),
            ("release_to_terminal_s", terminal - release),
        ):
            _require(field in result, f"Missing {field}.")
            _number(result[field], field)
            _same(result[field], expected, field)

        events = result.get("events")
        _require(
            isinstance(events, list) and bool(events),
            "Missing stream events.",
        )
        fragments = []
        for position, event in enumerate(events):
            _require(isinstance(event, dict), "Invalid stream event.")
            _require("error" not in event, "Stream contains a server error.")
            text = event.get("response", "")
            _require(isinstance(text, str), "Invalid response fragment.")
            fragments.append(text)
            _require(
                event.get("done") is not True
                or position == len(events) - 1,
                "Completion event precedes retained events.",
            )
        final = result.get("final_event")
        _require(
            isinstance(final, dict)
            and final.get("done") is True
            and final == events[-1],
            "Missing or inconsistent completion event.",
        )
        answer = "".join(fragments)
        _require(
            bool(answer) and result.get("answer") == answer,
            "Missing or inconsistent generated text.",
        )
        recorded_runtime = result.get("runtime_metrics")
        _require(
            isinstance(recorded_runtime, dict),
            "Missing runtime metrics.",
        )
        try:
            expected_runtime = runtime_metrics(final)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise ValueError("Invalid completion metrics.") from exc
        for field, expected in expected_runtime.items():
            _require(field in recorded_runtime, f"Missing runtime {field}.")
            if type(expected) in (int, float):
                _number(expected, f"completion {field}")
            _same(recorded_runtime[field], expected, f"runtime {field}")

    recorded_metrics = batch.get("metrics")
    _require(isinstance(recorded_metrics, dict), "Missing batch metrics.")
    recomputed = copy.deepcopy(batch)
    summarize_batch(recomputed)
    for field, expected in recomputed["metrics"].items():
        _require(field in recorded_metrics, f"Missing batch {field}.")
        _same(recorded_metrics[field], expected, f"batch {field}")
