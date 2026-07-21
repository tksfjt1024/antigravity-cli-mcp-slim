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


def test_format_result_ok_but_empty_stdout_surfaces_diagnostics():
    # Regression guard: agy can exit 0 with empty stdout (e.g. a tool call was
    # auto-denied for lacking a permissions.allow rule in headless mode). The
    # ok branch must not swallow that signal as a bare empty string.
    text = _format_result(
        {
            "ok": True,
            "returncode": 0,
            "stdout": "",
            "stderr": 'jetski: no output produced — a tool required the "read_file" '
            "permission that headless mode cannot prompt for, so it was auto-denied.",
            "argv": ["agy", "--print", "q"],
            "cwd": "/tmp",
        }
    )
    assert "[WARNING]" in text
    assert "auto-denied" in text
    assert "argv:" in text
    assert "cwd: /tmp" in text


def test_format_result_ok_with_whitespace_only_stdout_surfaces_diagnostics():
    assert "[WARNING]" in _format_result({"ok": True, "stdout": "   \n  "})


def test_format_result_ok_empty_stdout_missing_optional_keys_does_not_raise():
    # Mirrors the minimal-dict shape already used by
    # test_format_result_ok_returns_stdout_verbatim: only ok/stdout present.
    text = _format_result({"ok": True, "stdout": ""})
    assert "[WARNING]" in text
    assert "argv: None" in text


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
