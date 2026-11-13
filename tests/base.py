"""Shared test helpers.

Boots a *fresh* ShopLocal server (subprocess) for each concrete test class,
so in-memory state (carts, stock, price history) never leaks between classes.
Within a class, tests are written to be order-independent where possible.

Uses only the Python standard library.
"""

import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PY = os.path.join(APP_DIR, "app.py")


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerTestCase(unittest.TestCase):
    """Base class that starts and stops a real server per test class."""

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        env = dict(os.environ, PORT=str(cls.port))
        cls.proc = subprocess.Popen(
            [sys.executable, APP_PY],
            env=env,
            cwd=APP_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        cls.base = f"http://127.0.0.1:{cls.port}"
        deadline = time.time() + 20
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                out = cls.proc.stdout.read().decode("utf-8", "replace")
                raise AssertionError(f"server exited before becoming ready:\n{out}")
            try:
                with urllib.request.urlopen(cls.base + "/api/health", timeout=1) as r:
                    if r.status == 200:
                        return
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        if cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
                cls.proc.wait(timeout=5)
        out = cls.proc.stdout.read().decode("utf-8", "replace") if cls.proc.stdout else ""
        if cls.proc.stdout:
            cls.proc.stdout.close()
        raise AssertionError(f"server did not become ready within 20s\n{out}")

    @classmethod
    def tearDownClass(cls):
        if cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
                cls.proc.wait(timeout=5)
        if cls.proc.stdout:
            try:
                cls.proc.stdout.close()
            except ValueError:
                pass

    # ------------------------------------------------------------- HTTP client
    def request(self, method, path, body=None):
        """Return (status, headers, raw_bytes) for a request against the server.

        `body` may be a dict/list (JSON-encoded), a str (sent verbatim), or None.
        HTTP error statuses (4xx/5xx) are returned, not raised.
        """
        url = self.base + path
        data, headers = None, {}
        if body is not None:
            if isinstance(body, (dict, list)):
                data = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            else:
                data = body.encode("utf-8") if isinstance(body, str) else body
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            payload = e.read()
            e.close()
            return e.code, dict(e.headers), payload

    def api(self, method, path, body=None):
        """Like request(), but JSON-decodes the body. Returns (status, parsed)."""
        status, _headers, payload = self.request(method, path, body)
        try:
            parsed = json.loads(payload) if payload else None
        except json.JSONDecodeError:
            parsed = None
        return status, parsed

    def raw_request(self, request_line):
        """Send a raw HTTP/1.0 request (paths are NOT normalized client-side).

        Returns (status_line, body_bytes). Used for path-traversal checks.
        """
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as s:
            s.sendall(request_line.encode("utf-8") + b"\r\n\r\n")
            buf = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        head, _, body = buf.partition(b"\r\n\r\n")
        status_line = head.split(b"\r\n", 1)[0].decode("utf-8", "replace")
        return status_line, body
