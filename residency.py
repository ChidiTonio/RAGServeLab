"""Control-plane operations for model-residency experiments."""

import json
import math
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from probe import BASE_URL, get_json


def control_model(
    model,
    action,
    *,
    num_ctx=2048,
    opener=urlopen,
    clock=time.perf_counter,
):
    """Request model loading or unloading and retain operation telemetry.

    Elapsed time includes connection setup and response decoding. Successful
    completion acknowledges the control request; residency must be verified
    separately. Expected runtime failures are returned as error records.
    """
    if action not in ("load", "unload"):
        raise ValueError(f"Unsupported control action: {action}")

    payload = {
        "model": model,
        "prompt": "",
        "stream": False,
        "keep_alive": "5m" if action == "load" else 0,
    }
    if action == "load":
        # Match the measured workload's context allocation during preload.
        payload["options"] = {"num_ctx": num_ctx}

    request = Request(
        BASE_URL + "/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    record = {
        "action": action,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "request": payload,
        "status": "error",
    }
    started = clock()

    try:
        with opener(request, timeout=180) as response:
            event = json.load(response)

        record["response"] = event
        if not isinstance(event, dict):
            raise RuntimeError("Control response is not a JSON object.")
        if "error" in event:
            raise RuntimeError(str(event["error"]))
        if event.get("done") is not True:
            raise RuntimeError("Control response lacks a completion event.")

        record["status"] = "success"
    except (OSError, ValueError, RuntimeError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        record["client_total_s"] = clock() - started

    return record


def verify_residency(
    digest,
    expected_present,
    *,
    max_attempts=5,
    interval_s=0.25,
    query=get_json,
    clock=time.perf_counter,
    sleep=time.sleep,
):
    """Observe a target digest within a bounded number of residency queries.

    Success means the expected state appeared in one valid server snapshot.
    It does not establish continued residency or independent GPU placement.
    Query failures and malformed snapshots remain unknown, not absent.
    """
    if not isinstance(digest, str) or not digest.strip():
        raise ValueError("A non-empty model digest is required.")
    if not isinstance(expected_present, bool):
        raise ValueError("expected_present must be a boolean.")
    if type(max_attempts) is not int or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer.")
    if not math.isfinite(interval_s) or interval_s < 0:
        raise ValueError("interval_s must be finite and non-negative.")

    record = {
        "model_digest": digest,
        "expected_present": expected_present,
        "max_attempts": max_attempts,
        "interval_s": interval_s,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "error",
        "observations": [],
    }
    started = clock()

    for attempt in range(1, max_attempts + 1):
        observation = {
            "attempt": attempt,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "error",
        }
        record["observations"].append(observation)

        try:
            snapshot = query("/api/ps")
            observation["response"] = snapshot
            if not isinstance(snapshot, dict):
                raise RuntimeError("Residency response is not a JSON object.")

            models = snapshot.get("models")
            if not isinstance(models, list):
                raise RuntimeError("Residency response lacks a models list.")

            # Validate every entry before treating a missing target as absent.
            for model in models:
                if (
                    not isinstance(model, dict)
                    or not isinstance(model.get("digest"), str)
                    or not model["digest"].strip()
                ):
                    raise RuntimeError("Residency entry lacks a valid digest.")

            present = any(model["digest"] == digest for model in models)
            observation["present"] = present
            observation["status"] = "success"
            if present == expected_present:
                record["status"] = "success"
        except (OSError, ValueError, RuntimeError) as exc:
            observation["error"] = f"{type(exc).__name__}: {exc}"

        observation["elapsed_since_start_s"] = clock() - started
        if record["status"] == "success":
            break
        if attempt < max_attempts:
            sleep(interval_s)

    record["client_total_s"] = clock() - started
    if record["status"] != "success":
        record["error"] = (
            "Expected residency state was not verified within the query budget."
        )
    return record
