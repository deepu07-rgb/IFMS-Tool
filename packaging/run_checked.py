"""Expose a bounded diagnostic annotation when a public CI command fails."""

import collections, subprocess, sys

label = sys.argv[1]
command = sys.argv[2:]
if command and command[0] == "--":
    command = command[1:]
lines = collections.deque(maxlen=45)
process = subprocess.Popen(
    command,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    errors="replace",
)
for line in process.stdout:
    print(line, end="", flush=True)
    lines.append(line)
code = process.wait()
if code:
    message = (
        "".join(lines)[-7000:]
        .replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )
    print(f"::error title={label}::{message}", flush=True)
sys.exit(code)
