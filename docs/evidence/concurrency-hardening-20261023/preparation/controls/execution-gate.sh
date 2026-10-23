#!/bin/sh
printf '%s\n' \
    'BLOCKED: seccomp, guarded bootstrap, and authentication gates unresolved.' \
    'This preparation does not authorize or launch tests.' >&2
exit 125
