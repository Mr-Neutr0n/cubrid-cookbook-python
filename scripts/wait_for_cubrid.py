"""Bound the existing in-container csql readiness probe and failure diagnostics."""

from __future__ import annotations

import argparse
import math
import shlex
import subprocess
import sys
import time


def positive_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number of seconds")
    return seconds


def wait_for_cubrid(
    compose: list[str], timeout: float, probe_timeout: float, interval: float
) -> int:
    deadline = time.monotonic() + timeout
    last_error = "No readiness response"
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            response = subprocess.run(
                [*compose, "exec", "-T", "cubrid", "csql", "-u", "dba", "testdb", "-c", "SELECT 1"],
                capture_output=True,
                text=True,
                timeout=min(probe_timeout, remaining),
                check=False,
            )
            if response.returncode == 0:
                print("CUBRID is ready: the in-container csql query passed.")
                return 0
            last_error = response.stderr.strip() or response.stdout.strip()
            last_error = last_error or f"Readiness command exited {response.returncode}"
        except subprocess.TimeoutExpired:
            last_error = "Readiness probe timed out"
        except OSError as error:
            last_error = str(error)
            break
        time.sleep(min(interval, max(0, deadline - time.monotonic())))

    print(f"CUBRID readiness failed within {timeout:g}s: {last_error}", file=sys.stderr)
    for arguments in (["ps"], ["logs", "--tail", "50", "cubrid"]):
        try:
            response = subprocess.run(
                [*compose, *arguments],
                capture_output=True,
                text=True,
                timeout=probe_timeout,
                check=False,
            )
            print(f"Compose {' '.join(arguments)} (exit {response.returncode}):", file=sys.stderr)
            print(response.stdout + response.stderr, file=sys.stderr)
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"Compose {' '.join(arguments)} diagnostics failed: {error}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose", default="docker compose")
    parser.add_argument("--timeout", type=positive_seconds, default=120)
    parser.add_argument("--probe-timeout", type=positive_seconds, default=5)
    parser.add_argument("--interval", type=positive_seconds, default=2)
    arguments = parser.parse_args()
    try:
        compose = shlex.split(arguments.compose)
    except ValueError as error:
        parser.error(str(error))
    if not compose:
        parser.error("--compose must name an executable")
    return wait_for_cubrid(compose, arguments.timeout, arguments.probe_timeout, arguments.interval)


if __name__ == "__main__":
    raise SystemExit(main())
