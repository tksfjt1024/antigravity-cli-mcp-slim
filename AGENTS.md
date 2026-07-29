# AGENTS.md — antigravity-cli-mcp-slim

This file gives AI coding agents (Claude Code, Codex, Cursor, and other tools
that speak MCP) the project-specific context required to work on this
repository. Claude Code reads it via `CLAUDE.md`, which is a one-line
`@AGENTS.md` import shim.

## What this project is

A **thin bridge** that exposes the Antigravity CLI (`agy`) to MCP clients
(Claude Code, Codex MCP, Cursor MCP, and other MCP-speaking tools).

- **Input**: one MCP tool, `consult_agy`
- **Output**: an argv-list subprocess invocation of the `agy` CLI in
  non-interactive print mode (`agy --print <query> ...`). The binary path is
  configurable via `$AGY_CMD`.

`agy` is an agentic coding assistant: given a workspace it autonomously reads
files and performs the requested task, printing the response to stdout. History
management, caching, and streaming are **deliberately not provided**. The
killer feature is cross-repository analysis via `directory` (cwd) + `add_dir`.

## Architectural decisions (load-bearing principles)

This project starts from "**don't blindly route your prompts and code through
someone else's wrapper**." Recent supply-chain incidents (`xz-utils` backdoor,
`postmark-mcp` typosquat, npm `chalk`/`debug` compromise) inform every design
choice; **default toward auditability**.

- **Auditable**: the core implementation is a single file
  (`src/antigravity_cli_mcp_slim/server.py`) that anyone can read end-to-end in
  one sitting. If a feature would meaningfully grow this size, prefer
  **dropping or omitting** the feature over splitting the file.
- **Minimum dependencies**: `[project].dependencies` in `pyproject.toml` is
  **`mcp` only**, bounded to `>=2.0.0,<3`. Adding a direct dependency expands
  supply-chain surface; always check whether the standard library can do the job
  first. The upper bound is load-bearing rather than cautious: MCP Python SDK
  2.0.0 dropped the low-level `Server.list_tools()` / `Server.call_tool()`
  decorators this server had been built on, so the unbounded `>=1.0.0` it shipped
  with let a fresh install resolve to 2.x and die at import. Raise it only in the
  same change that migrates to the next major API.
  Moving to 2.0.0 pulled `mcp-types`, `httpx2`, `opentelemetry-api` and
  `truststore` into the transitive set and dropped `httpx-sse`,
  `pydantic-settings` and `python-dotenv` (measured with `uv lock`).
  `jsonschema` stays a required dependency of `mcp` itself, which is why the
  argument checking in `server.py` is hand-written: declaring `jsonschema`
  directly would install nothing new, but it would spend the "direct
  dependencies are `mcp` only" rule on a job the standard library can do.
- **`agy >= 1.1.8`**: the server always passes `--output-format json`, which
  older builds reject as an unknown flag. The envelope is not a nicety — it
  carries the `status` that separates "agy had nothing to report" from "agy
  could not do its work", and the `conversation_id` a caller needs in order to
  use the `conversation` parameter the tool already advertised.
- **Faithful CLI mapping**: typed parameters mirror the actual `agy` flag names
  one-to-one (`add_dir` → `--add-dir`, `dangerously_skip_permissions` →
  `--dangerously-skip-permissions`, `continue` → `--continue`, `conversation` →
  `--conversation`, `sandbox` → `--sandbox`, `print_timeout` →
  `--print-timeout`). Do **not** soften or rename flags: the parameter surface
  should make it obvious which CLI flags an invocation actually sets. The
  `dangerously_` prefix is kept precisely because the danger should be visible.
- **Forward-compatible**: unknown / rare flags flow through
  `extra_args: string[]` verbatim. The server should not need to be re-released
  every time the upstream `agy` CLI grows a new flag.
- **Transparent**: every subprocess invocation logs its full argv to stderr
  (`logger.info("exec %s ...")`).
- **No shell**: always use `asyncio.create_subprocess_exec` with an argv list.
  `shell=True` and string-concatenated commands are forbidden.
- **Configurable binary**: keep `$AGY_CMD` working so users can swap or wrap the
  `agy` binary.

## Build / test / lint

`uv` is the local development driver (with `.venv/`); Docker is not used. CI
(`.github/workflows/ci.yml`) installs the same `optional-dependencies` groups
via `pip`, so local and CI use the same dependency set.

```bash
uv sync --extra test --extra dev      # local
pip install -e ".[test,dev]"          # mirrors CI
.venv/bin/pytest tests/ -v
.venv/bin/ruff check .
.venv/bin/ruff format .
```

