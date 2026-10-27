---
name: codeact
description: "Run multi-step work as executable Python actions with execution-feedback self-debugging (CodeAct, arXiv:2402.01030). Use for tasks composed of several operations — multi-file edits, data transformation, API/tool composition, scripting, anything with loops or intermediate state — when the user says 'use codeact', asks for code actions, or wants one script over many small tool calls. Not needed for single reads, quick questions, or one-shot edits."
---

# CodeAct — executable code actions

Source: *Executable Code Actions Elicit Better LLM Agents* (Wang et al., ICML 2024,
arXiv:2402.01030). Actions are executable Python, not JSON tool calls or prose. One
code block per action step, executed, observed, then revised from its feedback.

## The action loop

1. **Compose** — write ONE Python block that performs the whole step: loops,
   conditionals and helper functions live inside the block. Do not split a step
   into many tiny tool calls when code can compose them.
2. **Execute** — run it with `codeact-repl`'s `execute_code` (see
   `references/repl-tools.md`). Fall back to Bash + `python` when that server is
   unavailable or the step must outlive the interpreter (see below).
3. **Observe** — read the full result before acting again: `status`, `stdout`,
   `stderr`, `value`, and on error the whole `error.traceback`.
4. **Revise** — on error, diagnose from the traceback, rewrite the block, re-run.
   At most 3 self-debug attempts per step, then change approach or say what is
   blocking. Never claim success without a passing observation.
5. **Advance** — state persists in the interpreter; use `defined_names` and
   `inspect_namespace` to compose the next step against what exists.

Keep facts that must survive interruption or compaction in the task ledger per
`j-space`; the interpreter namespace is convenience state, not a record.

## Choosing the action space

- **Use code actions** for: multi-file changes, search-and-transform across files,
  data wrangling/analysis, calling several tools or services in one step, repeated
  operations a loop should drive, building intermediate state across steps.
- **Use direct tools** for: reading one or two files, a single small edit, questions
  answered by inspection, anything faster without a script. This skill changes how
  you act, not that judgment.

## State discipline

- One task per session: call `reset_session` when switching to unrelated work.
- A result with `session_reset: true` (timeout or crash) wiped the namespace —
  re-establish needed state explicitly in the next block.
- Long-running jobs (minutes+, training, builds, downloads) must NOT hold the
  interpreter: write a script file and run it detached via Bash, then poll. Use
  `timeout_seconds` up to 600 only for work you intend to wait on.
- Persist irreplaceable state (results to keep) to files, not just variables.

## Feedback-driven self-debug

Execution feedback is the point: the traceback shows the failing line in your own
code action, and the next action is a corrected whole-block rewrite, not a patch.
Prefer fixing what the error states before hypothesizing; if the same error
survives two revisions, the approach is wrong, not the line.

## Safety

Code actions run with the user's full local privileges — they are actions, not
explanations. The authorization rules of any other tool call apply unchanged:
exploratory, reversible, read-only work proceeds; deletion, overwrites, publishing,
or anything outward-facing still needs explicit user authorization. Do not use code
actions to bypass a permission a direct tool call would have required.
