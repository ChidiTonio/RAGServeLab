"""Pure validation of supplied server metadata; no network access."""

import copy

from concurrency_run_store import MODEL, DIGEST


EXPECTED_SERVER_VERSION = "0.40.6"


def validate_server_metadata(version_response, tags_response):
    """Validate observations against protocol expectations.

    Inputs must be decoded JSON responses supplied by a caller.
    This function performs no requests and grants no execution authority.
    Installed model metadata does not establish residency or allocation.
    """
    if not isinstance(version_response, dict):
        raise ValueError("Server version response must be a JSON object.")
    if version_response.get("version") != EXPECTED_SERVER_VERSION:
        raise ValueError("Server version does not match the protocol.")

    if not isinstance(tags_response, dict):
        raise ValueError("Model tags response must be a JSON object.")
    models = tags_response.get("models")
    if not isinstance(models, list):
        raise ValueError("Model tags response must contain a models list.")

    for entry in models:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or not entry["name"].strip()
            or not isinstance(entry.get("digest"), str)
            or not entry["digest"].strip()
        ):
            raise ValueError("Model tags contain a malformed entry.")

    matches = [entry for entry in models if entry["name"] == MODEL]
    if len(matches) != 1:
        raise ValueError("Expected exactly one target model entry.")
    if matches[0]["digest"] != DIGEST:
        raise ValueError("Target model digest does not match the protocol.")

    return {
        "check": "server_version_and_installed_model_metadata",
        "status": "success",
        "expected": {
            "server_version": EXPECTED_SERVER_VERSION,
            "model": MODEL,
            "model_digest": DIGEST,
        },
        "server_version_response": copy.deepcopy(version_response),
        "model_tags_response": copy.deepcopy(tags_response),
        "selected_model_metadata": copy.deepcopy(matches[0]),
        "live_enabled": False,
    }


def build_offline_execution_preflight(root, mode="measured"):
    """Bind a local plan to a clean committed revision; no authorization.

    Capture provenance before reading the plan, compare input hashes,
    and verify provenance again afterward. Failures propagate to the
    caller, which must handle persistence separately from operations.
    Environment evidence and live metadata are not collected here.
    """
    from concurrency_provenance import capture_provenance, verify_provenance
    from concurrency_run_store import FIXTURE, MANIFEST, offline_plan

    provenance = capture_provenance(root)
    plan = offline_plan(root, mode)

    expected_hashes = {
        "docs/concurrency-protocol-v1.md": plan["protocol_sha256"],
        str(FIXTURE): plan["prompt_sha256"],
        str(MANIFEST): plan["manifest_sha256"],
    }
    for name, digest in expected_hashes.items():
        if provenance["file_sha256"].get(name) != digest:
            raise ValueError(
                f"Plan input does not match execution provenance: {name}"
            )

    verify_provenance(root, provenance)
    return {
        "check": "offline_plan_and_execution_provenance",
        "status": "success",
        "live_enabled": False,
        "plan": copy.deepcopy(plan),
        "execution_provenance": copy.deepcopy(provenance),
        "pending_checks": [
            "environment_evidence",
            "authorized_live_connectivity_and_metadata",
            "calibration_authorization",
            "measured_execution_authorization",
        ],
    }


