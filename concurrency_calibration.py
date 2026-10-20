"""Offline calibration simulation with explicitly supplied test dependencies.

No live CLI or default network transports. Callers must supply offline fakes.
Completion describes the simulation, not an authorized serving experiment.
"""

import copy

from concurrency_experiment import (
    CALIBRATION_SCHEDULE,
    run_prepared_batch,
    run_schedule,
)
from concurrency_preflight import build_offline_execution_preflight
from concurrency_provenance import verify_provenance
from concurrency_run_store import RunReports


def run_offline_calibration(
    root, directory, *, control, verify, batch_runner,
):
    """Simulate calibration and persist reports using offline test fakes.

    The required dependencies intentionally have no production defaults.
    Provenance and persistence failures propagate without finalization.
    """
    for name, function in (
        ("control", control),
        ("verify", verify),
        ("batch_runner", batch_runner),
    ):
        if not callable(function):
            raise TypeError(f"{name} must be an explicit offline callable.")

    preflight = build_offline_execution_preflight(root, "calibration")
    plan = preflight["plan"]
    baseline = preflight["execution_provenance"]

    if (
        plan["mode"] != "calibration"
        or plan["live_enabled"] is not False
        or plan["schedule"] != [
            list(levels) for levels in CALIBRATION_SCHEDULE
        ]
        or plan["batch_count"] != 3
        or plan["request_count"] != 7
    ):
        raise ValueError("Unexpected offline calibration plan.")

    verify_provenance(root, baseline)
    reports = RunReports(directory, {
        "record_type": "offline_calibration_simulation",
        "live_enabled": False,
        "execution_authorized": False,
        "execution_provenance": copy.deepcopy(baseline),
        "offline_preflight": copy.deepcopy(preflight),
    })

    def prepared(payload, digest, concurrency, *, checkpoint):
        verify_provenance(root, baseline)
        return run_prepared_batch(
            copy.deepcopy(payload),
            digest,
            concurrency,
            checkpoint=checkpoint,
            control=control,
            verify=verify,
            batch_runner=batch_runner,
        )

    summary = run_schedule(
        copy.deepcopy(plan["payload"]),
        plan["model_digest"],
        checkpoint=reports.checkpoint,
        schedule=CALIBRATION_SCHEDULE,
        prepared_runner=prepared,
    )

    verify_provenance(root, baseline)
    summary = copy.deepcopy(summary)
    summary.update({
        "mode": "calibration",
        "record_type": "offline_calibration_simulation",
        "live_enabled": False,
        "execution_authorized": False,
    })
    reports.finish(summary)
    return summary
