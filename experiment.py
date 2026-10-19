"""A-B-C trial orchestration, independent of CLI and report storage."""

from datetime import datetime, timezone

from probe import generate, runtime_metrics
from residency import control_model, verify_residency


def run_trial(
    payload,
    digest,
    *,
    checkpoint,
    trial_number=1,
    control=control_model,
    verify=verify_residency,
    generation=generate,
):
    """Run one sequential trial; checkpoint receives the current trial record.

    The callback must persist the record synchronously. Its failures propagate.
    Injected operations must follow the production operation return contracts.
    """
    model = payload["model"]
    num_ctx = payload["options"]["num_ctx"]
    trial = {
        "trial_number": trial_number,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "conditions": [
            {
                "condition": label,
                "status": "pending",
                "preparation": [],
            }
            for label in ("A", "B", "C")
        ],
    }
    checkpoint(trial)

    def prepare(condition, kind, operation, *args, **kwargs):
        result = operation(*args, **kwargs)
        condition["preparation"].append({
            "kind": kind,
            "record": result,
        })
        checkpoint(trial)
        if result["status"] != "success":
            condition["status"] = "skipped"
            condition["reason"] = f"Required {kind} operation failed."
            checkpoint(trial)
            return False
        return True

    def reset(condition):
        return (
            prepare(condition, "unload", control, model, "unload")
            and prepare(condition, "verify_absent", verify, digest, False)
        )

    def measure(condition):
        condition["status"] = "running"
        condition["generation_started_at_utc"] = (
            datetime.now(timezone.utc).isoformat()
        )
        checkpoint(trial)
        # Report persistence is deliberately outside this exception boundary.
        try:
            result = generation(payload)
            metrics = runtime_metrics(result["final_event"])
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            condition["status"] = "error"
            condition["error"] = f"{type(exc).__name__}: {exc}"
        else:
            condition["generation"] = result
            condition["runtime_metrics"] = metrics
            condition["status"] = "success"
        checkpoint(trial)

    a, b, c = trial["conditions"]

    if reset(a):
        measure(a)

    # Always reset again: A may have populated the prompt cache.
    if (
        reset(b)
        and prepare(b, "load", control, model, "load", num_ctx=num_ctx)
        and prepare(b, "verify_present", verify, digest, True)
    ):
        measure(b)

    if b["status"] != "success":
        c["status"] = "skipped"
        c["reason"] = "Condition B did not complete successfully."
        checkpoint(trial)
    elif prepare(c, "verify_present", verify, digest, True):
        # No intervening generation or residency-control request after B.
        measure(c)

    trial["status"] = (
        "success"
        if all(item["status"] == "success" for item in trial["conditions"])
        else "error"
    )
    trial["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    checkpoint(trial)
    return trial
