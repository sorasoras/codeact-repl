# codeact-repl

Persistent Python interpreter exposed as MCP tools, implementing the CodeAct
action space ([arXiv:2402.01030](https://arxiv.org/abs/2402.01030)): the agent
writes executable Python as its action, observes structured execution
feedback, and revises. Variables, imports and definitions persist across tool
calls.

Ships with a companion agent skill (`skill/`) that defines the action loop:
compose one code block per step, execute, read the traceback, revise.

## Tools

- `execute_code(code, timeout_seconds=30)` — run Python in the persistent
  namespace; returns `status` (`ok`/`error`/`timeout`/`crash`), `stdout`,
  `stderr`, the repr of a trailing expression as `value`, `error`
  (`{type, message, traceback}`), `defined_names`, and `session_reset`.
- `inspect_namespace()` — list names with type and repr.
- `reset_session()` — clear the namespace and start a fresh worker.

## Design

Execution happens in `worker.py`, a separate process spoken to over a
marker-framed JSON line protocol (`__CODEACT__...__CODEACT__`). A timeout,
segfault or import failure in user code cannot take down the MCP server: the
worker is killed/respawned and the result reports `session_reset: true` with
a captured stderr tail. User code output is captured (never mixed into the
protocol) and stdin is an EOF stream during execution (`input()` is not
available).

REPL semantics: the value of a trailing expression is captured. Output is
truncated to ~20k chars per stream with head+tail preserved.

Why a subprocess instead of `multiprocessing`? On Windows, `multiprocessing`'s
spawn start method re-executes the parent's main module in the child, which
breaks (or recurses) depending on what the host module does. A plain worker
script with an explicit line protocol has no such constraint and works under
any host: script, `python -c`, or an MCP server.

## Layout

```
server.py        FastMCP tool surface + worker process management
worker.py        the interpreter: namespace, exec/inspect, line protocol
tests/smoke.py   session semantics (persistence, errors, timeout, reset)
tests/e2e_client.py  real MCP client over stdio
skill/           companion agent skill (CodeAct action loop)
```

## Setup

```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

Register as an MCP server (example for CLI-style configs; any MCP client
speaks the same stdio transport):

```json
"codeact-repl": {
  "command": "<absolute-path>-to-codeact-repl\\venv\\Scripts\\python.exe",
  "args": ["<absolute-path>-to-codeact-repl\\server.py"],
  "type": "stdio"
}
```

Install the skill by copying `skill/` to `~/.zcode/skills/codeact/` (or your
harness's skill directory).

## Tests

```
venv\Scripts\python.exe tests\smoke.py
venv\Scripts\python.exe tests\e2e_client.py
```

## Security note

`execute_code` runs arbitrary Python with the user's full local privileges —
no sandbox. It is an action channel for the agent, not a privilege escalation;
normal authorization rules apply to code actions exactly as to shell commands.

## License

MIT. See [LICENSE](LICENSE).
