"""Verify one completed scheduled run and create separate analysis files."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from run_evidence_length import (
    ROOT, SCHEDULE, load_fixtures, require, validate_report,
)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_csv(path, rows, fields):
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def seconds(event, key):
    value = event.get(key)
    return None if value is None else value / 1_000_000_000

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    events = [
        json.loads(line)
        for line in (run / "journal.jsonl").read_text().splitlines()
    ]
    require(events[0]["event"] == "start", "Missing start event")
    require(events[-1]["event"] == "complete", "Run is not complete")
    require(not any(e["event"] == "stopped" for e in events),
            "Journal contains a stopped event")
    start = events[0]
    require(start["schedule"] == [list(levels) for levels in SCHEDULE],
            "Schedule mismatch")
    require(digest(ROOT / "scripts/run_evidence_length.py")
            == start["runner_sha256"], "Runner hash mismatch")
    require(digest(ROOT / "docs/evidence-length-repeated-protocol-v1.md")
            == start["protocol_sha256"], "Protocol hash mismatch")
    fixtures = load_fixtures()
    require(start["fixture_sha256"] ==
            {str(k): v["sha256"] for k, v in fixtures.items()},
            "Journal fixture hashes mismatch")

    expected = [
        (block, position, level)
        for block, levels in enumerate(SCHEDULE, 1)
        for position, level in enumerate(levels, 1)
    ]
    groups = {}
    for kind in ("invocation_start", "invocation_exit", "validation_pass"):
        groups[kind] = [e for e in events if e["event"] == kind]
        require(
            [(e["block"], e["position"], e["level"]) for e in groups[kind]]
            == expected, f"{kind}: missing, duplicate, or reordered visits",
        )

    observations, pairs, scoring, hashes = [], [], [], []
    saved_paths = set()
    for begin, exit_event, validated in zip(
        groups["invocation_start"], groups["invocation_exit"],
        groups["validation_pass"],
    ):
        require(begin["report"] == exit_event["report"] == validated["report"],
                "Journal report paths disagree")
        path = (ROOT / exit_event["report"]).resolve()
        require(path.parent == run, "Report outside selected run directory")
        require(exit_event["exit_code"] == 0, "Nonzero exit code")
        report_hash = digest(path)
        require(report_hash == exit_event["report_sha256"],
                f"Report hash mismatch: {path.name}")
        level = exit_event["level"]
        validate_report(path, fixtures[level])
        saved_paths.add(path)
        hashes.append({"report": path.name, "sha256": report_hash})
        report = json.loads(path.read_bytes())
        identity = {
            "block": exit_event["block"],
            "position": exit_event["position"],
            "distractors": level,
            "report": path.name,
        }
        by_condition = {}
        for condition in report["trials"][0]["conditions"]:
            generation = condition["generation"]
            event = generation["final_event"]
            duration = seconds(event, "eval_duration")
            count = event.get("eval_count")
            row = {
                **identity,
                "condition": condition["condition"],
                "client_first_text_s": generation.get("client_first_text_s"),
                "client_total_s": generation.get("client_total_s"),
                "server_total_s": seconds(event, "total_duration"),
                "server_load_s": seconds(event, "load_duration"),
                "server_prompt_eval_s": seconds(event, "prompt_eval_duration"),
                "server_eval_s": duration,
                "generation_tokens_per_s": (
                    count / duration
                    if count is not None and duration is not None
                    and duration > 0 else None
                ),
                "prompt_eval_count": event.get("prompt_eval_count"),
                "prompt_eval_cached_count": event.get("prompt_eval_cached_count"),
                "eval_count": count,
                "done_reason": event.get("done_reason"),
            }
            observations.append(row)
            by_condition[row["condition"]] = row
            scoring.append({
                **identity, "condition": row["condition"],
                "answer": generation["answer"],
                "done_reason": row["done_reason"],
                "fact_correctness": "",
                "citation_correctness": "",
                "extra_or_conflicting_citations": "",
                "unsupported_claims": "",
                "format_compliance": "",
                "review_notes": "",
            })
        pair = dict(identity)
        for metric in (
            "client_first_text_s", "client_total_s", "server_prompt_eval_s",
            "generation_tokens_per_s",
        ):
            b, c = by_condition["B"][metric], by_condition["C"][metric]
            pair[f"B_minus_C_{metric}"] = (
                None if b is None or c is None else b - c
            )
        pairs.append(pair)

    require(saved_paths == {p.resolve() for p in run.glob("b*.json")},
            "Unjournaled or missing report files")
    require(len(observations) == 54, "Wrong generation count")

    summary = []
    metrics = [
        key for key in observations[0]
        if key not in ("block", "position", "distractors", "report",
                       "condition", "done_reason")
    ]
    for level in (0, 8, 24):
        for condition in ("A", "B", "C"):
            selected = [r for r in observations
                        if r["distractors"] == level
                        and r["condition"] == condition]
            for metric in metrics:
                values = [r[metric] for r in selected if r[metric] is not None]
                summary.append({
                    "distractors": level, "comparison": condition,
                    "metric": metric, "n_available": len(values),
                    "n_missing": len(selected) - len(values),
                    "median": median(values) if values else None,
                    "minimum": min(values) if values else None,
                    "maximum": max(values) if values else None,
                })
        selected = [r for r in pairs if r["distractors"] == level]
        for metric in pairs[0]:
            if not metric.startswith("B_minus_C_"):
                continue
            values = [r[metric] for r in selected if r[metric] is not None]
            summary.append({
                "distractors": level, "comparison": "B-C",
                "metric": metric, "n_available": len(values),
                "n_missing": len(selected) - len(values),
                "median": median(values) if values else None,
                "minimum": min(values) if values else None,
                "maximum": max(values) if values else None,
            })

    # Create outputs only after all evidence checks pass.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = run / f"analysis-{stamp}"
    out.mkdir(exist_ok=False)
    for filename, rows in (
        ("observations.csv", observations),
        ("paired-differences.csv", pairs),
        ("summary.csv", summary),
        ("answer-scoring.csv", scoring),
        ("report-hashes.csv", hashes),
    ):
        write_csv(out / filename, rows, list(rows[0]))
    (out / "provenance.json").write_text(json.dumps({
        "source_run": str(run.relative_to(ROOT)),
        "execution_commit": start["execution_commit"],
        "journal_sha256": digest(run / "journal.jsonl"),
        "analysis_script_sha256": digest(Path(__file__)),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "operator_interaction": (
            "Terminal output showed typed q and exit during execution. "
            "Run completed; measurement impact is undetermined."
        ),
        "environment_note": (
            "Power settings, other-client activity, and other interruptions "
            "require operator confirmation; not independently verified."
        ),
        "scoring_status": "Pending manual review using manifest rubric.",
    }, indent=2) + "\n", encoding="utf-8")

    print("Verified: 18 report hashes, schedule, provenance hashes, and reports.")
    print("Extracted: 54 observations and 18 within-trial B-C pairs.")
    print("Completion reasons:", dict(Counter(
        r["done_reason"] for r in observations
    )))
    print("\nPrimary B measurements: seconds, median [minimum, maximum]")
    for row in summary:
        if row["comparison"] == "B" and row["metric"] in (
            "client_first_text_s", "server_prompt_eval_s",
        ):
            print(
                f"d{row['distractors']:02d} {row['metric']}: "
                f"{row['median']} [{row['minimum']}, {row['maximum']}] "
                f"n={row['n_available']}, missing={row['n_missing']}"
            )
    print("\nAnalysis directory:", out)
    print("Answer scoring is pending; blank cells are not passing scores.")

if __name__ == "__main__":
    main()
