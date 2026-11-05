"""antigravity_cli_mcp_slim: Thin, auditable MCP server wrapping the Antigravity CLI (agy).

Design goals:
  * Auditable: a single file with only one third-party dependency (`mcp`),
    readable end-to-end in one sitting.
  * Forward-compatible: any new agy CLI flag is reachable via `extra_args`
    without server changes; the binary itself can be swapped via $AGY_CMD.
  * Safe: subprocess uses argv-list form (no shell), explicit cwd, hard timeout,
    explicit env merge. Each invocation logs the exact argv to stderr.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

logger = logging.getLogger("antigravity_cli_mcp_slim")

AGY_CMD = os.environ.get("AGY_CMD", "agy")
DEFAULT_TIMEOUT = int(os.environ.get("ANTIGRAVITY_CLI_MCP_SLIM_TIMEOUT", "660"))

_PKG_NAME = "antigravity-cli-mcp-slim"
# The Server is built at the bottom of this file: v2 takes the handlers as constructor
# arguments, so they must already be defined by the time it is constructed.


def _build_argv(
    *,
    query: str,
    add_dir: list[str] | None = None,
    dangerously_skip_permissions: bool = False,
    sandbox: bool = False,
    continue_: bool = False,
    conversation: str | None = None,
    print_timeout: str | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    # The prompt must be the token immediately after --print. agy treats
    # --print as a string flag, so anything placed between --print and the
    # prompt would be swallowed as the prompt text. Keep `query` first; every
    # other flag follows it. Getting this wrong fails silently: `agy --print
    # --output-format json "<prompt>"` exits 0 having answered the question
    # "what is --output-format" in plain text.
    #
    # --output-format json (agy >= 1.1.8) is what lets this server tell "agy had
    # nothing to report" from "agy could not do its work" via the envelope's
    # `status`, and hand the caller a `conversation_id` it can pass back as
    # `conversation`. extra_args is appended last, so a caller can still override it.
    argv: list[str] = [AGY_CMD, "--print", query, "--output-format", "json"]
    for d in add_dir or []:
        argv += ["--add-dir", d]  # repeatable flag: one --add-dir per directory
    if dangerously_skip_permissions:
        argv.append("--dangerously-skip-permissions")
    if sandbox:
        argv.append("--sandbox")
    if conversation:
        argv += ["--conversation", conversation]
    elif continue_:
        argv.append("--continue")
    if print_timeout:
        argv += ["--print-timeout", print_timeout]
    if extra_args:
        argv += list(extra_args)
    return argv


async def _run_agy(
    *,
    cwd: str,
    argv: list[str],
    timeout: int,
    env_overrides: dict[str, str] | None = None,
    stdin_text: str | None = None,
) -> dict[str, Any]:
    cwd_path = Path(cwd).expanduser().resolve()
    if not cwd_path.is_dir():
        return {
            "ok": False,
            "error": f"directory does not exist: {cwd_path}",
            "argv": argv,
        }

    env = os.environ.copy()
    if env_overrides:
        env.update({k: str(v) for k, v in env_overrides.items()})

    logger.info("exec %s (cwd=%s, timeout=%ss)", argv, cwd_path, timeout)

    # stdin must NOT inherit the parent's stdin: when this server runs over the
    # stdio MCP transport, the parent's stdin is the JSON-RPC channel from the
    # MCP client. A child that reads from (or sets ioctl flags on) a shared
    # stdin file description can corrupt that channel. agy is a Go binary and
    # was not observed to do this, but DEVNULL is the safe default and also
    # stops agy from blocking on an interactive auth/permission prompt that can
    # never be answered in headless --print mode.
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd_path),
            stdin=asyncio.subprocess.PIPE if stdin_text is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            # own session, so timeout cleanup can kill the group (POSIX only, no-op elsewhere)
            start_new_session=True,
        )
    except OSError as exc:
        return {
            "ok": False,
            "error": f"failed to launch agy binary: {exc} (check $AGY_CMD)",
            "argv": argv,
        }

    # shield the task so a first-wait timeout doesn't cancel the second wait below
    communicate_task = asyncio.ensure_future(
        proc.communicate(stdin_text.encode() if stdin_text else None)
    )
    try:
        try:
            stdout, stderr = await asyncio.wait_for(
                asyncio.shield(communicate_task), timeout=timeout
            )
        except asyncio.TimeoutError:
            if communicate_task.done():
                # narrow race: the process finished at the exact moment wait_for's timeout fired
                stdout, stderr = await communicate_task
                return {
                    "ok": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace"),
                    "argv": argv,
                    "cwd": str(cwd_path),
                }
            _kill_process_group(proc)
            stdout, stderr = b"", b""
            with contextlib.suppress(asyncio.TimeoutError):
                # kill above closes the pipes, so communicate() reaches EOF with the buffered output
                stdout, stderr = await asyncio.wait_for(
                    asyncio.shield(communicate_task), timeout=10
                )
            # bounded backstop: a D-state descendant can't be force-killed, so don't block forever
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=10)
            return {
                "ok": False,
                "error": f"timeout after {timeout}s",
                "argv": argv,
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "cwd": str(cwd_path),
            }
    except asyncio.CancelledError:
        _kill_process_group(proc)
        raise
    finally:
        if not communicate_task.done():
            communicate_task.cancel()
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await communicate_task

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "argv": argv,
        "cwd": str(cwd_path),
    }


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Kill agy's process group; a descendant that setsid/setpgid away from it is out of reach."""
    if sys.platform != "win32":
        # start_new_session=True makes agy pid==pgid, so killpg(proc.pid) works after agy exits too
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
    # any killpg failure (not just the two anticipated OSError subclasses) must still fall back here
    with contextlib.suppress(OSError):
        proc.kill()


