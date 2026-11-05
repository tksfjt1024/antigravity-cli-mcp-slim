# antigravity-cli-mcp-slim

A thin, auditable [MCP](https://modelcontextprotocol.io) server wrapping the [Antigravity CLI](https://github.com/google-antigravity/antigravity-cli) (`agy`).

[![PyPI version](https://img.shields.io/pypi/v/antigravity-cli-mcp-slim.svg)](https://pypi.org/project/antigravity-cli-mcp-slim/)
[![Python versions](https://img.shields.io/pypi/pyversions/antigravity-cli-mcp-slim.svg)](https://pypi.org/project/antigravity-cli-mcp-slim/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/tksfjt1024/antigravity-cli-mcp-slim/actions/workflows/ci.yml/badge.svg)](https://github.com/tksfjt1024/antigravity-cli-mcp-slim/actions/workflows/ci.yml)

## Why

When you add an MCP server to your AI coding tool, every prompt and code snippet
you send flows through that wrapper. Most CLI-wrapping MCP servers are small,
individually maintained packages — and recent supply-chain incidents
(`xz-utils`, `postmark-mcp`, the npm `chalk`/`debug` compromise) show that
"small and useful" is not the same as "safe to trust blindly."

This project takes the opposite stance: instead of asking you to trust it, it
tries to be **easy to audit**.

- **Single file** — the whole server is `src/antigravity_cli_mcp_slim/server.py`,
  readable end-to-end in one sitting
- **One third-party dependency** (`mcp`) — minimal supply-chain surface
- **Faithful CLI mapping** — every typed parameter mirrors a real `agy` flag by
  name, so it is obvious which flags an invocation actually sets
- **Forward-compatible** — any new or uncommon `agy` flag is reachable via
  `extra_args` without touching this server
- **Configurable binary path** — `$AGY_CMD` lets you swap or wrap the `agy` binary
- **Transparent** — every invocation logs the exact argv to stderr

Read `server.py` before you install. That is the point.

## Prerequisites

- The `agy` CLI, **version 1.1.8 or newer**, installed and on `$PATH` (or pointed
  to via `$AGY_CMD`). See the
  [official Antigravity CLI repository](https://github.com/google-antigravity/antigravity-cli)
  and [install docs](https://antigravity.google/docs/cli-overview).
  This server always passes `--output-format json`, and 1.1.8 is the first release
  to document and support that flag.
- `agy` already **authenticated** — this wrapper does not manage login; it
  surfaces `agy`'s own error output if the CLI is not ready.

## Installation

```bash
# Run directly without installing
uvx antigravity-cli-mcp-slim

# Install from PyPI
pip install antigravity-cli-mcp-slim

# Run from GitHub HEAD
uvx --from git+https://github.com/tksfjt1024/antigravity-cli-mcp-slim antigravity-cli-mcp-slim
```

## Usage as an MCP server

### Claude Code

```bash
claude mcp add antigravity-cli uvx antigravity-cli-mcp-slim
```

Or manually in `~/.claude.json`:

```json
{
  "mcpServers": {
    "antigravity-cli": {
      "type": "stdio",
      "command": "uvx",
      "args": ["antigravity-cli-mcp-slim"]
    }
  }
}
```

If `agy` is not on the launching process's `$PATH`, point `$AGY_CMD` at it:

```json
{
  "mcpServers": {
    "antigravity-cli": {
      "type": "stdio",
      "command": "uvx",
      "args": ["antigravity-cli-mcp-slim"],
      "env": { "AGY_CMD": "/absolute/path/to/agy" }
    }
  }
}
```

### Other MCP clients

Any MCP-compatible client can launch the server via stdio:

```bash
uvx antigravity-cli-mcp-slim
```

## Tool: `consult_agy`

Runs a single `agy` invocation in non-interactive print mode (`agy --print`).
`agy` is an agentic assistant: it autonomously reads files in `directory`
(and any `add_dir`) to fulfill the request, then prints the response.

The tool returns `agy`'s response text followed by one metadata line:

```
[agy] status=SUCCESS conversation_id=133cb55a-5128-463a-835c-b8362519876f total_tokens=18035
```

`status` is whatever `agy` reported for the run and is always present; the other fields
appear only when the run produced them. The values shown here are examples, not the full
set `agy` can return. A run `agy` itself calls failed also carries its reason in `error`,
and the tool result is flagged `isError` instead of coming back as a successful call:

```
[agy] status=ERROR error=timeout waiting for response conversation_id=a35d1505-804e-4159-9c76-ea2ff821c290
```

Starting in `agy` 1.4.11, a turn that stops early (a `print_timeout` hit, an error, or
an interruption) records the cause in `finished_reason`. The tool result for such a
turn is flagged `isError`, even when `agy` reports `status=SUCCESS` or returns a
partial answer, and `finished_reason` on the metadata line is what tells a timeout
apart from other failures. How the output starts depends on `agy`'s exit code:

- When `agy` exits 0, the output starts with
  `[ERROR] agy did not finish the turn (finished_reason=…)`, followed by the metadata
  line and, if present, the partial answer under `partial response:`. On `agy` 1.4.12,
  a `print_timeout` hit and a mid-turn error both exited 0.
- When `agy` exits non-zero, the output starts with an `[ERROR] agy failed` line and a
  `returncode=…` line, followed by the metadata line, `agy`'s stderr and its raw
  stdout. A partial answer, if any, stays in the `response` field of the stdout JSON.
  Starting in `agy` 1.5.0, a `print_timeout` hit exits 3.

On a `print_timeout` hit, `agy`'s stderr can hold a line of its own that also starts
with `[agy]` (`[agy] print timeout after …`); the metadata line is the one before
`stderr:`.

Either way the metadata line carries `finished_reason`. A `print_timeout` hit on 1.4.12
(first line) and on 1.5.0 (second line):

```
[agy] status=SUCCESS finished_reason=print_timeout conversation_id=38132840-0311-4450-bc1f-ec153a925b98
[agy] status=ERROR error=print timeout after 3s with the turn still in progress; the response is partial finished_reason=print_timeout conversation_id=6226bd86-8cdd-42e7-bb29-5005ebcfa955 total_tokens=0
```

Pass the `conversation_id` from the metadata line back as `conversation` to resume the
same run.
Prefer it over `continue`, which races with any other invocation for whichever
conversation happens to be the most recent one.

| Parameter                       | Type     | Description                                                                                   |
| ------------------------------- | -------- | --------------------------------------------------------------------------------------------- |
| `query` (required)              | string   | Prompt sent verbatim to `agy --print`                                                         |
| `directory` (required)          | string   | Working directory (`agy` cwd); the default workspace root                                     |
| `add_dir`                       | string[] | Extra workspace directories; each maps to one `--add-dir` (repeatable, not comma-joined)      |
| `dangerously_skip_permissions`  | bool     | Pass `--dangerously-skip-permissions` (auto-approve all tool requests). See warning below     |
| `sandbox`                       | bool     | Pass `--sandbox` (terminal restrictions enabled)                                              |
| `continue`                      | bool     | Pass `--continue` (resume the most recent conversation). Mutually exclusive with `conversation` |
| `conversation`                  | string   | Pass `--conversation <ID>` (resume a specific conversation). Mutually exclusive with `continue` |
| `print_timeout`                 | string   | Pass `--print-timeout` (Go duration, e.g. `5m0s`). Keep shorter than `timeout_seconds`        |
| `extra_args`                    | string[] | Raw CLI flags appended verbatim. Use for new/uncommon `agy` flags                             |
| `env`                           | object   | Extra environment variables for the `agy` subprocess                                          |
| `timeout_seconds`               | int      | Hard wall-clock timeout for the subprocess (default 660)                                      |

### Security note: `dangerously_skip_permissions`

`dangerously_skip_permissions: true` passes `--dangerously-skip-permissions`,
which auto-approves **all** of `agy`'s tool permission requests — including
running shell commands and editing files — with no prompt. The parameter keeps
the `dangerously_` prefix on purpose: enable it only in a trusted, isolated
workspace where you fully trust the prompt. It defaults to `false`.

## Cross-repository analysis example

Analyze multiple repositories from a single invocation by adding directories to
the workspace:

```jsonc
{
  "name": "consult_agy",
  "arguments": {
    "query": "Compare the API surface of the main service with the clients that call it",
    "directory": "/path/to/main-service",
    "add_dir": [
      "/path/to/client-a",
      "/path/to/client-b"
    ]
  }
}
```

This launches `agy --print "..." --output-format json --add-dir /path/to/client-a --add-dir /path/to/client-b`,
giving the agent read access to all three workspaces in one session.

## Conversation continuity

`agy` can resume prior conversations. This wrapper exposes that directly and
stays stateless itself:

- `continue: true` resumes the most recent conversation. Because "most recent"
  is shared state, concurrent calls can race on it — prefer `conversation` when
  it matters.
- `conversation: "<ID>"` resumes a specific conversation by id.

The two are mutually exclusive; passing both returns an error.

## Timeout configuration

There are two independent timeouts:

- `print_timeout` — `agy`'s own wait timeout (Go duration; `agy` 1.5.0 defaults to
  `0s`, which waits until the turn completes).
- `timeout_seconds` — this wrapper's hard wall-clock limit (default 660).

Keep `timeout_seconds` longer than `print_timeout` so `agy` can finish or time
out cleanly before the wrapper force-kills the subprocess. When you raise
`print_timeout` for a long task, raise `timeout_seconds` to match. On `agy` 1.5.0,
without `print_timeout`, only `timeout_seconds` bounds the run.

On timeout, the wrapper kills the subprocess's whole process group and then
waits up to 20 additional seconds to collect any buffered output and reap the
process, so the effective wall-clock ceiling is `timeout_seconds + 20`.

## Forward-compatibility example

If a future `agy` release adds a new flag (say `--super-mode`), use it
immediately without updating this server:

```jsonc
{
  "name": "consult_agy",
  "arguments": {
    "query": "...",
    "directory": "...",
    "extra_args": ["--super-mode"]
  }
}
```

## Configuration

| Environment variable                  | Default | Purpose                                  |
| ------------------------------------- | ------- | ---------------------------------------- |
| `AGY_CMD`                             | `agy`   | Path to the `agy` CLI binary             |
| `ANTIGRAVITY_CLI_MCP_SLIM_TIMEOUT`    | `660`   | Default subprocess timeout in seconds    |
| `ANTIGRAVITY_CLI_MCP_SLIM_LOG_LEVEL`  | `INFO`  | Logging level for stderr diagnostics     |

## Development

```bash
# Install dev dependencies
pip install -e ".[test,dev]"

# Lint
ruff check .

# Test
pytest
```

## License

[MIT](./LICENSE) © tksfjt1024
