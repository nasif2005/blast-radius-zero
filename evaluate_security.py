
"""Blast Radius Zero: reproducible sandbox security evaluation.

Usage:
    python evaluate_security.py
    python evaluate_security.py --repeat 3 --output security_results.csv

Requires sandbox_launcher_v3.py and Docker Desktop.
No third-party Python packages or Vultr API calls are required.
"""

import argparse
import csv
import json
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sandbox_launcher_v3 import run_sandbox


def scenarios():
    """Return controlled baseline and adversarial test cases."""

    return [
        {
            "name": "normal_execution",
            "category": "baseline",
            "code": "print(sum(range(1, 101)))",
            "expected": "normal",
        },
        {
            "name": "runtime_exception",
            "category": "baseline",
            "code": "print(10 / 0)",
            "expected": "exception",
        },
        {
            "name": "network_isolation",
            "category": "network",
            "code": (
                "import socket\n"
                "s = socket.socket()\n"
                "try:\n"
                "    s.settimeout(2)\n"
                "    s.connect(('1.1.1.1', 443))\n"
                "except OSError:\n"
                "    print('NETWORK_BLOCKED')\n"
                "else:\n"
                "    print('NETWORK_CONNECTED')\n"
                "finally:\n"
                "    s.close()\n"
            ),
            "expected": "network_blocked",
        },
        {
            "name": "readonly_filesystem",
            "category": "filesystem",
            "code": (
                "try:\n"
                "    with open('/sandbox_write_probe', 'w') as f:\n"
                "        f.write('test')\n"
                "except OSError:\n"
                "    print('WRITE_BLOCKED')\n"
                "else:\n"
                "    print('WRITE_ALLOWED')\n"
            ),
            "expected": "write_blocked",
        },
        {
            "name": "host_path_visibility",
            "category": "filesystem",
            "code": (
                "from pathlib import Path\n"
                "p = Path('/host_private_brz_probe')\n"
                "print('HOST_PATH_VISIBLE' if p.exists() "
                "else 'HOST_PATH_NOT_VISIBLE')\n"
            ),
            "expected": "host_not_visible",
        },
        {
            "name": "infinite_loop",
            "category": "resource",
            "code": "while True: pass",
            "expected": "timeout",
        },
        {
            "name": "memory_exhaustion",
            "category": "resource",
            "code": (
                "data = []\n"
                "while True:\n"
                "    data.append(bytearray(10 * 1024 * 1024))\n"
            ),
            "expected": "oom",
        },
        {
            "name": "stdout_flood",
            "category": "output",
            "code": (
                "import sys\n"
                "while True:\n"
                "    sys.stdout.write('A' * 8192)\n"
                "    sys.stdout.flush()\n"
            ),
            "expected": "output_limit",
        },
        {
            "name": "stderr_flood",
            "category": "output",
            "code": (
                "import sys\n"
                "while True:\n"
                "    sys.stderr.write('B' * 8192)\n"
                "    sys.stderr.flush()\n"
            ),
            "expected": "output_limit",
        },
        {
            "name": "combined_output_flood",
            "category": "output",
            "code": (
                "import sys\n"
                "while True:\n"
                "    sys.stdout.write('A' * 4096)\n"
                "    sys.stdout.flush()\n"
                "    sys.stderr.write('B' * 4096)\n"
                "    sys.stderr.flush()\n"
            ),
            "expected": "output_limit",
        },
    ]


def check_expected(expected, result):
    """Evaluate the specific security assertion for each scenario."""

    stdout = result.get("stdout") or ""
    stderr = result.get("stderr") or ""
    exit_code = result.get("exit_code")

    if result.get("busy"):
        return False, "Sandbox rejected evaluation as busy"

    if not result.get("cleanup_success"):
        return False, "Container cleanup failed"

    if expected == "normal":
        passed = (
            exit_code == 0
            and stdout.strip() == "5050"
            and not result.get("timed_out")
            and not result.get("output_limited")
        )
        return passed, "Normal program produced expected result"

    if expected == "exception":
        passed = (
            exit_code is not None
            and exit_code != 0
            and "ZeroDivisionError" in stderr
        )
        return passed, "Runtime exception captured"

    if expected == "network_blocked":
        passed = (
            exit_code == 0
            and "NETWORK_BLOCKED" in stdout
            and "NETWORK_CONNECTED" not in stdout
        )
        return passed, "Outbound connection blocked"

    if expected == "write_blocked":
        passed = (
            exit_code == 0
            and "WRITE_BLOCKED" in stdout
            and "WRITE_ALLOWED" not in stdout
        )
        return passed, "Root filesystem write blocked"

    if expected == "host_not_visible":
        passed = (
            exit_code == 0
            and "HOST_PATH_NOT_VISIBLE" in stdout
            and "HOST_PATH_VISIBLE" not in stdout
        )
        return passed, "Probe path not visible"

    if expected == "timeout":
        passed = bool(result.get("timed_out"))
        return passed, "Execution timeout enforced"

    if expected == "oom":
        passed = bool(result.get("oom_killed"))
        return passed, "Memory limit enforced"

    if expected == "output_limit":
        passed = bool(result.get("output_limited"))
        return passed, "Output limit enforced"

    return False, "Unknown expected outcome"