def _parse_agy_json(stdout: str) -> dict[str, Any] | None:
    """Return agy's --output-format json envelope, or None when stdout is not one.

    Returning None instead of raising keeps the plain-text path working for a caller that
    overrides --output-format through extra_args.
    """
    text = stdout.strip()
    if not text:
        return None
    try:
        envelope = json.loads(text)
    except ValueError:
        return None
    return envelope if isinstance(envelope, dict) and "response" in envelope else None


def _agy_trailer(envelope: dict[str, Any]) -> str:
    """One line of run metadata, appended under agy's own text.

    `conversation_id` is here because the tool advertises `conversation` as the reliable
    way to resume a run, yet before agy grew --output-format json a caller had no way to
    learn the id it was supposed to pass back.

    `error` is agy's own reason for a run that did not work — before agy 1.4.11 a
    `--print-timeout` hit returned `status=ERROR` with `error="timeout waiting for
    response"` (observed). Without it here the reason would survive only inside the raw
    stdout dump of the failure branch.

    `finished_reason` is how agy 1.4.11 and later say a turn did not run to its end
    (`print_timeout`, `interrupted` or `error`; absent when the turn finished normally).
    """
    bits = [f"status={envelope.get('status') or 'UNKNOWN'}"]
    error = envelope.get("error")
    if error:
        bits.append(f"error={error}")
    finished_reason = envelope.get("finished_reason")
    if finished_reason:
        bits.append(f"finished_reason={finished_reason}")
    conversation_id = envelope.get("conversation_id")
    if conversation_id:
        bits.append(f"conversation_id={conversation_id}")
    usage = envelope.get("usage")
    if isinstance(usage, dict) and usage.get("total_tokens") is not None:
        bits.append(f"total_tokens={usage['total_tokens']}")
    return "[agy] " + " ".join(bits)


