"""Guarded entry point; intended ONLY for the authenticated sandbox."""
print("DIAG bootstrap:2 before-import", flush=True)
import ctypes
print("DIAG bootstrap:2 after-import", flush=True)
print("DIAG bootstrap:3 before-import", flush=True)
import importlib.abc
print("DIAG bootstrap:3 after-import", flush=True)
print("DIAG bootstrap:4 before-import", flush=True)
import importlib.machinery
print("DIAG bootstrap:4 after-import", flush=True)
print("DIAG bootstrap:5 before-import", flush=True)
import os
print("DIAG bootstrap:5 after-import", flush=True)
print("DIAG bootstrap:6 before-import", flush=True)
from pathlib import Path
print("DIAG bootstrap:6 after-import", flush=True)
print("DIAG bootstrap:7 before-import", flush=True)
import sys
print("DIAG bootstrap:7 after-import", flush=True)
print("DIAG bootstrap:8 before-import", flush=True)
import tempfile
print("DIAG bootstrap:8 after-import", flush=True)
print("DIAG bootstrap:9 before-import", flush=True)
import types
print("DIAG bootstrap:9 after-import", flush=True)
print("DIAG bootstrap:10 before-import", flush=True)
import unittest
print("DIAG bootstrap:10 after-import", flush=True)

PROJECT_MODULES = frozenset({
    "concurrency_preflight", "concurrency_run_store",
    "concurrency_experiment", "report_store", "probe",
    "test_concurrency_offline_input_validation",
})
SHIM_SYMBOLS = {
    "concurrency": ("run_batch",),
    "concurrency_batch_validation": ("validate_successful_batch",),
    "residency": ("control_model", "verify_residency"),
    "concurrency_validation": ("validate_residency_record",),
}
EXPECTED_METHODS = frozenset({
    "test_valid_manifest_preserves_offline_plan",
    "test_malformed_manifests_raise_value_error",
    "test_malformed_manifests_are_persisted_as_failed_reports",
    "test_nonfinite_evidence_is_rejected_before_retention",
})
WRITE_ROOT = Path("/tmp/tests")
SOURCE_ROOT = Path("/snapshot")
CONTROL_ROOT = Path("/controls")

class SecurityViolation(BaseException):
    """Not swallowed by ordinary project Exception handlers."""

