"""Trusted control checks only. Does not import project modules."""
print("DIAG smoke:2 before-import", flush=True)
import ctypes
print("DIAG smoke:2 after-import", flush=True)
print("DIAG smoke:3 before-import", flush=True)
import errno
print("DIAG smoke:3 after-import", flush=True)
print("DIAG smoke:4 before-import", flush=True)
import os
print("DIAG smoke:4 after-import", flush=True)
print("DIAG smoke:5 before-import", flush=True)
from pathlib import Path
print("DIAG smoke:5 after-import", flush=True)
print("DIAG smoke:6 before-import", flush=True)
import sys
print("DIAG smoke:6 after-import", flush=True)
print("DIAG smoke:7 before-import", flush=True)
import tempfile
print("DIAG smoke:7 after-import", flush=True)

# bootstrap defines controls but does not run its main when imported.
print("DIAG smoke:10 before-control-path", flush=True)
sys.path.insert(0, "/controls")
print("DIAG smoke:10 after-control-path", flush=True)
print("DIAG smoke:11 before-import", flush=True)
import bootstrap
print("DIAG smoke:11 after-import", flush=True)

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def main():
    require(sys.flags.isolated and sys.flags.no_site,
            "Require isolated Python without site initialization")
    require(sys.dont_write_bytecode, "Require bytecode writes disabled")
    require(Path.cwd() == Path("/tmp/tests"), "Unexpected working directory")
    require(len(sys.argv) == 2, "Expected exactly one smoke mode")
    mode = sys.argv[1]

    # Load ctypes machinery before the tighter filter.
    print("DIAG smoke:26 before-libc-load", flush=True)
    libc = ctypes.CDLL(None, use_errno=True)
    print("DIAG smoke:26 after-libc-load", flush=True)
    syscall = libc.syscall
    syscall.restype = ctypes.c_long

    if mode != "startup-socket":
        print("DIAG smoke:31 before-locked-filter", flush=True)
        bootstrap.install_filter()
        print("DIAG smoke:31 after-locked-filter", flush=True)

    if mode == "allowed":
        print("DIAG smoke:34 before-temporary-files", flush=True)
        with tempfile.TemporaryDirectory(dir="/tmp/tests") as directory:
            root = Path(directory)
            original = root / "original"
            replacement = root / "replacement"
            original.write_text("initial", encoding="utf-8")
            replacement.write_text("replacement", encoding="utf-8")
            os.replace(replacement, original)
            require(original.read_text() == "replacement",
                    "Atomic replacement failed")

        # Require mount-level protection independently of file permissions.
        print("DIAG smoke:45 before-snapshot-check", flush=True)
        snapshot_mounts = []
        for entry in Path("/proc/self/mountinfo").read_text(
                encoding="utf-8").splitlines():
            mount_fields, separator, filesystem_fields = entry.partition(" - ")
            require(bool(separator), "Malformed mountinfo entry")
            fields = mount_fields.split()
            require(len(fields) >= 6, "Malformed mountinfo mount fields")
            if fields[4] == "/snapshot":
                snapshot_mounts.append(set(fields[5].split(",")))
        require(len(snapshot_mounts) == 1,
                "Expected exactly one /snapshot mount")
        require("ro" in snapshot_mounts[0],
                "Snapshot mount is not read-only")
        print("DIAG snapshot mount-read-only verified", flush=True)

        target = Path("/snapshot/concurrency_preflight.py")
        require(target.is_file(), "Snapshot mount missing")
        require(bool(target.read_bytes()), "Snapshot read failed")
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_APPEND)
        except OSError as exc:
            require(exc.errno in (errno.EROFS, errno.EACCES),
                    "Expected snapshot write denial")
            print(f"DIAG snapshot write-denied errno={exc.errno}", flush=True)
        else:
            os.close(descriptor)
            raise RuntimeError("Snapshot unexpectedly writable")

        print("DIAG smoke:57 before-hidden-path-checks", flush=True)
        require(not Path("/home").exists(), "Home mount unexpectedly present")
        require(not Path("/root").exists(), "Root home unexpectedly present")
        require(not Path("/repo").exists(), "Repository mount unexpectedly present")

        # Linux exposes only the fresh namespace's loopback interface.
        print("DIAG smoke:62 before-network-interface-read", flush=True)
        interfaces = {
            line.split(":", 1)[0].strip()
            for line in Path("/proc/net/dev").read_text().splitlines()[2:]
            if ":" in line
        }
        require(interfaces == {"lo"}, "Unexpected network interfaces")

        print("SMOKE_ALLOWED_PASS", flush=True)
        return 0

    # These syscall numbers are Linux x86-64 only.
    print("EXPECTED_SECCOMP_TERMINATION " + mode, flush=True)
    if mode in {"startup-socket", "locked-socket"}:
        syscall(41, 2, 1, 0)             # socket(AF_INET, SOCK_STREAM, 0)
    elif mode == "locked-fork":
        syscall(57)                      # fork
    elif mode == "locked-exec":
        # Even a nonexistent executable must be denied at syscall entry.
        syscall(59, ctypes.c_char_p(b"/nonexistent"),
                ctypes.c_void_p(), ctypes.c_void_p())
    elif mode == "locked-x32":
        syscall(0x40000000 | 39)          # x32-tagged getpid
    else:
        raise RuntimeError("Unknown smoke mode")

    raise RuntimeError("Forbidden syscall returned; enforcement check failed")

if __name__ == "__main__":
    raise SystemExit(main())
