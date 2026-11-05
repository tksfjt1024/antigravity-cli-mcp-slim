# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- The README, AGENTS.md and the code comments now describe `agy` 1.5.0, which exits 3
  on a `--print-timeout` hit. Such a run comes back as `[ERROR] agy failed` with
  `returncode=3`; the `[agy]` metadata line still carries
  `finished_reason=print_timeout`, and any partial answer stays in the `response` field
  of the raw stdout JSON. The README also gives 1.5.0's `print_timeout` default, `0s`
  (wait until the turn completes). The behaviour of the server did not change.

## [0.2.2]

### Fixed
- A turn that `agy` did not finish is now reported as a failed (`isError`) call.
  Starting in `agy` 1.4.11, a turn that stops early (a `--print-timeout` hit, a
  mid-turn error, or an interruption) exits 0 and reports the cause in the envelope's
  new `finished_reason` field; on 1.4.12 a timed-out run even reports `status=SUCCESS`
  with no `error`. 0.2.1 returned such runs as successful calls, along with any
  partial answer, because a non-empty `response` overrode a lingering `error`. A run
  whose envelope carries `finished_reason` now fails regardless of `response`: the
  output starts with `[ERROR] agy did not finish the turn (finished_reason=…)`, and
  any partial answer is kept under `partial response:`.

### Added
- The `[agy]` metadata line now includes `finished_reason` when `agy` reports one.

## [0.2.1]

### Fixed
- A run that completed with a final answer is no longer reported as a failed
  (`isError`) call when agy leaves a recovered mid-run tool error in the envelope's
  `error` field. Observed on agy 1.1.17: the model misuses `view_file`'s
  `ContentOffset` continuation, gets an error such as `ContentOffset 70000 exceeds
  line range size 15820`, recovers, and finishes the run — and the envelope then
  carries both the full `response` and that stale `error`. The envelope's `error`
  now counts as the run's verdict only when `response` is empty; the `[agy]`
  trailer still carries `status` and `error`, so the lingering error stays visible.

## [0.2.0]

### Changed
- Migrated to MCP Python SDK 2.x (`mcp>=2.0.0,<3`), lifting the `<2` ceiling that
  0.1.3 added as a stopgap. v1.x now receives only critical fixes, so staying on
  it meant riding a line that will stop getting security updates. The low-level
  `Server` is kept: the high-level `MCPServer` derives every tool schema from a
  Python function signature, and a wire parameter named `continue` cannot be
  reached that way — `Field(alias="continue")` advertises the right name but then
  fails the call with `unexpected keyword argument 'continue'`.
- **Requires `agy >= 1.1.8`**, the release that documents and supports
  `--output-format json`, which the server now always passes. `agy`'s response text
  still comes back first (with trailing whitespace trimmed), followed by one metadata
  line carrying `status` plus whichever of `error`, `conversation_id` and
  `total_tokens` the run reported. `conversation_id` closes a gap: the `conversation`
  parameter advertised the reliable way to resume a run without giving callers any way
  to learn the id.
- A failed `agy` run, a rejected argument and a caught exception now come back as
  `isError` tool results rather than as successful calls whose text happens to
  start with `[ERROR]`. "Failed" follows `agy`'s own verdict as well as the exit
  code: an envelope carrying an `error` counts even on a zero exit.
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
- An explicit `null` for `query` or `directory` is reported as the missing required
  argument it is. It used to clear the presence check and reach `Path(None)`, coming
  back as a `TypeError` that told the caller nothing actionable.

### Added
- Pushing a `v*` tag now creates the GitHub release as well as uploading to PyPI.
  The body is this file's section for that version, and a tag whose version has no
  entry here fails before anything is uploaded: PyPI refuses a second upload of a
  version it already holds, so failing after the upload would leave a published
  version that cannot be released without a version bump.
- CI runs Python 3.14, which is the only version where `mcp` 2.x selects
  `anyio>=4.10` and `starlette>=0.48.0`; the Trove classifiers list it too.

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

[Unreleased]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/releases/tag/v0.1.0
