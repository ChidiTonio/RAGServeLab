"""Single-request Ollama serving probe. Uses only the Python standard library."""

import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:11434"
PROMPT = "Explain retrieval-augmented generation in three concise sentences."


def get_json(path):
    with urlopen(BASE_URL + path, timeout=10) as response:
        return json.load(response)


def read_stream(lines, started, clock=time.perf_counter):
    """Consume Ollama NDJSON; require a successful completion event."""
    first_text_s = None
    fragments = []
    final_event = None

    for raw in lines:
        if not raw.strip():
            continue

        event = json.loads(raw)
        if "error" in event:
            raise RuntimeError(str(event["error"]))

        text = event.get("response", "")
        if text:
            if first_text_s is None:
                first_text_s = clock() - started
            fragments.append(text)

        if event.get("done") is True:
            final_event = event
            break

    elapsed_s = clock() - started
    if final_event is None:
        raise RuntimeError("Stream ended without a completion event.")
    if first_text_s is None:
        raise RuntimeError("Completed request produced no generated text.")

    return {
        "client_first_text_s": first_text_s,
        "client_total_s": elapsed_s,
        "answer": "".join(fragments),
        "final_event": final_event,
    }


def runtime_metrics(event):
    result = {}
    for key in (
        "total_duration",
        "load_duration",
        "prompt_eval_duration",
        "eval_duration",
    ):
        value = event.get(key)
        result[key + "_s"] = (
            value / 1_000_000_000 if value is not None else None
        )

    result["prompt_eval_count"] = event.get("prompt_eval_count")
    result["prompt_eval_cached_count"] = event.get("prompt_eval_cached_count")
    result["eval_count"] = event.get("eval_count")
    count = result["eval_count"]
    duration = result["eval_duration_s"]
    result["generation_tokens_per_s"] = (
        count / duration
        if count is not None and duration and duration > 0
        else None
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if args.out.exists():
        parser.error(f"Output already exists: {args.out}")

    payload = {
        "model": args.model,
        "prompt": PROMPT,
        "stream": True,
        "keep_alive": "5m",
        "options": {
            "temperature": 0,
            "seed": 42,
            "num_ctx": 2048,
            "num_predict": 128,
        },
    }
    report = {
        "schema_version": "0.1",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "client_platform": platform.platform(),
        "endpoint": BASE_URL,
        "request": payload,
        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
        "status": "error",
    }

    try:
        report["server_version"] = get_json("/api/version")
        models = get_json("/api/tags")["models"]
        selected = next(
            (model for model in models if model["name"] == args.model),
            None,
        )
        if selected is None:
            raise RuntimeError(f"Model is not installed: {args.model}")

        report["model_metadata"] = selected
        report["residency_before"] = get_json("/api/ps")

        request = Request(
            BASE_URL + "/api/generate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        with urlopen(request, timeout=180) as response:
            result = read_stream(response, started)

        report.update(result)
        report["runtime_metrics"] = runtime_metrics(result["final_event"])
        report["status"] = "success"

        try:
            report["residency_after"] = get_json("/api/ps")
        except (OSError, ValueError) as exc:
            report["residency_after_error"] = (
                f"{type(exc).__name__}: {exc}"
            )

    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Status: {report['status']}; report: {args.out}")
    if report["status"] == "success":
        print(f"First text: {report['client_first_text_s']:.3f} s")
        print(f"Total:      {report['client_total_s']:.3f} s")
        print(report["answer"])
    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