def _run_failed(result: dict[str, Any]) -> bool:
    """Whether the client should see this as a failed tool call.

    A non-zero exit is always a failure. The envelope's `error` is consulted on top of
    that because it is agy's own verdict on the run rather than the shell's: a
    `--print-timeout` hit filled it before agy 1.4.11 (exiting 1) and fills it again on
    1.5.0 (exiting 3), so an exit-0 path that still carries an `error` would otherwise be
    handed back as a successful call whose failure shows up only in the text a human
    reads.

    The envelope's `error` counts only when `response` is empty. agy (observed on
    1.1.17) lets a mid-run tool error the model already recovered from linger in the
    envelope even though the agent loop ran to completion: the model misused
    `view_file`'s ContentOffset continuation, got "ContentOffset 70000 exceeds line
    range size 15820", recovered, and produced its full final answer — which the
    envelope carried in `response` next to that stale `error`. Marking such a run
    isError makes clients discard the answer; the trailer still shows `status` and
    `error`, so the lingering error stays visible without costing the response.

    `finished_reason` (added in agy 1.4.11) settles that ambiguity on agy 1.4.12, which
    exits 0 and returns whatever the model had written when a `--print-timeout` hit or a
    mid-turn error stops a turn early (observed: a `--print-timeout` hit comes back as
    `status=SUCCESS`, no `error`, an empty or partial `response` and
    `finished_reason=print_timeout`; a mid-turn safety-filter stop as `status=ERROR` with a
    3,680-character partial `response` and `finished_reason=error`). agy sets the field only
    for a turn that did not finish, so its presence fails the call regardless of
    `response`; the partial text still goes back in the result. agy 1.5.0 exits 3 on a
    `--print-timeout` hit instead (observed), which the exit-code check fails before the
    envelope is read. How a mid-turn error or an interruption exits on 1.5.0 is not
    known, so the `finished_reason` check stays.
    """
    if not result["ok"]:
        return True
    envelope = _parse_agy_json(result.get("stdout", ""))
    if envelope and envelope.get("finished_reason"):
        return True
    if not envelope or not envelope.get("error"):
        return False
    return not str(envelope.get("response") or "").strip()


def _format_result(result: dict[str, Any]) -> str:
    if result["ok"]:
        stdout = result.get("stdout", "")
        envelope = _parse_agy_json(stdout)
        if envelope is None:
            if stdout.strip():
                return stdout
            parts = [
                "[WARNING] agy exited successfully (returncode 0) but produced no stdout output."
            ]
        else:
            response = str(envelope.get("response") or "")
            finished_reason = envelope.get("finished_reason")
            if finished_reason:
                # _run_failed fails this call, so the text opens with [ERROR] like every
                # other failure; the partial answer stays below rather than being dropped.
                parts = [
                    f"[ERROR] agy did not finish the turn (finished_reason={finished_reason}).",
                    _agy_trailer(envelope),
                ]
                if response.strip():
                    parts.append(f"partial response:\n{response.rstrip()}")
            elif response.strip():
                return f"{response.rstrip()}\n\n{_agy_trailer(envelope)}"
            else:
                # agy exited 0 with an empty response. Without the envelope this was
                # indistinguishable from a run that could not work: a headless run that hits
                # an unapproved tool permission (no allow-rule in settings.json) gets
                # auto-denied and the agent loop ends with nothing to print, while the process
                # still exits 0. `status` in the trailer is what tells those two apart now.
                #
                # The marker follows the same envelope field _run_failed reads, so the text
                # does not open with [WARNING] on a result the client is being handed as
                # isError.
                marker = "[ERROR]" if envelope.get("error") else "[WARNING]"
                parts = [f"{marker} agy returned no response text.", _agy_trailer(envelope)]
        if result.get("stderr"):
            parts.append(f"stderr:\n{result['stderr']}")
        parts.append(f"argv: {result.get('argv')}")
        if result.get("cwd"):
            parts.append(f"cwd: {result['cwd']}")
        return "\n\n".join(parts)
    parts = [f"[ERROR] {result.get('error', 'agy failed')}"]
    if "returncode" in result:
        parts.append(f"returncode={result['returncode']}")
    failed_envelope = _parse_agy_json(result.get("stdout", ""))
    if failed_envelope is not None:
        parts.append(_agy_trailer(failed_envelope))
    if result.get("stderr"):
        parts.append(f"stderr:\n{result['stderr']}")
    if result.get("stdout"):
        parts.append(f"stdout:\n{result['stdout']}")
    parts.append(f"argv: {result.get('argv')}")
    if "cwd" in result:
        parts.append(f"cwd: {result['cwd']}")
    return "\n\n".join(parts)


