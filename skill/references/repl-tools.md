# codeact-repl tool reference

Server: `~/.zcode/mcp-servers/codeact-repl/` (registered as `codeact-repl` in
`~/.zcode/cli/config.json`). Persistent Python interpreter; state survives across
calls in a worker process isolated from the MCP server.

## Tools

### `execute_code(code, timeout_seconds=30)`

Runs Python in the persistent namespace. REPL semantics: a trailing expression's
value is captured and returned as `value`. `timeout_seconds` clamps to 1–600.

Result schema:

| field | meaning |
|---|---|
| `status` | `ok` \| `error` \| `timeout` \| `crash` |
| `stdout`, `stderr` | captured output, each truncated to ~20k chars |
| `value` | repr of the trailing expression, if any |
| `error` | `{type, message, traceback}` when not ok — revise from this |
| `defined_names` | variables newly created by this call |
| `session_reset` | interpreter restarted (namespace lost) |

### `inspect_namespace()`

Returns `{names: {name: {type, repr}}, count}` — what state exists before you
compose the next block.

### `reset_session()`

Fresh interpreter, empty namespace. Use between unrelated tasks.

## Example action step

```python
import re
from pathlib import Path

errors = []
for path in Path("src").rglob("*.py"):
    text = path.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(r"except\s*:", line):
            errors.append(f"{path}:{i}: {line.strip()}")
print(f"{len(errors)} bare excepts")
for e in errors[:10]:
    print(e)
```

Then observe, and compose the fix as a second block against the same state
(`errors` is still defined), rather than re-scanning.

## Practical limits

- Code runs with user privileges and no sandbox. Authorization rules follow the
  task, exactly as for Bash — this is an action channel, not a privilege escalation.
- Hung code is killed at `timeout_seconds` and the namespace is wiped with it.
  For work that may exceed 10 minutes, write a script file and run it detached
  via Bash instead of holding the interpreter.
- Native crashes (segfaults in C extensions) return `status: crash` and respawn
  the interpreter; re-establish state afterwards.
- Output over ~20k chars is truncated with head+tail. Ask for summaries in code
  (`print(df.head())`, aggregations) instead of raw dumps.
