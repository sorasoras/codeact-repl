"""Smoke tests for the CodeactSession worker protocol. Run:

    venv/Scripts/python.exe tests/smoke.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import CodeactSession  # noqa: E402


def main() -> None:
    s = CodeactSession()

    # 1. Basic execution + trailing-expression capture (REPL semantics)
    r = s.execute("x = 41\nx + 1", 30)
    assert r["status"] == "ok", r
    assert r["value"] == "42", r
    assert r["defined_names"] == ["x"], r

    # 2. Persistence across calls
    r = s.execute("x += 1\nprint('x is', x)", 30)
    assert r["status"] == "ok" and "x is 42" in r["stdout"], r
    assert r["defined_names"] == [], r

    # 3. Errors carry type/message/traceback, and state survives them
    r = s.execute("y = 1\n1 / 0", 30)
    assert r["status"] == "error", r
    assert r["error"]["type"] == "ZeroDivisionError", r
    assert "ZeroDivisionError" in r["error"]["traceback"], r
    r = s.execute("y", 30)
    assert r["status"] == "ok" and r["value"] == "1", r

    # 4. import-state persistence (json.dumps returns a str; value is its repr)
    r = s.execute("import json\njson.dumps({'a': 1})", 30)
    assert r["status"] == "ok" and r["value"] == '\'{"a": 1}\'', r

    # 4b. stderr capture
    r = s.execute("import sys\nprint('to stderr', file=sys.stderr)", 30)
    assert r["status"] == "ok" and "to stderr" in r["stderr"], r

    # 5. inspect_namespace
    names = s.inspect()["names"]
    assert {"x", "y", "json"} <= set(names), names
    assert names["x"]["type"] == "int", names

    # 6. Timeout kills the worker and resets the namespace
    r = s.execute("import time\ntime.sleep(30)", 2)
    assert r["status"] == "timeout" and r["session_reset"] is True, r
    r = s.execute("x", 30)
    assert r["status"] == "error" and r["error"]["type"] == "NameError", r

    # 7. Fresh state works after the reset
    r = s.execute("2 * 21", 30)
    assert r["status"] == "ok" and r["value"] == "42", r

    # 8. Explicit reset
    s.reset()
    r = s.execute("x", 30)
    assert r["status"] == "error" and r["error"]["type"] == "NameError", r

    print("all smoke tests passed")


if __name__ == "__main__":
    main()