_TOOL_PROPS: dict[str, Any] = {
    "query": {
        "type": "string",
        "minLength": 1,
        "description": (
            "Prompt sent verbatim to agy via --print. "
            "agy runs its full agentic loop and prints the response to stdout."
        ),
    },
    "directory": {
        "type": "string",
        "description": (
            "Working directory (agy cwd). Defines the default workspace root agy reads from."
        ),
    },
    "add_dir": {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "Extra workspace directories. Each entry maps to a separate agy --add-dir flag "
            "(repeatable, not comma-joined). Use to analyze multiple repositories in one call."
        ),
    },
    "dangerously_skip_permissions": {
        "type": "boolean",
        "description": (
            "Pass --dangerously-skip-permissions: auto-approve ALL tool permission requests "
            "without prompting, letting agy run commands and edit files unattended. "
            "Leave false (the default) unless you fully trust the prompt and workspace."
        ),
    },
    "sandbox": {
        "type": "boolean",
        "description": "Pass --sandbox: run agy with terminal restrictions enabled.",
    },
    "continue": {
        "type": "boolean",
        "description": (
            "Pass --continue: resume the most recent agy conversation. "
            "Mutually exclusive with `conversation`. Concurrent calls that set this race on "
            "the same 'most recent' conversation; prefer `conversation` for reliable resumption."
        ),
    },
    "conversation": {
        "type": "string",
        "description": (
            "Pass --conversation <ID>: resume a specific past conversation by id. "
            "Mutually exclusive with `continue`."
        ),
    },
    "print_timeout": {
        "type": "string",
        "description": (
            "Pass --print-timeout: agy's own wait timeout as a Go duration ('5m0s', '300s'). "
            "Keep it shorter than timeout_seconds so agy can exit cleanly before the "
            "wrapper kills it."
        ),
    },
    "extra_args": {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "Raw CLI flags appended verbatim (one token per element). "
            "Use to reach new or uncommon agy flags (e.g. --log-file) without updating this server."
        ),
    },
    "env": {
        "type": "object",
        "additionalProperties": {"type": "string"},
        "description": "Extra environment variables for the agy subprocess.",
    },
    "timeout_seconds": {
        "type": "integer",
        "minimum": 30,
        "maximum": 3600,
        "description": "Hard wall-clock timeout for the agy subprocess in seconds (default 660).",
    },
}


_TOOL = Tool(
    name="consult_agy",
    description=(
        "Run a single agy (Antigravity CLI) invocation in non-interactive print mode. "
        "agy is an agentic coding assistant that autonomously reads files and works inside "
        "`directory` (plus any `add_dir`). Forward-compatible: unknown CLI flags can be "
        "passed via `extra_args`. The agy binary path is configurable via $AGY_CMD."
    ),
    inputSchema={
        "type": "object",
        "properties": _TOOL_PROPS,
        "required": ["query", "directory"],
    },
)

_BOOL_FIELDS = ("dangerously_skip_permissions", "sandbox", "continue")
_STR_FIELDS = ("query", "directory", "conversation", "print_timeout")
_STR_ARRAY_FIELDS = ("add_dir", "extra_args")


def _validate_args(args: dict[str, Any]) -> str | None:
    """Return the first schema violation, or None when the arguments are usable.

    v1 ran jsonschema against `inputSchema` before the handler saw the arguments. v2's
    low-level Server advertises the schema and never applies it, so this walks the same
    eleven properties by hand. Checking only that the required keys are present is not
    enough: every value here reaches argv.
    """
    for key in ("query", "directory"):
        # `is None`, not `not in`: an explicit null passes the presence check but then
        # reaches Path(None) in _run_agy, where it surfaces as a TypeError the caller
        # cannot act on instead of as the schema violation it is.
        if args.get(key) is None:
            return f"`{key}` is required"
    for key in _STR_FIELDS:
        value = args.get(key)
        if value is not None and not isinstance(value, str):
            return f"`{key}` must be a string, got {type(value).__name__}"
    if not args["query"]:
        return "`query` must not be empty"
    for key in _BOOL_FIELDS:
        value = args.get(key)
        # An exact type check rather than truthiness: `bool("false")` is True, and for
        # dangerously_skip_permissions that would silently auto-approve every tool
        # permission request agy makes.
        if value is not None and not isinstance(value, bool):
            return f"`{key}` must be a boolean, got {type(value).__name__}"
    for key in _STR_ARRAY_FIELDS:
        value = args.get(key)
        if value is None:
            continue
        # A bare string satisfies `for d in add_dir` and `list(extra_args)` but iterates
        # character by character, so "docs" would expand into four --add-dir flags.
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return f"`{key}` must be an array of strings"
    env = args.get("env")
    if env is not None and (
        not isinstance(env, dict)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
    ):
        return "`env` must be an object mapping strings to strings"
    timeout = args.get("timeout_seconds")
    if timeout is not None:
        # bool subclasses int, so it has to be excluded before isinstance would accept it
        if isinstance(timeout, bool) or not isinstance(timeout, int):
            return f"`timeout_seconds` must be an integer, got {type(timeout).__name__}"
        if not 30 <= timeout <= 3600:
            return f"`timeout_seconds` must be between 30 and 3600, got {timeout}"
    return None