def install_filter():
    raw = (CONTROL_ROOT / "locked.bpf").read_bytes()
    if not raw or len(raw) % 8 or len(raw) // 8 > 4096:
        raise SecurityViolation("Invalid classic-BPF filter size")

    class SockFilter(ctypes.Structure):
        _fields_ = [
            ("code", ctypes.c_ushort),
            ("jt", ctypes.c_ubyte),
            ("jf", ctypes.c_ubyte),
            ("k", ctypes.c_uint32),
        ]

    class SockFprog(ctypes.Structure):
        _fields_ = [
            ("len", ctypes.c_ushort),
            ("filter", ctypes.POINTER(SockFilter)),
        ]

    rows = (SockFilter * (len(raw) // 8)).from_buffer_copy(raw)
    program = SockFprog(len(rows), rows)
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.restype = ctypes.c_int

    # Set no_new_privs, then install the irreversible additional filter.
    if prctl(38, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS failed")
    if prctl(22, 2, ctypes.byref(program), 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_SECCOMP failed")

def inside(path, root):
    resolved = Path(path).resolve()
    return resolved == root or root in resolved.parents

def main():
    if not sys.flags.isolated or not sys.flags.no_site:
        raise SecurityViolation("Require Python -I -S")
    if not sys.dont_write_bytecode:
        raise SecurityViolation("Require Python -B")
    if not hasattr(sys, "stdlib_module_names"):
        raise SecurityViolation("Require Python 3.10 or newer")
    if not WRITE_ROOT.is_dir():
        raise SecurityViolation("Sandbox test directory missing")
    if Path.cwd() != WRITE_ROOT:
        raise SecurityViolation("Unexpected working directory")

    # Preload trusted dependencies before installing audit restrictions.
    import unittest.mock
    import json
    import hashlib
    import threading
    import urllib.request
    import datetime

    # Remove distribution/vendor package paths; retain only runtime
    # paths beneath the trusted interpreter prefix.
    runtime = Path(sys.base_prefix).resolve()
    trusted_paths = []
    for entry in sys.path:
        if not entry:
            continue
        parts = Path(entry).parts
        if "site-packages" in parts or "dist-packages" in parts:
            continue
        if inside(entry, runtime):
            trusted_paths.append(entry)
    if not trusted_paths:
        raise SecurityViolation("No trusted standard-library paths")
    sys.path[:] = [str(SOURCE_ROOT)] + trusted_paths
    tempfile.tempdir = str(WRITE_ROOT)

    violations = []

    def reject(message):
        violations.append(message)
        raise SecurityViolation(message)

    def blocked(name):
        def call(*args, **kwargs):
            reject("Forbidden operational call: " + name)
        return call

    for name, symbols in SHIM_SYMBOLS.items():
        if name in sys.modules:
            reject("Operational module was loaded before controls: " + name)
        module = types.ModuleType(name)
        module.__file__ = "<fail-closed-shim>"
        module.__all__ = list(symbols)
        for symbol in symbols:
            setattr(module, symbol, blocked(name + "." + symbol))
        sys.modules[name] = module

    class ImportBoundary(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            top = fullname.split(".", 1)[0]
            if top in SHIM_SYMBOLS:
                reject("Unexpected operational submodule import: " + fullname)
            if top in PROJECT_MODULES:
                if fullname != top:
                    reject("Unexpected project submodule: " + fullname)
                spec = importlib.machinery.PathFinder.find_spec(
                    fullname, [str(SOURCE_ROOT)]
                )
                expected = SOURCE_ROOT / (fullname + ".py")
                if spec is None or Path(spec.origin) != expected:
                    reject("Unexpected project module origin: " + fullname)
                return spec
            if top not in sys.stdlib_module_names:
                reject("Import outside allowlist: " + fullname)
            return None

    sys.meta_path.insert(0, ImportBoundary())

    def writable(path):
        if isinstance(path, int):
            reject("Unexpected descriptor-based file operation")
        if not inside(os.fsdecode(path), WRITE_ROOT):
            reject("Write outside /tmp/tests: " + repr(path))

    def audit(event, args):
        if event == "open":
            path, mode, flags = args
            if isinstance(path, int):
                reject("Unexpected descriptor-based open")
            is_write = bool(
                flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT |
                         os.O_TRUNC | os.O_APPEND)
            )
            if is_write:
                writable(path)
        elif event in {
            "os.mkdir", "os.remove", "os.rmdir", "os.chmod",
            "os.truncate", "os.utime",
        }:
            writable(args[0])
        elif event == "os.rename":
            writable(args[0])
            writable(args[1])
        elif event in {"os.link", "os.symlink"}:
            reject("Link creation prohibited")
        elif event == "os.chdir":
            writable(args[0])
        elif (
            event.startswith("socket.")
            or event.startswith("subprocess.")
            or event.startswith("os.exec")
            or event.startswith("os.spawn")
            or event in {"os.system", "os.fork", "os.forkpty"}
            or event.startswith("ctypes.")
        ):
            reject("Forbidden runtime operation: " + event)

    # Kernel restrictions must succeed before any project import.
    install_filter()
    sys.addaudithook(audit)

    module = __import__("test_concurrency_offline_input_validation")
    cls = module.OfflineInputValidationTests
    loader = unittest.TestLoader()
    names = frozenset(loader.getTestCaseNames(cls))
    if names != EXPECTED_METHODS:
        reject("Test method set differs from the reviewed scope")
    suite = loader.loadTestsFromTestCase(cls)
    if suite.countTestCases() != 4:
        reject("Expected exactly four tests")

    class Result(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.nonfinite_subcases = 0

        def addSubTest(self, test, subtest, error):
            if test._testMethodName == (
                "test_nonfinite_evidence_is_rejected_before_retention"
            ):
                self.nonfinite_subcases += 1
            super().addSubTest(test, subtest, error)

    result = unittest.TextTestRunner(
        verbosity=2, resultclass=Result
    ).run(suite)

    good = (
        result.wasSuccessful()
        and result.testsRun == 4
        and result.nonfinite_subcases == 7
        and not violations
    )
    print("CONTROL_SUMMARY", {
        "tests_run": result.testsRun,
        "nonfinite_subcases": result.nonfinite_subcases,
        "security_violations": violations,
        "passed": good,
    })
    return 0 if good else 1

if __name__ == "__main__":
    raise SystemExit(main())