**Required before commit**: `pytest` and `ruff check` both green. A type checker
(`mypy` / `pyright`) is intentionally not configured at this size — if you want
to add one, first verify it does not conflict with the "minimum dependencies"
principle.

## Release flow

The package is published to PyPI via Trusted Publishing
(`.github/workflows/publish.yml`), triggered by pushing a `v*` tag.

- The single source of truth for the version is `pyproject.toml`'s
  `[project].version`. Bump it in the same PR as the change.
- `src/antigravity_cli_mcp_slim/__init__.py` exposes `__version__` via
  `importlib.metadata`, so it follows `pyproject.toml` automatically.
- After merge: `git tag vX.Y.Z && git push origin vX.Y.Z`. The publish workflow
  picks it up.
- `CHANGELOG.md` follows Keep a Changelog; add a new entry per release.

## Common gotchas

### v2 dropped two jobs the `@server.call_tool()` decorator used to do

In v1 the decorator was not just registration. Outside the handler it ran
`jsonschema.validate` against the advertised `inputSchema`, and it converted any
handler exception into a `CallToolResult(isError=True)`. The low-level `Server`
in v2 does neither: the schema is advertised and never applied, and an escaping
exception becomes a JSON-RPC error, which clients treat as a transport failure
rather than as something to show the model.

Both are re-implemented in `server.py` (`_validate_args`, and the `except
Exception` in `on_call_tool`). Do not thin them out on the grounds that the
schema already says so — the schema is documentation to the SDK now. Checking
only that the required keys are present is specifically not enough: every value
reaches argv, `bool("false")` is `True`, and a string where a list belongs
iterates character by character.

The `except Exception` is deliberately not `except BaseException`:
`CancelledError` has to keep propagating so peer cancellation still reaches
`_run_agy`'s process-group kill.

### Keep the prompt as the token right after `--print`

`agy` treats `--print` / `--prompt` / `-p` as a string flag that takes the
prompt as its value. If a flag is placed between `--print` and the prompt, that
flag is swallowed as the prompt text. `_build_argv` therefore always emits
`[AGY_CMD, "--print", query, ...]` with `query` first and every other flag
after it. The regression test is in `tests/test_basic.py`.

### `--add-dir` is repeatable, not comma-joined

Each extra directory is passed as its own `--add-dir <dir>`. Do not join paths
with commas. `tests/test_basic.py` guards this.

### Never let the subprocess inherit the parent's stdin

When the server runs over the **MCP stdio transport**, the parent process's
stdin is the **JSON-RPC channel**. A child that reads from or sets ioctl flags
on a shared stdin file description can corrupt that channel and silently kill
the server. `agy` (a Go binary) was not observed to do this, but `_run_agy`
always passes `asyncio.subprocess.DEVNULL` when no stdin payload is provided.
DEVNULL also prevents `agy` from blocking on an interactive auth/permission
prompt that can never be answered in headless `--print` mode. Regression test:
`tests/test_subprocess_stdin_isolation.py`.

### Don't swallow `FileNotFoundError`

If `$AGY_CMD` points to an empty string or a non-existent path, return an error
dict (`ok: False`) that **includes the argv** so users can diagnose what was
attempted. Silently masking the exception removes any signal about why the tool
isn't working.

### `agy` must be authenticated

`agy` runs against an authenticated account. This wrapper does not manage auth;
it surfaces `agy`'s own error output on failure. Ensure `agy` is logged in
before relying on the tool.

### Treat "add a direct dependency" as a re-think trigger

Per the "minimum dependencies" principle above, anything beyond `mcp` should be
weighed against a few dozen lines of standard-library code first.

### Process-group kill uses `proc.pid` directly, not `os.getpgid(proc.pid)`

`start_new_session=True` makes the subprocess both the session and
process-group leader, so `proc.pid` **is** the pgid. `_kill_process_group`
calls `os.killpg(proc.pid, ...)` directly; calling `os.getpgid(proc.pid)`
first fails with `ProcessLookupError` once the leader has already
exited/been reaped, even if descendants in the same group are still alive
holding the stdout/stderr pipes open. A descendant that calls
`setsid()`/`setpgid()` to leave the group is out of reach either way — a
known limitation, not a bug to fix by walking the process tree.

### Don't delete the `communicate_task.done()` narrow-race check in `_run_agy`

If the subprocess finishes at (almost) the exact moment the first
`wait_for`'s timeout fires, `communicate_task` may already be done by the
time the `except asyncio.TimeoutError` handler runs. `_run_agy` checks this
before killing anything and reports the real result instead of a false
timeout. Regression test:
`test_narrow_race_reports_success_when_process_finishes_at_timeout_edge`.

## References

- Public docs: `README.md`
- License: `LICENSE` (MIT)
