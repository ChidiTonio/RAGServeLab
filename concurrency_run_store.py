"""Fixture validation and coordinator-owned experiment storage."""

import copy
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from concurrency_experiment import SCHEDULE, CALIBRATION_SCHEDULE
from probe import build_payload
from report_store import ReportStore


MODEL = "qwen2.5:3b"
PROTOCOL_HASH = "79233047c499f18ef7631f9a893ddacaba7c5efb7f606b781b4c76516b7e6b7c"
DIGEST = "357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b"
PROMPT_HASH = "50d4fc87d0f9c7ca2ea79ae9317477250f8ecad5fe8968e7d8f5533223a3d6b3"
FIXTURE = Path("workloads/evidence-length-v1/distractors-08.txt")
MANIFEST = FIXTURE.parent / "manifest.json"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def offline_plan(root, mode="measured"):
    """Read local inputs only; do not normalize fixture bytes."""
    root = Path(root)
    if mode not in ("measured", "calibration"):
        raise ValueError("Unknown experiment mode.")
    protocol = root / "docs/concurrency-protocol-v1.md"
    protocol_digest = file_hash(protocol)
    if protocol_digest != PROTOCOL_HASH:
        raise ValueError("Protocol does not match the pinned v1 hash.")
    raw = (root / FIXTURE).read_bytes()
    prompt = raw.decode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    manifest = json.loads((root / MANIFEST).read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object.")
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ValueError("Manifest must contain a fixtures list.")

    matches = []
    for item in fixtures:
        if not isinstance(item, dict):
            raise ValueError("Manifest fixture entries must be JSON objects.")
        name = item.get("file")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Manifest fixture entries require a file name.")
        if name == FIXTURE.name:
            matches.append(item)

    if len(matches) != 1:
        raise ValueError("Manifest must contain exactly one target fixture.")
    entry = matches[0]
    if (
        not isinstance(entry.get("prompt_sha256"), str)
        or type(entry.get("utf8_bytes")) is not int
        or entry["utf8_bytes"] < 0
        or type(entry.get("characters")) is not int
        or entry["characters"] < 0
    ):
        raise ValueError("Target fixture metadata is malformed.")
    if (
        digest != PROMPT_HASH
        or entry["prompt_sha256"] != digest
        or entry["utf8_bytes"] != len(raw)
        or entry["characters"] != len(prompt)
    ):
        raise ValueError("Fixture does not match protocol and manifest.")
    schedule = SCHEDULE if mode == "measured" else CALIBRATION_SCHEDULE
    return {
        "mode": mode,
        "live_enabled": False,
        "model": MODEL,
        "model_digest": DIGEST,
        "fixture": str(FIXTURE),
        "prompt_sha256": digest,
        "manifest_sha256": file_hash(root / MANIFEST),
        "protocol_sha256": protocol_digest,
        "payload": build_payload(
            MODEL, prompt=prompt, num_ctx=4096, num_predict=64
        ),
        "schedule": [list(row) for row in schedule],
        "batch_count": sum(len(row) for row in schedule),
        "request_count": sum(sum(row) for row in schedule),
    }


class RunReports:
    """Single coordinator, exclusive directory, journal and per-batch stores.

    Journal and batch checkpoints are individually atomic, not a transaction.
    A storage exception must stop execution. The surviving journal can remain
    incomplete; it must not be treated as evidence of successful completion.
    """

    def __init__(self, directory, provenance):
        self.owner = threading.get_ident()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.stores = {}
        self.identities = {}
        self.journal = {
            "schema_version": "0.1",
            "status": "pending",
            "created_at_utc": utc_now(),
            "provenance": copy.deepcopy(provenance),
            "batches": [],
            "events": [],
        }
        self.journal_store = ReportStore(
            self.directory / "journal.json", self.journal
        )

    def assert_owner(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("Only the coordinator may write reports.")

    def checkpoint(self, report):
        self.assert_owner()
        block, position, concurrency = (
            report[key] for key in ("block", "position", "concurrency")
        )
        if (
            type(block) is not int or block < 1
            or type(position) is not int or position not in (1, 2, 3)
            or type(concurrency) is not int or concurrency not in (1, 2, 4)
        ):
            raise ValueError("Invalid batch identity.")
        key = (block, position)
        if key in self.identities and self.identities[key] != concurrency:
            raise ValueError("Batch concurrency changed for existing identity.")
        snapshot = copy.deepcopy(report)
        snapshot["checkpoint_at_utc"] = utc_now()
        if key not in self.stores:
            name = f"block-{block:02d}-position-{position}-c{concurrency}.json"
            self.stores[key] = ReportStore(self.directory / name, snapshot)
            self.identities[key] = concurrency
            self.journal["batches"].append({
                "block": block, "position": position,
                "concurrency": concurrency, "file": name,
            })
        else:
            self.stores[key].checkpoint(snapshot)
        self.journal["status"] = "running"
        self.journal["events"].append({
            "at_utc": snapshot["checkpoint_at_utc"],
            "block": block, "position": position,
            "status": report["status"],
        })
        self.journal_store.checkpoint(self.journal)

    def finish(self, summary):
        self.assert_owner()
        if summary.get("status") not in ("complete", "stopped", "interrupted"):
            raise ValueError("Invalid terminal run status.")
        hashes = {
            store.path.name: file_hash(store.path)
            for store in self.stores.values()
        }
        self.journal["status"] = summary["status"]
        self.journal["summary"] = copy.deepcopy(summary)
        self.journal["finished_at_utc"] = utc_now()
        self.journal["report_sha256"] = hashes
        self.journal_store.checkpoint(self.journal)
