"""Offline checks by default; --execute runs the committed schedule."""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKLOAD = ROOT / "workloads/evidence-length-v1"
DIGEST = "357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b"
OPTIONS = {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 64}
SCHEDULE = (
    (0, 8, 24), (8, 24, 0), (24, 0, 8),
    (0, 24, 8), (24, 8, 0), (8, 0, 24),
)
PREPARATION = {
    "A": ["unload", "verify_absent"],
    "B": ["unload", "verify_absent", "load", "verify_present"],
    "C": ["verify_present"],
}
CALIBRATION = {
    0: "evidence-length-v1-d00-calibration-20261019T133539Z.json",
    8: "evidence-length-v1-d08-calibration-20261019T133547Z.json",
    24: "evidence-length-v1-d24-calibration-20261019T132605Z.json",
}

def utc():
    return datetime.now(timezone.utc).isoformat()

def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

def sha256(raw):
    return hashlib.sha256(raw).hexdigest()

def require(condition, message):
    if not condition:
        raise ValueError(message)

def git(*args):
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True
    ).strip()

def load_fixtures():
    manifest = json.loads((WORKLOAD / "manifest.json").read_bytes())
    fixtures = {}
    for item in manifest["fixtures"]:
        level = item["distractor_passages"]
        path = WORKLOAD / item["file"]
        raw = path.read_bytes()
        require(sha256(raw) == item["prompt_sha256"],
                f"Fixture hash mismatch: {path}")
        fixtures[level] = {
            "path": path, "prompt": raw.decode("utf-8"),
            "sha256": item["prompt_sha256"],
        }
    require(set(fixtures) == {0, 8, 24}, "Unexpected fixture levels")
    return fixtures

def validate_report(path, fixture):
    report = json.loads(path.read_bytes())
    require(report["status"] == "success", "Report failed")
    require(report["experiment"] == "sequential_abc", "Wrong experiment")
    require(report["requested_trials"] == 1, "Wrong requested trial count")
    require(report["endpoint"] == "http://127.0.0.1:11434", "Wrong endpoint")
    require(report["server_version"]["version"] == "0.40.6",
            "Server version changed")
    request = report["request"]
    require(request["model"] == "qwen2.5:3b", "Wrong model")
    require(request["stream"] is True, "Streaming disabled")
    require(request["keep_alive"] == "5m", "Wrong keep_alive")
    require(request["options"] == OPTIONS, "Settings mismatch")
    require(request["prompt"] == fixture["prompt"], "Prompt mismatch")
    require(report["prompt_sha256"] == fixture["sha256"],
            "Prompt hash mismatch")
    require(len(report["trials"]) == 1, "Wrong saved trial count")
    trial = report["trials"][0]
    require(trial["trial_number"] == 1, "Wrong trial number")
    require(trial["status"] == "success", "Trial failed")
    conditions = trial["conditions"]
    require([c["condition"] for c in conditions] == ["A", "B", "C"],
            "Wrong condition order")
    for condition in conditions:
        name = condition["condition"]
        require(condition["status"] == "success", f"{name}: failed")
        steps = condition["preparation"]
        require([s["kind"] for s in steps] == PREPARATION[name],
                f"{name}: preparation mismatch")
        for step in steps:
            record = step["record"]
            require(record["status"] == "success",
                    f"{name}: preparation failed")
            if step["kind"] in ("verify_absent", "verify_present"):
                expected = step["kind"] == "verify_present"
                require(record["model_digest"] == DIGEST,
                        f"{name}: verification digest mismatch")
                require(record["expected_present"] is expected,
                        f"{name}: wrong verification expectation")
                observation = record["observations"][-1]
                require(observation["status"] == "success",
                        f"{name}: final observation failed")
                models = observation["response"]["models"]
                targets = [m for m in models if m["digest"] == DIGEST]
                require(observation["present"] is expected,
                        f"{name}: presence check failed")
                require(bool(targets) == expected,
                        f"{name}: digest presence mismatch")
                if expected:
                    require(all(m["context_length"] == 4096 for m in targets),
                            f"{name}: residency context mismatch")
            if step["kind"] == "load":
                require(record["request"]["options"]["num_ctx"] == 4096,
                        f"{name}: preload context mismatch")
        generation = condition["generation"]
        require(generation["final_event"]["done"] is True,
                f"{name}: missing completed stream")
        require(isinstance(generation["answer"], str),
                f"{name}: missing answer")
    # Answer correctness and completion reason are not exclusion gates.

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="Send live requests; default is offline checks.")
    args = parser.parse_args()
    fixtures = load_fixtures()
    for level, filename in CALIBRATION.items():
        validate_report(ROOT / "results" / filename, fixtures[level])
        print(f"Offline validation passed: {level} distractors")
    for block, levels in enumerate(SCHEDULE, 1):
        print(f"Block {block}: {' -> '.join(map(str, levels))}")
    if not args.execute:
        print("Offline checks complete. No live requests sent.")
        return

    require(git("diff", "HEAD", "--name-only") == "",
            "Tracked changes present; commit them before execution")
    commit = git("rev-parse", "HEAD")
    directory = ROOT / "results" / f"evidence-length-v1-repeated-{stamp()}"
    directory.mkdir(exist_ok=False)
    journal = directory / "journal.jsonl"

    def record(entry):
        with journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"utc": utc(), **entry}) + "\n")

    record({
        "event": "start", "execution_commit": commit,
        "python": sys.version, "schedule": SCHEDULE,
        "runner_sha256": sha256(Path(__file__).read_bytes()),
        "protocol_sha256": sha256(
            (ROOT / "docs/evidence-length-repeated-protocol-v1.md").read_bytes()
        ),
        "fixture_sha256": {k: v["sha256"] for k, v in fixtures.items()},
    })
    print(f"Run directory: {directory}", flush=True)
    try:
        for block, levels in enumerate(SCHEDULE, 1):
            for position, level in enumerate(levels, 1):
                require(git("rev-parse", "HEAD") == commit,
                        "Execution commit changed")
                require(git("diff", "HEAD", "--name-only") == "",
                        "Tracked files changed during execution")
                fixture = fixtures[level]
                require(sha256(fixture["path"].read_bytes()) == fixture["sha256"],
                        "Fixture changed during execution")
                report = directory / (
                    f"b{block:02d}-p{position}-d{level:02d}-{stamp()}.json"
                )
                require(not report.exists(), "Report already exists")
                command = [
                    sys.executable, str(ROOT / "benchmark.py"),
                    "--model", "qwen2.5:3b", "--out", str(report),
                    "--trials", "1", "--prompt-file", str(fixture["path"]),
                    "--num-ctx", "4096", "--num-predict", "64",
                ]
                identity = {
                    "block": block, "position": position, "level": level,
                    "report": str(report.relative_to(ROOT)),
                }
                record({"event": "invocation_start", **identity,
                        "command": command})
                code = subprocess.call(command, cwd=ROOT)
                record({
                    "event": "invocation_exit", **identity, "exit_code": code,
                    "report_sha256": (
                        sha256(report.read_bytes()) if report.exists() else None
                    ),
                })
                require(code == 0, f"Benchmark exit code: {code}")
                validate_report(report, fixture)
                record({"event": "validation_pass", **identity})
        record({"event": "complete"})
        print("All 18 scheduled trials completed and validated.")
    except BaseException as error:
        record({"event": "stopped", "error": repr(error)})
        raise

if __name__ == "__main__":
    main()
