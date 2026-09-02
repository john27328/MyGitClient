from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PER_TEST_TIMEOUT_SECONDS = 90


def _collected_node_ids() -> tuple[str, ...]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        print(completed.stdout, end="", file=sys.stderr)
        print(completed.stderr, end="", file=sys.stderr)
        raise RuntimeError("Pytest could not collect the test suite.")
    return tuple(
        line
        for line in completed.stdout.splitlines()
        if line.startswith(("tests/", "tests\\")) and "::" in line
    )


def main() -> int:
    report_directory = Path("test-results")
    report_directory.mkdir(exist_ok=True)

    for index, node_id in enumerate(_collected_node_ids(), start=1):
        report = report_directory / f"{index:03}.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--timeout=60",
            f"--junitxml={report}",
            node_id,
        ]
        print(f"\n=== {node_id} ===", flush=True)
        try:
            completed = subprocess.run(command, check=False, timeout=_PER_TEST_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            print(
                f"{node_id} exceeded the {_PER_TEST_TIMEOUT_SECONDS}-second process limit.",
                file=sys.stderr,
            )
            return 1
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
