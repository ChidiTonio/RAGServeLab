#!/usr/bin/env python3
"""Offline concurrency planning. Live execution is not implemented yet."""

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from concurrency_run_store import offline_plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("measured", "calibration"), default="measured"
    )
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    if args.live:
        parser.error(
            "Live execution is disabled pending serving inspection, "
            "preflight implementation, and separate authorization."
        )
    plan = offline_plan(ROOT, args.mode)
    # Exact payload remains available to the future runner; avoid printing
    # the entire fixture in the human-readable offline summary.
    displayed = dict(plan)
    displayed["payload"] = {
        key: value for key, value in plan["payload"].items()
        if key != "prompt"
    }
    displayed["notice"] = "Offline plan only; no requests or output files created."
    print(json.dumps(displayed, indent=2))


if __name__ == "__main__":
    main()
