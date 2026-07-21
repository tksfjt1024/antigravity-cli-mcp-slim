# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/tksfjt1024/antigravity-cli-mcp-slim/releases/tag/v0.1.0
