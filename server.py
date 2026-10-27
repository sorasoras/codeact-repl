"""MCP server: persistent Python interpreter for CodeAct-style agents.

Implements the CodeAct action space (arXiv:2402.01030): the agent writes
executable Python as its action, reads structured execution feedback
(stdout/stderr/traceback), and revises. State persists across calls in a
worker process, so multi-step tasks can carry variables forward.

Tools:
  - execute_code       -- run Python in the persistent namespace
  - inspect_namespace  -- list defined names with types and reprs
  - reset_session      -- clear the namespace and start fresh

The interpreter runs in a separate worker process (worker.py) spoken to over
a marker-framed line protocol: a timeout or hard crash (e.g. a native-code
segfault) cannot take down the MCP server itself. On timeout or crash the
worker is respawned, which loses the namespace; that is reported explicitly
in the result.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

_DEFAULT_TIMEOUT_S = 30.0
_MAX_TIMEOUT_S = 600.0
_MARK = "__CODEACT__"
_WORKER_PATH = Path(__file__).resolve().parent / "worker.py"

mcp = FastMCP("codeact-repl")


class CodeactSession:
    """Owns the worker process and speaks the request/response protocol."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._queue: queue.Queue | None = None
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._generation = 0
        self._spawn()

    def _spawn(self) -> None:
        self._stop()
        proc = subprocess.Popen(
            [sys.executable, str(_WORKER_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        q: queue.Queue = queue.Queue()
        threading.Thread(target=self._read_loop, args=(proc.stdout, q), daemon=True).start()
        threading.Thread(target=self._stderr_loop, args=(proc.stderr,), daemon=True).start()
        self._proc, self._queue = proc, q
        self._generation += 1

    def _read_loop(self, stream, q: queue.Queue) -> None:
        for line in stream:
            line = line.strip()
            if line.startswith(_MARK) and line.endswith(_MARK) and len(line) > 2 * len(_MARK):
                try:
                    q.put(json.loads(line[len(_MARK):-len(_MARK)]))
                except ValueError:
                    continue
        q.put(None)  # EOF: worker died

    def _stderr_loop(self, stream) -> None:
        for line in stream:
            self._stderr_tail.append(line.rstrip())

    def _stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except Exception:
                pass
        self._proc = None
        self._queue = None

    def _call(self, msg: dict, timeout: float) -> tuple[dict | None, str | None]:
        """Returns (reply, failure). failure is 'timeout' or 'crash'."""
        assert self._proc is not None and self._proc.stdin is not None and self._queue is not None
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self._spawn()
            return None, "crash"
        try:
            reply = self._queue.get(timeout=timeout)
        except queue.Empty:
            self._spawn()
            return None, "timeout"
        if reply is None:  # EOF sentinel from the reader thread
            self._spawn()
            return None, "crash"
        return reply, None

    def execute(self, code: str, timeout_s: float) -> dict:
        with self._lock:
            return self._execute_locked(code, timeout_s)

    def _execute_locked(self, code: str, timeout_s: float) -> dict:
        reply, failure = self._call({"op": "exec", "code": code}, timeout_s)
        if failure == "timeout":
            return {
                "status": "timeout",
                "error": {
                    "type": "TimeoutError",
                    "message": (
                        f"Execution exceeded {timeout_s:.0f}s and was killed. "
                        "The interpreter was reset to recover, so previously "
                        "defined variables are gone."
                    ),
                    "traceback": None,
                },
                "session_reset": True,
            }
        if failure == "crash":
            return {
                "status": "crash",
                "error": {
                    "type": "WorkerCrash",
                    "message": (
                        "The interpreter process died mid-execution (native-code "
                        "crash or kill). It was restarted; previously defined "
                        "variables are gone."
                    ),
                    "traceback": None,
                },
                "stderr_tail": list(self._stderr_tail),
                "session_reset": True,
            }
        assert reply is not None
        status = "error" if reply.get("error") else "ok"
        return {**reply, "status": status, "session_reset": False}

    def inspect(self) -> dict:
        with self._lock:
            reply, failure = self._call({"op": "inspect"}, 10.0)
            if failure or not reply:
                return {"status": "error", "error": f"interpreter unavailable ({failure})"}
            return {**reply, "status": "ok"}

    def reset(self) -> dict:
        with self._lock:
            self._spawn()
            return {"status": "ok", "message": "Namespace cleared; fresh interpreter started."}


# Lazy singleton: cheap to defer until the first tool call.
_session: CodeactSession | None = None
_session_lock = threading.Lock()


def _get_session() -> CodeactSession:
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = CodeactSession()
    return _session


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

@mcp.tool()
def execute_code(code: str, timeout_seconds: float = _DEFAULT_TIMEOUT_S) -> dict:
    """Run Python in the persistent interpreter and return execution feedback.

    State persists across calls: variables, imports and function definitions
    created here are visible to later execute_code calls. Use one call per
    action step; read the result, then revise and re-run if it errored.

    Args:
        code: Python source to execute. A trailing expression's value is
            captured (REPL semantics) and returned as `value`.
        timeout_seconds: Kill execution after this many seconds (default 30,
            max 600). On timeout the interpreter is reset and the namespace
            is lost.

    Returns a dict with:
        status: "ok" | "error" | "timeout" | "crash"
        stdout, stderr: captured output (each truncated to ~20k chars)
        value: repr of the trailing expression, if any
        error: {type, message, traceback} when status is not "ok" -- read the
            traceback, fix the code, and call execute_code again
        defined_names: variables newly created by this call
        session_reset: true if the interpreter had to be restarted (namespace lost)
    """
    timeout = max(1.0, min(float(timeout_seconds), _MAX_TIMEOUT_S))
    if not isinstance(code, str) or not code.strip():
        return {"status": "error", "error": {"type": "ValueError", "message": "code must be a non-empty string", "traceback": None}}
    return _get_session().execute(code, timeout)


@mcp.tool()
def inspect_namespace() -> dict:
    """List variables in the persistent interpreter: name, type and repr.

    Use between action steps to see what state is available before composing
    the next code action. Returns {names: {name: {type, repr}}, count}."""
    return _get_session().inspect()


@mcp.tool()
def reset_session() -> dict:
    """Clear the interpreter namespace and start a fresh process.

    Use between unrelated tasks, or after a timeout/crash left the state
    untrustworthy. All previously defined variables are discarded."""
    return _get_session().reset()


if __name__ == "__main__":
    mcp.run()
