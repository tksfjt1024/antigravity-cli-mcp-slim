"""Regression tests for subprocess stdin isolation.

The MCP server runs over the stdio transport, where the parent's stdin is the
JSON-RPC channel from the MCP client. If the agy child process inherits that
stdin (stdin=None), a read or ioctl on the shared file description can corrupt
the JSON-RPC channel and silently kill the server. DEVNULL also stops agy from
blocking on an interactive auth/permission prompt in headless --print mode.
_run_agy must therefore always pass asyncio.subprocess.DEVNULL when no stdin
payload is provided.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from antigravity_cli_mcp_slim.server import _run_agy


def _make_proc_mock(*, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> AsyncMock:
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return proc


async def test_no_stdin_text_uses_devnull(tmp_path: Path) -> None:
    with patch(
        "antigravity_cli_mcp_slim.server.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.return_value = _make_proc_mock()
        await _run_agy(cwd=str(tmp_path), argv=["echo", "hi"], timeout=5)
    kwargs = mock_create.call_args.kwargs
    assert kwargs["stdin"] == asyncio.subprocess.DEVNULL


async def test_with_stdin_text_uses_pipe(tmp_path: Path) -> None:
    with patch(
        "antigravity_cli_mcp_slim.server.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.return_value = _make_proc_mock()
        await _run_agy(
            cwd=str(tmp_path),
            argv=["cat"],
            timeout=5,
            stdin_text="payload",
        )
    kwargs = mock_create.call_args.kwargs
    assert kwargs["stdin"] == asyncio.subprocess.PIPE


async def test_stdin_is_never_left_inheriting_parent(tmp_path: Path) -> None:
    # stdin=None lets the child inherit the parent's stdin FD. Under MCP stdio
    # transport this is the JSON-RPC channel and any read/ioctl from the child
    # corrupts it; this assertion guards against accidental regressions.
    with patch(
        "antigravity_cli_mcp_slim.server.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.return_value = _make_proc_mock()
        await _run_agy(cwd=str(tmp_path), argv=["echo"], timeout=5)
    assert mock_create.call_args.kwargs["stdin"] is not None


async def test_parallel_invocations_smoke(tmp_path: Path) -> None:
    # `agy` is not assumed to be installed in the test env; the current python
    # stands in to exercise _run_agy's subprocess orchestration.
    fake_argv = [sys.executable, "-c", "print('ok')"]
    results = await asyncio.gather(
        *[_run_agy(cwd=str(tmp_path), argv=fake_argv, timeout=15) for _ in range(3)]
    )
    for r in results:
        assert r["ok"], r
        assert "ok" in r["stdout"]
