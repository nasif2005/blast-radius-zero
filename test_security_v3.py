"""Security regression suite for sandbox_launcher_v3.py.

Run: python -m unittest -v test_security_v3.py
Requires Docker Desktop running and python:3.11-slim image available.
"""
import subprocess
import threading
import unittest
import uuid
from unittest.mock import patch

import sandbox_launcher_v3 as sandbox


class SandboxSecurityTests(unittest.TestCase):
    def execute(self, code):
        result = sandbox.run_sandbox(code)
        self.assertFalse(result["busy"], result)
        self.assertTrue(result["cleanup_success"], result)
        check = subprocess.run(
            ["docker", "container", "inspect", result["container"]],
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(check.returncode, 0, "Container still exists")
        return result

    def test_01_normal_execution(self):
        r = self.execute('print("Hello from sandbox!")')
        self.assertEqual(r["exit_code"], 0, r)
        self.assertEqual(r["stdout"].strip(), "Hello from sandbox!")
        self.assertFalse(r["timed_out"])
        self.assertFalse(r["oom_killed"])
        self.assertFalse(r["output_limited"])

    def test_02_runtime_exception(self):
        r = self.execute("print(10 / 0)")
        self.assertNotEqual(r["exit_code"], 0, r)
        self.assertIn("ZeroDivisionError", r["stderr"])
        self.assertFalse(r["timed_out"])

    def test_03_timeout(self):
        r = self.execute("while True: pass")
        self.assertTrue(r["timed_out"], r)
        self.assertFalse(r["oom_killed"])

    def test_04_memory_limit(self):
        code = ("data = []\nwhile True:\n"
                "    data.append(bytearray(10 * 1024 * 1024))\n")
        r = self.execute(code)
        self.assertTrue(r["oom_killed"], r)
        self.assertFalse(r["timed_out"])

    def test_05_network_isolation(self):
        code = ("import socket\n"
                "s = socket.socket()\n"
                "try:\n"
                "    s.settimeout(2)\n"
                "    s.connect(('1.1.1.1', 443))\n"
                "except OSError as e:\n"
                "    print('NETWORK_BLOCKED', type(e).__name__)\n"
                "else:\n"
                "    print('NETWORK_CONNECTED')\n"
                "finally:\n"
                "    s.close()\n")
        r = self.execute(code)
        self.assertEqual(r["exit_code"], 0, r)
        self.assertIn("NETWORK_BLOCKED", r["stdout"])
        self.assertNotIn("NETWORK_CONNECTED", r["stdout"])

    def test_06_read_only_root(self):
        code = ("try:\n"
                "    open('/sandbox_write_probe', 'w').write('data')\n"
                "except OSError as e:\n"
                "    print('WRITE_BLOCKED', type(e).__name__)\n"
                "else:\n"
                "    print('WRITE_ALLOWED')\n")
        r = self.execute(code)
        self.assertEqual(r["exit_code"], 0, r)
        self.assertIn("WRITE_BLOCKED", r["stdout"])
        self.assertNotIn("WRITE_ALLOWED", r["stdout"])

    def test_07_host_path_not_mounted(self):
        path = '/host_private_' + uuid.uuid4().hex
        code = ("from pathlib import Path\n"
                f"print('HOST_PATH_VISIBLE' if Path({path!r}).exists() "
                "else 'HOST_PATH_NOT_VISIBLE')\n")
        r = self.execute(code)
        self.assertEqual(r["exit_code"], 0, r)
        self.assertIn("HOST_PATH_NOT_VISIBLE", r["stdout"])

    def test_08_container_cleanup(self):
        r = self.execute("print('cleanup probe')")
        self.assertEqual(r["exit_code"], 0, r)
        self.assertTrue(r["cleanup_success"])

    def test_09_stdout_flood_is_bounded(self):
        r = self.execute("import sys\nwhile True: sys.stdout.write('x' * 8192); sys.stdout.flush()")
        self.assertTrue(r["output_limited"], r)
        self.assertLessEqual(len(r["stdout"].encode()), sandbox.MAX_OUTPUT_BYTES)
        self.assertFalse(r["timed_out"], r)

    def test_10_stderr_flood_is_bounded(self):
        r = self.execute("import sys\nwhile True: sys.stderr.write('x' * 8192); sys.stderr.flush()")
        self.assertTrue(r["output_limited"], r)
        self.assertLessEqual(len(r["stderr"].encode()), sandbox.MAX_OUTPUT_BYTES + 100)

    def test_11_combined_output_is_bounded(self):
        code = ("import sys\nwhile True:\n"
                "    sys.stdout.write('x' * 4096); sys.stdout.flush()\n"
                "    sys.stderr.write('y' * 4096); sys.stderr.flush()")
        r = self.execute(code)
        self.assertTrue(r["output_limited"], r)
        # Diagnostic suffix is outside the captured output budget.
        self.assertLessEqual(len(r["stdout"].encode()) + len(r["stderr"].encode()),
                             sandbox.MAX_OUTPUT_BYTES + 100)

    def test_12_busy_rejection(self):
        # Hold the sole slot without needing a Docker container.
        with patch.object(sandbox, "_SLOTS", threading.BoundedSemaphore(1)):
            self.assertTrue(sandbox._SLOTS.acquire(blocking=False))
            try:
                r = sandbox.run_sandbox("print(1)")
                self.assertTrue(r["busy"], r)
                self.assertIsNone(r["exit_code"])
                self.assertFalse(r["cleanup_success"])
            finally:
                sandbox._SLOTS.release()


if __name__ == "__main__":
    unittest.main(verbosity=2)
