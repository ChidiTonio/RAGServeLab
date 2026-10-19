"""Exclusive report creation and atomic checkpoint replacement."""

import json
import os
import tempfile
from pathlib import Path


def encode_report(report):
    """Serialize before touching the report file; reject non-finite numbers."""
    return json.dumps(report, indent=2, allow_nan=False) + "\n"


class ReportStore:
    """Store one report, assuming a single writer owns the output path.

    Initial creation is exclusive. Later checkpoints use same-directory
    atomic replacement. This does not guarantee power-loss durability.
    """

    def __init__(self, path, initial_report):
        self.path = Path(path)
        text = encode_report(initial_report)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("x", encoding="utf-8") as stream:
            stream.write(text)

    def checkpoint(self, report):
        text = encode_report(report)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(text)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
