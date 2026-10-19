"""Checkpointed sequential A-B-C benchmarks using the standard library."""

import argparse
import hashlib
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from experiment import run_trial
from probe import BASE_URL, PROMPT, build_payload, get_json
from report_store import ReportStore


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def positive_integer(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer.")
    return number


def select_model(tags, name):
    """Validate the tags response and identify the exact requested model."""
    if not isinstance(tags, dict):
        raise RuntimeError("Model metadata response is not a JSON object.")
    models = tags.get("models")
    if not isinstance(models, list):
        raise RuntimeError("Model metadata response lacks a models list.")

    for model in models:
        if (
            not isinstance(model, dict)
            or not isinstance(model.get("name"), str)
            or not model["name"].strip()
        ):
            raise RuntimeError("Model metadata entry lacks a valid name.")

    matches = [model for model in models if model["name"] == name]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one installed model named {name!r}; "
            f"found {len(matches)}."
        )

    selected = matches[0]
    digest = selected.get("digest")
    if not isinstance(digest, str) or not digest.strip():
        raise RuntimeError("Selected model lacks a non-empty digest.")
    return selected


def trial_succeeded(trial):
    """Require all three named conditions, not just a top-level status."""
    if not isinstance(trial, dict) or trial.get("status") != "success":
        return False
    conditions = trial.get("conditions")
    return (
        isinstance(conditions, list)
        and len(conditions) == 3
        and all(
            isinstance(condition, dict)
            and condition.get("condition") == label
            and condition.get("status") == "success"
            for condition, label in zip(conditions, ("A", "B", "C"))
        )
    )


def run_benchmark(
    model,
    out,
    *,
    trials=5,
    prompt=PROMPT,
    num_ctx=2048,
    num_predict=128,
    query=get_json,
    runner=run_trial,
    store_factory=ReportStore,
):
    """Persist progress synchronously; storage/runner exceptions propagate."""
    if not isinstance(model, str) or not model.strip():
        raise ValueError("A non-empty model name is required.")
    if type(trials) is not int or trials < 1:
        raise ValueError("Trial count must be a positive integer.")

    payload = build_payload(
        model, prompt=prompt, num_ctx=num_ctx, num_predict=num_predict
    )
    report = {
        "schema_version": "0.2",
        "experiment": "sequential_abc",
        "started_at_utc": utc_now(),
        "python": sys.version,
        "client_platform": platform.platform(),
        "endpoint": BASE_URL,
        "request": payload,
        "prompt_sha256": hashlib.sha256(
            payload["prompt"].encode("utf-8")
        ).hexdigest(),
        "requested_trials": trials,
        "status": "running",
        "trials": [],
    }
    # Exclusive creation must succeed before even metadata queries begin.
    store = store_factory(out, report)

    # Only metadata operations belong inside this exception boundary.
    try:
        version = query("/api/version")
        if (
            not isinstance(version, dict)
            or not isinstance(version.get("version"), str)
            or not version["version"].strip()
        ):
            raise RuntimeError("Server version response lacks a valid version.")
        report["server_version"] = version
        selected = select_model(query("/api/tags"), model)
        report["model_metadata"] = selected
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        report["status"] = "error"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["completed_at_utc"] = utc_now()
        store.checkpoint(report)
        return report

    store.checkpoint(report)

    for number in range(1, trials + 1):
        # Reserve this trial's position before invoking the controller.
        index = len(report["trials"])
        report["trials"].append({
            "trial_number": number,
            "status": "pending",
        })

        def checkpoint(trial):
            if trial.get("trial_number") != number:
                raise RuntimeError("Controller returned an unexpected trial number.")
            report["trials"][index] = trial
            store.checkpoint(report)

        trial = runner(
            payload,
            selected["digest"],
            checkpoint=checkpoint,
            trial_number=number,
        )
        checkpoint(trial)

    report["status"] = (
        "success"
        if len(report["trials"]) == trials
        and all(trial_succeeded(trial) for trial in report["trials"])
        else "error"
    )
    report["completed_at_utc"] = utc_now()
    store.checkpoint(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trials", type=positive_integer, default=5)
    parser.add_argument(
        "--prompt-file", type=Path,
        help="UTF-8 prompt file; contents are preserved without trimming.",
    )
    parser.add_argument(
        "--num-ctx", type=positive_integer,
        help="Context-window size (default: 2048).",
    )
    parser.add_argument(
        "--num-predict", type=positive_integer,
        help="Generation token limit (default: 128).",
    )
    args = parser.parse_args(argv)
    if not args.model.strip():
        parser.error("--model must not be empty.")

    try:
        workload = {}
        if args.prompt_file is not None:
            with args.prompt_file.open(
                "r", encoding="utf-8", newline=""
            ) as source:
                workload["prompt"] = source.read()
        if args.num_ctx is not None:
            workload["num_ctx"] = args.num_ctx
        if args.num_predict is not None:
            workload["num_predict"] = args.num_predict
        report = run_benchmark(
            args.model, args.out, trials=args.trials, **workload
        )
    except KeyboardInterrupt:
        print(
            "Interrupted; the last successful checkpoint is retained.",
            file=sys.stderr,
        )
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        # Do not retry persistence or perform any more server operations.
        print(
            f"Benchmark stopped: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "Report may be absent or incomplete; inspect it before retrying.",
            file=sys.stderr,
        )
        return 1

    print(f"Status: {report['status']}; report: {args.out}")
    successful = sum(trial_succeeded(item) for item in report["trials"])
    print(f"Successful trials: {successful}/{report['requested_trials']}")
    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
