"""Run a command in its own session, fully detached (macOS has no setsid).

The gate-pilot arms outlive the agent harness that starts them, so they must not
share its process group — a harness kill signals the whole group. `os.setsid()`
in the child puts the arm in a session of its own; stdio is redirected to the
log file so nothing is lost when the parent terminal goes away.

Usage: python experiments/seedcraft/detach.py <logfile> <cmd> [args...]
"""

import os
import sys

log, cmd = sys.argv[1], sys.argv[2:]
if os.fork():
    sys.exit(0)          # parent returns to the caller immediately
os.setsid()              # new session: no controlling terminal, own group
if os.fork():
    os._exit(0)          # second fork: cannot reacquire a terminal
fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
os.dup2(fd, 1)
os.dup2(fd, 2)
os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
os.execvp(cmd[0], cmd)
