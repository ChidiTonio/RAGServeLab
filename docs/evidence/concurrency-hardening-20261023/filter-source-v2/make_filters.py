"""Encode reviewed Linux x86-64 classic-BPF policies; no project imports.

Run later using a reviewed system Python with -I -S.
Output directory must be newly created by this program.
"""
import hashlib
import os
import platform
import struct
import sys
from pathlib import Path

# Architecture-specific Linux syscall numbers, not portable constants.
# Deliberately absent: sockets, clone/fork, ptrace, namespace creation,
# mounts, bpf, io_uring, process_vm operations, execveat, and privilege
# changing syscalls. Compatibility must be demonstrated by smoke checks.
SYSCALLS = {
    "read": 0, "write": 1, "open": 2, "close": 3,
    "stat": 4, "fstat": 5, "lstat": 6, "poll": 7,
    "lseek": 8, "mmap": 9, "mprotect": 10, "munmap": 11,
    "brk": 12, "rt_sigaction": 13, "rt_sigprocmask": 14,
    "rt_sigreturn": 15, "ioctl": 16,
    "pread64": 17, "pwrite64": 18, "readv": 19, "writev": 20,
    "access": 21, "pipe": 22, "select": 23,
    "sched_yield": 24, "mremap": 25, "msync": 26,
    "mincore": 27, "madvise": 28, "dup": 32, "dup2": 33,
    "nanosleep": 35, "getpid": 39, "exit": 60, "uname": 63,
    "fcntl": 72, "flock": 73, "fsync": 74, "fdatasync": 75,
    "truncate": 76, "ftruncate": 77, "getdents": 78,
    "getcwd": 79, "chdir": 80, "mkdir": 83, "rmdir": 84,
    "creat": 85, "unlink": 87, "readlink": 89,
    "chmod": 90, "fchmod": 91, "umask": 95,
    "gettimeofday": 96, "getrlimit": 97, "getrusage": 98,
    "sysinfo": 99, "getuid": 102, "getgid": 104,
    "geteuid": 107, "getegid": 108, "getppid": 110,
    "getgroups": 115, "sigaltstack": 131,
    "arch_prctl": 158, "gettid": 186, "time": 201,
    "futex": 202, "sched_getaffinity": 204,
    "getdents64": 217, "set_tid_address": 218,
    "clock_gettime": 228, "clock_getres": 229,
    "clock_nanosleep": 230, "exit_group": 231,
    "openat": 257, "mkdirat": 258, "newfstatat": 262,
    "unlinkat": 263, "renameat": 264, "readlinkat": 267,
    "faccessat": 269, "pselect6": 270, "ppoll": 271,
    "set_robust_list": 273, "dup3": 292, "pipe2": 293,
    "prlimit64": 302, "renameat2": 316, "getrandom": 318,
    "statx": 332, "rseq": 334, "faccessat2": 439,
    "close_range": 436, "rename": 82,
}

# Classic BPF instructions and seccomp return values.
LD_W_ABS = 0x20
JEQ_K = 0x15
JSET_K = 0x45
RET_K = 0x06
KILL_PROCESS = 0x80000000
ALLOW = 0x7fff0000
AUDIT_ARCH_X86_64 = 0xc000003e

def policy(extra):
    allowed = sorted(set(SYSCALLS.values()) | set(extra))
    instructions = [
        (LD_W_ABS, 0, 0, 4),               # seccomp_data.arch
        (JEQ_K, 1, 0, AUDIT_ARCH_X86_64),
        (RET_K, 0, 0, KILL_PROCESS),
        (LD_W_ABS, 0, 0, 0),               # seccomp_data.nr
        (JSET_K, 0, 1, 0x40000000),        # reject x32 ABI
        (RET_K, 0, 0, KILL_PROCESS),
    ]
    for number in allowed:
        instructions.extend([
            (JEQ_K, 0, 1, number),
            (RET_K, 0, 0, ALLOW),
        ])
    instructions.append((RET_K, 0, 0, KILL_PROCESS))
    return b"".join(struct.pack("<HBBI", *row) for row in instructions)

def main():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("Unsupported operating system or architecture")
    if sys.byteorder != "little" or struct.calcsize("P") != 8:
        raise SystemExit("Unsupported Python ABI")
    if len(sys.argv) != 2:
        raise SystemExit("Usage: make_filters.py NEW_OUTPUT_DIRECTORY")

    output = Path(sys.argv[1])
    output.mkdir(mode=0o700, parents=False, exist_ok=False)

    # Startup needs execve for Bubblewrap's final launch, and prctl for
    # installing the stricter filter. Neither survives in the final policy.
    products = {
        "startup.bpf": policy({59, 61, 157}),
        "locked.bpf": policy(set()),
    }
    manifest = []
    for name, raw in products.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)
        os.chmod(output / name, 0o400)
        manifest.append(f"{hashlib.sha256(raw).hexdigest()}  {name}\n")
    with (output / "FILTERS.sha256").open("x", encoding="ascii") as stream:
        stream.writelines(manifest)
    os.chmod(output / "FILTERS.sha256", 0o400)
    print("FILTERS ENCODED — NOT YET ENFORCEMENT-VERIFIED")
    print("".join(manifest), end="")

if __name__ == "__main__":
    main()
