"""Residency preparation and finite-batch scheduling; no live CLI."""

import copy

from concurrency import run_batch
from concurrency_batch_validation import validate_successful_batch
from residency import control_model, verify_residency

from concurrency_validation import validate_residency_record

SCHEDULE = (
    (1, 2, 4), (2, 4, 1), (4, 1, 2),
    (1, 4, 2), (4, 2, 1), (2, 1, 4),
)
CALIBRATION_SCHEDULE = ((1, 2, 4),)


def validate_presence(record, digest, num_ctx):
    """Require strictly consistent presence and context evidence."""
    validate_residency_record(record, digest, True, num_ctx)


def run_prepared_batch(
    payload, digest, concurrency, *, checkpoint,
    control=control_model, verify=verify_residency, batch_runner=run_batch,
):
    """Reset, preload, measure, and verify; persistence failures propagate."""
    report = {
        "experiment": "resident_prompt_unwarmed_batch",
        "concurrency": concurrency,
        "status": "pending",
        "preparation": [],
        "batch": None,
    }

    def save():
        checkpoint(copy.deepcopy(report))

    def operation(kind, function, *args, expected_present=None, **kwargs):
        # Persistence deliberately sits outside the operation error boundary.
        try:
            record = function(*args, **kwargs)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            record = {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
        entry = {"kind": kind, "record": record}
        report["preparation"].append(entry)
        valid = isinstance(record, dict) and record.get("status") == "success"
        if valid and expected_present is not None:
            try:
                validate_residency_record(
                    record, digest, expected_present,
                    payload["options"]["num_ctx"],
                )
            except (ValueError, RuntimeError, KeyError, TypeError) as exc:
                valid = False
                entry["validation_error"] = f"{type(exc).__name__}: {exc}"
        if not valid:
            report["status"] = "error"
            report["error"] = f"Required {kind} operation failed."
        save()
        return valid

    save()
    report["status"] = "preparing"
    model = payload["model"]
    if not operation("unload", control, model, "unload"):
        return report
    if not operation(
        "verify_absent", verify, digest, False, expected_present=False,
    ):
        return report
    if not operation(
        "load", control, model, "load",
        num_ctx=payload["options"]["num_ctx"],
    ):
        return report
    if not operation(
        "verify_present", verify, digest, True, expected_present=True,
    ):
        return report

    def batch_checkpoint(batch):
        report["batch"] = copy.deepcopy(batch)
        report["status"] = (
            "pending" if batch["status"] == "pending" else "checking"
        )
        save()

    batch = batch_runner(
        payload, concurrency, checkpoint=batch_checkpoint
    )
    report["batch"] = copy.deepcopy(batch)

    # Even failed measured batches retain a post-batch observation.
    # No reset or replacement is attempted here.
    if not operation(
        "verify_present_after", verify, digest, True, expected_present=True,
    ):
        if batch.get("status") == "interrupted":
            report["status"] = "interrupted"
            save()
        return report

    successful = False
    if batch.get("status") == "success":
        try:
            validate_successful_batch(batch, payload, concurrency)
        except ValueError as exc:
            report["batch_validation_error"] = f"ValueError: {exc}"
        else:
            successful = True
    report["status"] = (
        "interrupted" if batch.get("status") == "interrupted" else
        ("success" if successful else "error")
    )
    if not successful:
        report["error"] = "Measured batch failed or returned invalid outcomes."
    save()
    return report


def run_schedule(
    payload, digest, *, checkpoint, schedule=SCHEDULE,
    prepared_runner=run_prepared_batch,
):
    """Execute listed visits; stop at the first unsuccessful batch.

    checkpoint receives a batch report with its block and position attached.
    A CLI may use these identities to own a separate ReportStore per batch.
    This controller does not create output files or retry operations.
    """
    schedule = tuple(tuple(levels) for levels in schedule)
    if not schedule or any(
        not levels or any(type(c) is not int or c not in (1, 2, 4)
                          for c in levels)
        for levels in schedule
    ):
        raise ValueError("Invalid concurrency schedule.")
    summary = {"status": "running", "batches": []}
    for block, levels in enumerate(schedule, 1):
        for position, concurrency in enumerate(levels, 1):
            def save(report):
                snapshot = copy.deepcopy(report)
                snapshot.update({"block": block, "position": position})
                checkpoint(snapshot)

            report = prepared_runner(
                payload, digest, concurrency, checkpoint=save
            )
            save(report)
            summary["batches"].append({
                "block": block, "position": position,
                "concurrency": concurrency, "status": report["status"],
            })
            if report["status"] != "success":
                summary["status"] = "stopped"
                return summary
    summary["status"] = "complete"
    return summary
