"""Local Git provenance checks; no server access or authorization."""

import hashlib
import subprocess
from pathlib import Path, PurePosixPath


REQUIRED_FILES = (
    "concurrency.py",
    "concurrency_batch_validation.py",
    "concurrency_experiment.py",
    "concurrency_run_store.py",
    "concurrency_validation.py",
    "concurrency_provenance.py",
    "concurrency_preflight.py",
    "probe.py",
    "residency.py",
    "report_store.py",
    "scripts/run_concurrency.py",
    "docs/concurrency-protocol-v1.md",
    "workloads/evidence-length-v1/distractors-08.txt",
    "workloads/evidence-length-v1/manifest.json",
)


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Git provenance check failed: {detail}")
    return result.stdout


def capture_provenance(root, required=REQUIRED_FILES):
    """Require a committed, clean revision and exact required-file bytes."""
    root = Path(root).resolve()
    top = Path(
        git(root, "rev-parse", "--show-toplevel").decode().strip()
    ).resolve()
    if top != root:
        raise ValueError("Provenance root must be the Git repository root.")

    commit = git(root, "rev-parse", "--verify", "HEAD").decode().strip()
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("Tracked modifications prevent execution provenance.")

    hashes = {}
    for name in required:
        if not isinstance(name, str):
            raise ValueError("Required paths must be strings.")
        relative = PurePosixPath(name)
        if (
            not name or relative.is_absolute()
            or ".." in relative.parts or str(relative) != name
            or name in hashes
        ):
            raise ValueError("Invalid or duplicate required path.")
        path = root / name
        if path.is_symlink() or root not in path.resolve().parents:
            raise ValueError(f"Required path is not a local regular file: {name}")
        if not path.is_file():
            raise ValueError(f"Required file is missing: {name}")
        try:
            committed = git(root, "show", f"{commit}:{name}")
        except RuntimeError as exc:
            raise ValueError(
                f"Required file is absent from execution commit: {name}"
            ) from exc
        working = path.read_bytes()
        if working != committed:
            raise ValueError(f"Required file differs from commit: {name}")
        hashes[name] = hashlib.sha256(working).hexdigest()

    # Recheck after collecting hashes to catch changes during inspection.
    if (
        git(root, "rev-parse", "--verify", "HEAD").decode().strip() != commit
        or git(root, "status", "--porcelain", "--untracked-files=no").strip()
    ):
        raise ValueError("Revision changed during provenance inspection.")

    untracked = git(
        root, "ls-files", "--others", "--exclude-standard", "-z"
    )
    return {
        "execution_commit": commit,
        "file_sha256": hashes,
        "untracked_paths": [
            item.decode("utf-8", errors="surrogateescape")
            for item in untracked.split(b"\0") if item
        ],
    }


def verify_provenance(root, baseline):
    """Recheck commit and required-file hashes at a later boundary."""
    current = capture_provenance(root, tuple(baseline["file_sha256"]))
    if (
        current["execution_commit"] != baseline["execution_commit"]
        or current["file_sha256"] != baseline["file_sha256"]
    ):
        raise ValueError("Execution provenance changed.")
    return current