def _error_result(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=f"[ERROR] {text}")], is_error=True)


async def consult_agy(arguments: dict[str, Any] | None) -> CallToolResult:
    """The tool body, taking a plain dict so callers need no SDK request object."""
    # v1's decorator normalised a missing `arguments` key to {}; v2 hands the None through.
    args = dict(arguments or {})

    invalid = _validate_args(args)
    if invalid is not None:
        return _error_result(f"input validation: {invalid}")

    continue_ = bool(args.get("continue", False))
    conversation = args.get("conversation")
    if continue_ and conversation:
        return _error_result("`continue` and `conversation` are mutually exclusive; pass only one")

    argv = _build_argv(
        query=args["query"],
        add_dir=args.get("add_dir"),
        dangerously_skip_permissions=bool(args.get("dangerously_skip_permissions", False)),
        sandbox=bool(args.get("sandbox", False)),
        continue_=continue_,
        conversation=conversation,
        print_timeout=args.get("print_timeout"),
        extra_args=args.get("extra_args"),
    )

    result = await _run_agy(
        cwd=args["directory"],
        argv=argv,
        timeout=int(args.get("timeout_seconds") or DEFAULT_TIMEOUT),
        env_overrides=args.get("env"),
    )
    # v1 reported an agy failure as a successful tool call whose text merely started with
    # [ERROR]. is_error makes the failure legible to the client as a failed tool call.
    return CallToolResult(
        content=[TextContent(type="text", text=_format_result(result))],
        is_error=_run_failed(result),
    )


async def on_list_tools(
    ctx: ServerRequestContext, params: PaginatedRequestParams | None
) -> ListToolsResult:
    return ListToolsResult(tools=[_TOOL])


async def on_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    # v1's decorator turned handler exceptions into isError results. v2 has no such layer,
    # and an escaping exception becomes a JSON-RPC error, which clients treat as a transport
    # failure rather than as something to show the model. CancelledError derives from
    # BaseException, so peer cancellation still propagates and _run_agy's killpg still runs.
    try:
        if params.name != "consult_agy":
            return _error_result(f"unknown tool: {params.name}")
        return await consult_agy(params.arguments)
    except Exception as exc:
        logger.exception("consult_agy failed")
        return _error_result(f"{type(exc).__name__}: {exc}")


server: Server = Server(
    _PKG_NAME,
    version=_pkg_version(_PKG_NAME),
    on_list_tools=on_list_tools,
    on_call_tool=on_call_tool,
)
# v2 attaches an OpenTelemetryMiddleware by default. It is a no-op without an exporter, but
# it puts a tracing layer on the path of every request and reads OTEL_* environment
# variables in-process. This file is meant to be the whole story, so the layer is dropped
# rather than left implicit; delete this line to get the SDK default back.
server.middleware.clear()


async def _amain() -> None:
    logging.basicConfig(
        level=os.environ.get("ANTIGRAVITY_CLI_MCP_SLIM_LOG_LEVEL", "INFO"),
        format="[antigravity-cli-mcp-slim] %(levelname)s %(message)s",
    )
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