def validate_environment_evidence(evidence):
    """Validate supplied evidence structure, not environmental truth.

    No network access, authorization, or independent verification.
    This schema supports unavailable startup evidence only; a future
    captured-log path must validate its own evidence explicitly.
    """
    import json
    from datetime import datetime

    if not isinstance(evidence, dict):
        raise ValueError("Environment evidence must be a JSON object.")
    if (
        evidence.get("schema_version") != "0.1"
        or evidence.get("record_type") != "supplied_environment_evidence"
        or evidence.get("live_enabled") is not False
        or evidence.get("execution_authorized") is not False
    ):
        raise ValueError("Invalid evidence schema or authorization flags.")

    def text(value, label):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing or invalid {label}.")
        return value

    stamp = text(evidence.get("recorded_at_utc"), "recording timestamp")
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise ValueError("Invalid recording timestamp.") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Recording timestamp must have a UTC offset.")

    text(evidence.get("observation_date"), "observation date")
    text(evidence.get("observation_time_precision"), "time precision")
    observations = evidence.get("observations")
    if not isinstance(observations, dict):
        raise ValueError("Missing observations object.")

    def observation(name, source=None):
        item = observations.get(name)
        if not isinstance(item, dict):
            raise ValueError(f"Missing observation: {name}.")
        if source is not None and item.get("source") != source:
            raise ValueError(f"Invalid evidence source: {name}.")
        return item

    scheme = observation(
        "active_windows_power_scheme",
        "operator_supplied_powershell_output",
    )
    if scheme.get("command") != "powercfg /getactivescheme":
        raise ValueError("Unexpected power-scheme command.")
    for key in ("raw_output", "name", "guid"):
        text(scheme.get(key), f"power scheme {key}")

    allowed = {
        "ac_power": {"connected", "disconnected", "unknown"},
        "other_ollama_clients": {"currently_idle", "active", "unknown"},
        "planned_interruptions": {
            "none_planned_unless_needed", "planned", "unknown",
        },
        "serving_changes_since_project_start": {
            "none_reported", "changes_reported", "unknown",
        },
    }
    for name, values in allowed.items():
        item = observation(name, "operator_statement")
        if item.get("value") not in values:
            raise ValueError(f"Invalid operator value: {name}.")
        text(item.get("raw_statement"), f"{name} raw statement")

    startup = observation("startup_log", "operator_statement")
    if (
        startup.get("availability") != "unavailable"
        or startup.get("verified") is not False
    ):
        raise ValueError("Unsupported startup-log verification claim.")

    model = observation("model_recollection", "operator_recollection")
    text(model.get("raw_statement"), "model recollection")
    if (
        model.get("exact_model_tag_verified") is not False
        or model.get("model_digest_verified") is not False
    ):
        raise ValueError("Recollection cannot verify model identity.")

    power_mode = observation("separate_windows_power_mode")
    if power_mode.get("availability") != "unknown":
        raise ValueError("Unsupported separate power-mode evidence.")

    limitations = evidence.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValueError("Evidence limitations must be retained.")
    for limitation in limitations:
        text(limitation, "limitation")

    # Reject non-JSON values and non-finite numbers before persistence.
    try:
        json.dumps(evidence, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Evidence must contain finite JSON data.") from exc

    return {
        "check": "supplied_environment_evidence_structure",
        "status": "recorded",
        "live_enabled": False,
        "execution_authorized": False,
        "evidence": copy.deepcopy(evidence),
        "unverified": [
            "effective_windows_server_parallelism",
            "effective_windows_server_queue_limit",
            "effective_windows_server_context_default",
            "device_placement",
            "server_version_and_exact_model_identity",
            "separate_windows_power_mode",
        ],
        "notice": (
            "Structural validation only; no independent verification "
            "or execution authorization."
        ),
    }


def _reject_nonfinite_json_constant(value):
    """Reject non-standard numeric constants before retaining evidence."""
    raise ValueError(f"Evidence contains a non-finite JSON constant: {value}")


def persist_offline_preflight(root, evidence_path, directory, mode="measured"):
    """Save local preflight observations in an exclusive directory.

    No requests or execution authorization. Validation failures become
    explicit failed reports. Persistence errors propagate to the caller;
    a surviving pending report must not be treated as completed.
    """
    import hashlib
    import json
    import platform
    import sys
    from pathlib import Path

    from concurrency_run_store import utc_now
    from report_store import ReportStore

    directory = Path(directory)
    report = {
        "schema_version": "0.1",
        "record_type": "offline_preflight",
        "status": "pending",
        "created_at_utc": utc_now(),
        "live_enabled": False,
        "execution_authorized": False,
        "requested_mode": mode,
        "evidence_path": str(evidence_path),
        "client_runtime": {
            "source": "local_python_runtime",
            "observed_at_utc": utc_now(),
            "python_version": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "interpretation": (
                "Client runtime only; does not establish Windows "
                "serving-process configuration."
            ),
        },
        "environment_evidence": None,
        "execution_preflight": None,
        "error": None,
    }
    directory.mkdir(parents=True, exist_ok=False)
    store = ReportStore(directory / "preflight.json", report)

    stage = "environment_evidence"
    try:
        raw = Path(evidence_path).read_bytes()
        report["environment_evidence_sha256"] = (
            hashlib.sha256(raw).hexdigest()
        )
        supplied = json.loads(
            raw, parse_constant=_reject_nonfinite_json_constant
        )
        # Preserve decoded evidence even when validation rejects it.
        report["supplied_environment_evidence"] = copy.deepcopy(supplied)
        report["environment_evidence"] = (
            validate_environment_evidence(supplied)
        )
        stage = "planning_and_execution_provenance"
        report["execution_preflight"] = (
            build_offline_execution_preflight(root, mode)
        )
    except (OSError, ValueError, RuntimeError) as exc:
        report["status"] = "failed"
        report["error"] = {
            "stage": stage,
            "type": type(exc).__name__,
            "message": str(exc),
        }
    else:
        report["status"] = "offline_checks_complete"

    report["finished_at_utc"] = utc_now()
    report["notice"] = (
        "Offline evidence only. Live connectivity, server metadata, "
        "residency, and execution authorization are not established."
    )
    # Deliberately outside the validation exception handler:
    # storage errors must propagate, not be reported as successful writes.
    store.checkpoint(report)
    return copy.deepcopy(report)
