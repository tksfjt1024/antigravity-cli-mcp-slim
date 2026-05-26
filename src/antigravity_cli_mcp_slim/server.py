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
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = logging.getLogger("antigravity_cli_mcp_slim")

AGY_CMD = os.environ.get("AGY_CMD", "agy")
DEFAULT_TIMEOUT = int(os.environ.get("ANTIGRAVITY_CLI_MCP_SLIM_TIMEOUT", "660"))

server: Server = Server("antigravity-cli-mcp-slim")


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
    # other flag follows it.
    argv: list[str] = [AGY_CMD, "--print", query]
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
        )
    except OSError as exc:
        return {
            "ok": False,
            "error": f"failed to launch agy binary: {exc} (check $AGY_CMD)",
            "argv": argv,
        }

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(stdin_text.encode() if stdin_text else None),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        # The process may have exited between the timeout firing and this kill;
        # suppress the resulting race rather than crashing the request handler.
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        return {
            "ok": False,
            "error": f"timeout after {timeout}s",
            "argv": argv,
        }

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "argv": argv,
        "cwd": str(cwd_path),
    }


def _format_result(result: dict[str, Any]) -> str:
    if result["ok"]:
        return result["stdout"]
    parts = [f"[ERROR] {result.get('error', 'agy failed')}"]
    if "returncode" in result:
        parts.append(f"returncode={result['returncode']}")
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


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
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
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name != "consult_agy":
        return [TextContent(type="text", text=f"unknown tool: {name}")]

    args = dict(arguments)
    continue_ = bool(args.get("continue", False))
    conversation = args.get("conversation")
    if continue_ and conversation:
        return [
            TextContent(
                type="text",
                text="[ERROR] `continue` and `conversation` are mutually exclusive; pass only one.",
            )
        ]

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
    return [TextContent(type="text", text=_format_result(result))]


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