def verify_container_removed(container_name):
    """Check whether Docker can still inspect the container."""

    if not container_name:
        return False

    try:
        check = subprocess.run(
            ["docker", "container", "inspect", container_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return check.returncode != 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def run_evaluation(repeat):
    """Execute each scenario and collect structured results."""

    records = []
    cases = scenarios()

    total = len(cases) * repeat
    current = 0

    for repetition in range(1, repeat + 1):
        for scenario in cases:
            current += 1

            name = scenario["name"]

            print(
                f"[{current}/{total}] "
                f"{name} (run {repetition}) ... ",
                end="",
                flush=True,
            )

            try:
                result = run_sandbox(scenario["code"])
            except Exception as exc:
                result = {
                    "container": "",
                    "stdout": "",
                    "stderr": type(exc).__name__,
                    "exit_code": None,
                    "oom_killed": False,
                    "timed_out": False,
                    "output_limited": False,
                    "busy": False,
                    "duration": None,
                    "cleanup_success": False,
                }

            passed, explanation = check_expected(
                scenario["expected"],
                result,
            )

            removed = verify_container_removed(
                result.get("container")
            )

            passed = passed and removed

            if not removed:
                explanation += "; container removal unverified"

            record = {
                "timestamp_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
                "scenario": name,
                "category": scenario["category"],
                "repetition": repetition,
                "expected": scenario["expected"],
                "passed": passed,
                "explanation": explanation,
                "duration_seconds": result.get("duration"),
                "exit_code": result.get("exit_code"),
                "oom_killed": result.get("oom_killed"),
                "timed_out": result.get("timed_out"),
                "output_limited": result.get("output_limited"),
                "busy": result.get("busy"),
                "cleanup_success": result.get("cleanup_success"),
                "container_removed": removed,
                "stdout_bytes": len(
                    (result.get("stdout") or "").encode("utf-8")
                ),
                "stderr_bytes": len(
                    (result.get("stderr") or "").encode("utf-8")
                ),
            }

            records.append(record)

            print("PASS" if passed else "FAIL")

    return records


def save_csv(records, filename):
    """Write evaluation results to a CSV file."""

    if not records:
        return

    output = Path(filename)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(records[0].keys()),
        )
        writer.writeheader()
        writer.writerows(records)

    print(f"\nCSV report saved: {output.resolve()}")


def print_summary(records):
    """Print baseline and containment results separately."""

    total = len(records)
    passed = sum(bool(r["passed"]) for r in records)

    baseline = [
        r for r in records
        if r["category"] == "baseline"
    ]

    containment = [
        r for r in records
        if r["category"] != "baseline"
    ]

    baseline_passed = sum(
        bool(r["passed"]) for r in baseline
    )

    containment_passed = sum(
        bool(r["passed"]) for r in containment
    )

    durations = [
        float(r["duration_seconds"])
        for r in records
        if r["duration_seconds"] is not None
    ]

    print("\n" + "=" * 55)
    print("BLAST RADIUS ZERO — SECURITY EVALUATION")
    print("=" * 55)

    print(f"Total executions: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {total - passed}")

    if baseline:
        print(
            "Baseline correctness: "
            f"{baseline_passed}/{len(baseline)} "
            f"({100 * baseline_passed / len(baseline):.1f}%)"
        )

    if containment:
        print(
            "Observed containment checks: "
            f"{containment_passed}/{len(containment)} "
            f"({100 * containment_passed / len(containment):.1f}%)"
        )

    if durations:
        print(
            f"Mean execution duration: "
            f"{statistics.mean(durations):.3f} seconds"
        )
        print(
            f"Median execution duration: "
            f"{statistics.median(durations):.3f} seconds"
        )

    print("\nResults by category:")

    for category in sorted(set(r["category"] for r in records)):
        group = [
            r for r in records
            if r["category"] == category
        ]
        group_passed = sum(
            bool(r["passed"]) for r in group
        )

        print(
            f"  {category}: "
            f"{group_passed}/{len(group)} passed"
        )

    print("=" * 55)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate Blast Radius Zero sandbox controls"
    )

    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of repetitions per scenario",
    )

    parser.add_argument(
        "--output",
        default="security_results.csv",
        help="CSV output filename",
    )

    args = parser.parse_args()

    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    records = run_evaluation(args.repeat)

    save_csv(records, args.output)
    print_summary(records)

    if not all(r["passed"] for r in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
