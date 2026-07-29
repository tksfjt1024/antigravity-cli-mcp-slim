# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0]

### Changed
- Migrated to MCP Python SDK 2.x (`mcp>=2.0.0,<3`), lifting the `<2` ceiling that
  0.1.3 added as a stopgap. v1.x now receives only critical fixes, so staying on
  it meant riding a line that will stop getting security updates. The low-level
  `Server` is kept: the high-level `MCPServer` derives every tool schema from a
  Python function signature, and a wire parameter named `continue` cannot be
  reached that way — `Field(alias="continue")` advertises the right name but then
  fails the call with `unexpected keyword argument 'continue'`.
- **Requires `agy >= 1.1.8`.** The server now always passes `--output-format
  json`; older builds reject the flag. The response text is unchanged, but one
  metadata line is appended carrying `status`, `conversation_id` and
  `total_tokens`. `conversation_id` closes a gap: the `conversation` parameter
  advertised the reliable way to resume a run without giving callers any way to
  learn the id.
- A failed `agy` run, a rejected argument and a caught exception now come back as
  `isError` tool results rather than as successful calls whose text happens to
  start with `[ERROR]`.
- Dropped the OpenTelemetry middleware that SDK 2.x attaches by default, keeping
  the request path free of an observation layer that reads `OTEL_*` from the
  environment.

### Fixed
- Arguments are validated again. SDK 2.x advertises `inputSchema` but never
  applies it, so `server.py` now checks types and ranges itself. Without this,
  `"dangerously_skip_permissions": "false"` enabled
  `--dangerously-skip-permissions` (a non-empty string is truthy), and a string
  where `add_dir` or `extra_args` expects a list expanded into one flag per
  character.
- A `tools/call` that omits `arguments` entirely no longer raises: SDK 2.x passes
  `None` where v1's decorator substituted `{}`.

### Added
- CI runs Python 3.14, which is the only version where `mcp` 2.x selects
  `anyio>=4.10` and `starlette>=0.48.0`.

## [0.1.3]

### Fixed
- Bounded the `mcp` requirement to `>=1.0.0,<2`. MCP Python SDK 2.0.0 removed
  the low-level `Server.list_tools()` / `Server.call_tool()` decorators this
  server is built on, so any install that resolved the previously unbounded
  `mcp>=1.0.0` to 2.x died at import with `AttributeError: 'Server' object has
  no attribute 'list_tools'`. Environments already holding 1.x (through a
  lockfile or an existing virtualenv) kept working, which is why the failure
  surfaced only in fresh installs such as `uvx antigravity-cli-mcp-slim`.

## [0.1.2]

### Fixed
- On timeout, buffered stdout/stderr is now preserved instead of discarded.
  Previously the wrapper returned only `{"ok": false, "error": "timeout after
  Ns"}` with no output at all.
- On timeout, the subprocess's whole process group is now killed
  (`start_new_session=True` + `os.killpg`), not just the immediate child. This
  fixes descendants surviving the timeout, including the case where the
  process the wrapper launched has already exited (killpg now targets the pid
  directly instead of failing to `os.getpgid()` a leader that's already been
  reaped).
- Cancelling the underlying MCP request (or any caller cancellation) now
  reliably terminates the subprocess and its process group, instead of
  leaving it running.
- `_kill_process_group` now falls back to a plain `proc.kill()` on any
  `OSError` from `killpg`, not just `ProcessLookupError`/`PermissionError`;
  previously an unanticipated `OSError` subclass could skip the fallback
  entirely and crash the request handler.
- The wrapper's timeout is now bounded end-to-end (previously the final
  `proc.wait()` after a kill had no timeout and could block indefinitely on a
  subprocess stuck in an uninterruptible state).

### Changed
- The `Operating System :: OS Independent` classifier was replaced with
  `Operating System :: POSIX`: process-group cleanup on timeout relies on
  POSIX-only APIs (`start_new_session`, `os.killpg`) and degrades to
  best-effort (killing only the immediate process) on Windows.

## [0.1.1]

### Fixed
- `consult_agy` no longer returns a bare empty string when `agy` exits 0 but
  prints nothing on stdout. This happens when a headless run auto-denies a
  tool call that has no matching `permissions.allow` rule in `settings.json`
  (even `read_file` is denied this way by default) — the agent loop ends
  with nothing to print, but the process itself still exits 0. The result
  now surfaces `[WARNING]` plus `stderr`/`argv`/`cwd` instead, so callers can
  tell "nothing to report" from "agy couldn't work".
- The MCP server now reports its own package version via
  `importlib.metadata.version`, instead of whatever default the `mcp` SDK
  falls back to when no `version` is passed to `Server(...)`.

## [0.1.0]

### Added
- Initial release.
- MCP tool `consult_agy`: a single-tool, non-interactive wrapper around
  `agy --print` that runs the Antigravity CLI's agentic loop and returns the
  response on stdout.
- Typed parameters mirror the agy CLI flags one-to-one: `add_dir`
  (repeatable `--add-dir`), `dangerously_skip_permissions`, `sandbox`,
  `continue`, `conversation`, `print_timeout`. `continue` and `conversation`
  are mutually exclusive.
- Forward-compatible `extra_args` passthrough for new or uncommon agy flags.
- `$AGY_CMD` for swapping the agy binary path; `ANTIGRAVITY_CLI_MCP_SLIM_TIMEOUT`
  and `ANTIGRAVITY_CLI_MCP_SLIM_LOG_LEVEL` for wrapper configuration.
- Safe subprocess execution: argv-list form (no shell), explicit cwd validation,
  hard wall-clock timeout, `stdin=DEVNULL`, and full argv logged to stderr.
- Tests: `tests/test_basic.py` (argv construction, including the repeatable
  `--add-dir` invariant) and `tests/test_subprocess_stdin_isolation.py`
  (stdin DEVNULL invariant and a parallel smoke test).

[Unreleased]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/releases/tag/v0.1.0
