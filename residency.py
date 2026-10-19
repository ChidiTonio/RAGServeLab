"""Control-plane operations for model-residency experiments."""

import json
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from probe import BASE_URL


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
