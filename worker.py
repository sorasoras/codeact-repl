"""Worker process for codeact-repl: owns the persistent Python namespace.

Speaks a line protocol on stdin/stdout with the parent (server.py):
  request:  {"op": "exec", "code": "..."} | {"op": "inspect"} | {"op": "quit"}
  response: __CODEACT__{json}__CODEACT__

User code output is captured, never written to the protocol stream, and
stdin is redirected away during execution (interactive input() is not
available -- stdin carries the protocol). Lines without the marker are
ignored, so import-time noise cannot corrupt framing.
"""

from __future__ import annotations

import ast
import io
import json
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

_MAX_OUTPUT_CHARS = 20_000
_MAX_REPR_CHARS = 2_000
_MARK = "__CODEACT__"


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    half = limit // 2
    return text[:half] + f"\n... [truncated {len(text) - limit} chars] ...\n" + text[-half:], True


def _short_repr(value: Any) -> str:
    try:
        rep = repr(value)
    except Exception:
        rep = f"<unreprable {type(value).__name__}>"
    return _truncate(rep, _MAX_REPR_CHARS)[0]


def _exec_in_namespace(code: str, namespace: dict, counter: int) -> dict:
    """Execute code REPL-style; the value of a trailing expression is captured."""
    filename = f"<codeact:{counter}>"
    tree = ast.parse(code, filename=filename, mode="exec")
    before = set(namespace)

    trailing: ast.Expression | None = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        trailing = ast.Expression(tree.body[-1].value)
        tree.body = tree.body[:-1]

    if tree.body:
        exec(compile(tree, filename, "exec"), namespace)
    value = None
    has_value = False
    if trailing is not None:
        value = eval(compile(trailing, filename, "eval"), namespace)
        has_value = True

    defined = sorted(n for n in (set(namespace) - before) if not n.startswith("__"))
    return {"has_value": has_value, "value": value, "defined": defined}


def _handle_exec(code: str, namespace: dict, counter: int) -> dict:
    out, err = io.StringIO(), io.StringIO()
    error: dict | None = None
    exec_result: dict | None = None
    saved_stdin = sys.stdin
    sys.stdin = io.StringIO()  # stdin carries the protocol; input() sees EOF
    try:
        with redirect_stdout(out), redirect_stderr(err):
            exec_result = _exec_in_namespace(code, namespace, counter)
    except BaseException as exc:
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        sys.stdin = saved_stdin

    stdout, out_trunc = _truncate(out.getvalue(), _MAX_OUTPUT_CHARS)
    stderr, err_trunc = _truncate(err.getvalue(), _MAX_OUTPUT_CHARS)
    result: dict[str, Any] = {
        "stdout": stdout,
        "stderr": stderr,
        "output_truncated": out_trunc or err_trunc,
        "error": error,
    }
    if exec_result is not None:
        result["value"] = _short_repr(exec_result["value"]) if exec_result["has_value"] else None
        result["has_value"] = exec_result["has_value"]
        result["defined_names"] = exec_result["defined"]
    return result


def _handle_inspect(namespace: dict) -> dict:
    names = {}
    for name in sorted(namespace):
        if name.startswith("__"):
            continue
        try:
            value = namespace[name]
            names[name] = {"type": type(value).__name__, "repr": _short_repr(value)}
        except Exception as exc:
            names[name] = {"type": "?", "repr": f"<inspect failed: {exc}>"}
    return {"names": names, "count": len(names)}


def _emit(obj: dict) -> None:
    sys.stdout.write(_MARK + json.dumps(obj) + _MARK + "\n")
    sys.stdout.flush()


def main() -> None:
    namespace: dict[str, Any] = {"__name__": "__codeact_repl__"}
    counter = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        op = msg.get("op")
        if op == "quit":
            break
        try:
            if op == "exec":
                counter += 1
                reply = _handle_exec(msg.get("code", ""), namespace, counter)
                reply["ok"] = True
            elif op == "inspect":
                reply = _handle_inspect(namespace)
                reply["ok"] = True
            elif op == "ping":
                reply = {"ok": True}
            else:
                reply = {"ok": False, "error": f"unknown op {op!r}"}
        except BaseException:
            reply = {"ok": False, "error": traceback.format_exc()}
        _emit(reply)


if __name__ == "__main__":
    main()
