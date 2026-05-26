"""Tests for call_tool dispatch/validation and _format_result formatting."""

from antigravity_cli_mcp_slim.server import _format_result, call_tool


async def test_continue_and_conversation_are_mutually_exclusive():
    result = await call_tool(
        "consult_agy",
        {"query": "q", "directory": ".", "continue": True, "conversation": "cid"},
    )
    assert "mutually exclusive" in result[0].text


async def test_unknown_tool_name_is_reported():
    result = await call_tool("does_not_exist", {})
    assert "unknown tool" in result[0].text


def test_format_result_ok_returns_stdout_verbatim():
    assert _format_result({"ok": True, "stdout": "hello\n"}) == "hello\n"


def test_format_result_error_includes_diagnostics_and_partial_stdout():
    text = _format_result(
        {
            "ok": False,
            "error": "boom",
            "returncode": 2,
            "stderr": "err line",
            "stdout": "partial output",
            "argv": ["agy", "--print", "q"],
            "cwd": "/tmp",
        }
    )
    assert "[ERROR] boom" in text
    assert "returncode=2" in text
    assert "stderr:\nerr line" in text
    assert "stdout:\npartial output" in text
    assert "argv:" in text
    assert "cwd: /tmp" in text
