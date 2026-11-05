"""Bounded Docker sandbox launcher for local Blast Radius Zero development.

Requires Docker CLI/daemon. This is defense in depth, not a hardened
multi-tenant untrusted-code isolation boundary.
"""
import json
import os
import subprocess
import threading
import time
import uuid

IMAGE = "python:3.11-slim"
TIMEOUT = 10
MAX_OUTPUT_BYTES = 64 * 1024  # Combined stdout + stderr
MAX_CONCURRENT = 2

# The semaphore applies to this Python process, not across Uvicorn workers.
_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT)


def _docker(args, timeout=5):
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          timeout=timeout, errors="replace")


def run_sandbox(code):
    """Execute Python code with bounded output and best-effort cleanup.

    Retains the original response fields and adds output_limited and busy.
    """
    start = time.perf_counter()
    name = f"sandbox-{uuid.uuid4().hex[:12]}"
    data = {
        "container": name, "stdout": "", "stderr": "", "exit_code": None,
        "oom_killed": None, "timed_out": False, "duration": None,
        "cleanup_success": False, "output_limited": False, "busy": False,
    }
    if not isinstance(code, str):
        data["stderr"] = "Code must be a string"
        data["duration"] = round(time.perf_counter() - start, 3)
        return data

    if not _SLOTS.acquire(blocking=False):
        data["busy"] = True
        data["stderr"] = "Sandbox capacity reached; retry later"
        data["duration"] = round(time.perf_counter() - start, 3)
        # No container was created, so cleanup is not applicable.
        return data

    process = None
    chunks = {"stdout": [], "stderr": []}
    sizes = {"stdout": 0, "stderr": 0}
    total = [0]
    lock = threading.Lock()
    over_limit = threading.Event()
    readers = []
    launched = False
    try:
        command = [
            "docker", "run", "--name", name, "--network", "none",
            "--memory", "128m", "--memory-swap", "128m",
            "--cpus", "0.5", "--pids-limit", "64", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "65534:65534", IMAGE, "python", "-B", "-c", code,
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        launched = True

        def read_bounded(stream, key):
            try:
                while True:
                    block = stream.read(4096)
                    if not block:
                        break
                    with lock:
                        remaining = max(0, MAX_OUTPUT_BYTES - total[0])
                        keep = block[:remaining]
                        if keep:
                            chunks[key].append(keep)
                            sizes[key] += len(keep)
                            total[0] += len(keep)
                        if len(block) > remaining:
                            over_limit.set()
            finally:
                stream.close()

        for key, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            thread = threading.Thread(target=read_bounded, args=(stream, key),
                                      daemon=True)
            thread.start()
            readers.append(thread)

        deadline = time.monotonic() + TIMEOUT
        while process.poll() is None:
            if over_limit.is_set():
                data["output_limited"] = True
                break
            if time.monotonic() >= deadline:
                data["timed_out"] = True
                break
            time.sleep(0.025)

        if data["timed_out"] or data["output_limited"]:
            try:
                _docker(["kill", name], timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            # Docker CLI can remain stuck even if the container has stopped.
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

        for thread in readers:
            thread.join(timeout=2)
        if over_limit.is_set():
            data["output_limited"] = True

        data["stdout"] = b"".join(chunks["stdout"]).decode("utf-8", errors="replace")
        data["stderr"] = b"".join(chunks["stderr"]).decode("utf-8", errors="replace")
        data["exit_code"] = process.returncode
        if data["timed_out"]:
            data["stderr"] += "\nExecution timed out"
        if data["output_limited"]:
            data["stderr"] += "\nOutput limit exceeded"

    except (OSError, subprocess.SubprocessError) as exc:
        data["stderr"] += f"\nSandbox launcher error: {type(exc).__name__}"
    finally:
        # Inspect before removal; the original Docker exit code and OOM flag
        # are more informative than the Docker CLI's own return code.
        if launched:
            try:
                state_result = _docker(["inspect", "--format", "{{json .State}}", name])
                if state_result.returncode == 0:
                    state = json.loads(state_result.stdout)
                    data["oom_killed"] = state.get("OOMKilled", False)
                    data["exit_code"] = state.get("ExitCode", data["exit_code"])
            except (OSError, subprocess.TimeoutExpired, ValueError):
                data["stderr"] += "\nContainer inspection unavailable"

            # Attempt removal twice; verify absence, rather than trusting only
            # the exit status of `docker rm`.
            for attempt in range(2):
                try:
                    _docker(["rm", "-f", name], timeout=10)
                    check = _docker(["container", "inspect", name], timeout=5)
                    if check.returncode != 0:
                        data["cleanup_success"] = True
                        break
                except (OSError, subprocess.TimeoutExpired):
                    pass
                if attempt == 0:
                    time.sleep(0.2)
            if not data["cleanup_success"]:
                data["stderr"] += "\nContainer cleanup could not be verified"

        if process is not None and process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        data["duration"] = round(time.perf_counter() - start, 3)
        _SLOTS.release()
    return data


if __name__ == "__main__":
    for label, code in {
        "Normal": "print('Hello from sandbox!')",
        "Runtime exception": "print(10 / 0)",
        "Timeout": "while True: pass",
    }.items():
        print(label, run_sandbox(code))
