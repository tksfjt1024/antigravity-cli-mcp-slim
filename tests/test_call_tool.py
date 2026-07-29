"""Tests for tool dispatch, the hand-rolled argument validation, and result formatting.

The validation tests are not a migration artefact: v1's decorator ran jsonschema before
the handler was reached, and the suite called the undecorated function directly, so the
SDK's checking was never exercised here. v2 removed that layer entirely, which makes the
checks below the only thing standing between a client's argument and agy's argv.
"""

import json

from mcp.types import CallToolRequestParams

from antigravity_cli_mcp_slim.server import (
    _agy_trailer,
    _format_result,
    _parse_agy_json,
    consult_agy,
    on_call_tool,
    on_list_tools,
)


def _text(result):
    return result.content[0].text


async def test_continue_and_conversation_are_mutually_exclusive():
    result = await consult_agy(
        {"query": "q", "directory": ".", "continue": True, "conversation": "cid"}
    )
    assert "mutually exclusive" in _text(result)
    assert result.is_error is True


async def test_unknown_tool_name_is_reported():
    result = await on_call_tool(None, CallToolRequestParams(name="does_not_exist", arguments={}))
    assert "unknown tool" in _text(result)
    assert result.is_error is True


async def test_missing_arguments_key_does_not_raise():
    # v1's decorator normalised a missing `arguments` key to {}; v2 passes None through,
    # so the handler has to absorb it instead of raising TypeError at dict(None).
    result = await on_call_tool(None, CallToolRequestParams(name="consult_agy"))
    assert result.is_error is True
    assert "`query` is required" in _text(result)


async def test_missing_required_key_is_reported_not_raised():
    result = await consult_agy({"query": "q"})
    assert result.is_error is True
    assert "`directory` is required" in _text(result)


async def test_empty_query_is_rejected():
    result = await consult_agy({"query": "", "directory": "."})
    assert result.is_error is True
    assert "must not be empty" in _text(result)


async def test_string_false_does_not_enable_skip_permissions():
    # bool("false") is True. v1's jsonschema rejected the string for us; without this
    # check a client typo would auto-approve every tool permission agy asks for.
    result = await consult_agy(
        {"query": "q", "directory": ".", "dangerously_skip_permissions": "false"}
    )
    assert result.is_error is True
    assert "must be a boolean" in _text(result)


async def test_string_add_dir_is_rejected():
    # "docs" iterates character by character, which would become four --add-dir flags.
    result = await consult_agy({"query": "q", "directory": ".", "add_dir": "docs"})
    assert result.is_error is True
    assert "must be an array of strings" in _text(result)


async def test_string_extra_args_is_rejected():
    result = await consult_agy({"query": "q", "directory": ".", "extra_args": "--sandbox"})
    assert result.is_error is True
    assert "must be an array of strings" in _text(result)


async def test_timeout_out_of_range_is_rejected():
    result = await consult_agy({"query": "q", "directory": ".", "timeout_seconds": 5})
    assert result.is_error is True
    assert "between 30 and 3600" in _text(result)


async def test_timeout_true_is_rejected_even_though_bool_is_an_int():
    result = await consult_agy({"query": "q", "directory": ".", "timeout_seconds": True})
    assert result.is_error is True
    assert "must be an integer" in _text(result)


async def test_env_must_map_strings_to_strings():
    result = await consult_agy({"query": "q", "directory": ".", "env": {"A": 1}})
    assert result.is_error is True
    assert "`env` must be an object" in _text(result)


async def test_list_tools_returns_a_result_object_with_an_object_schema():
    # A ListToolsResult is required (v2 does not wrap a bare list), and the schema must
    # declare "type": "object" or the SDK drops the whole reply as an invalid result.
    result = await on_list_tools(None, None)
    assert [tool.name for tool in result.tools] == ["consult_agy"]
    assert result.tools[0].input_schema["type"] == "object"


def test_parse_agy_json_ignores_plain_text():
    assert _parse_agy_json("hello\n") is None
    assert _parse_agy_json("") is None
    assert _parse_agy_json('{"no_response_key": 1}') is None


def test_format_result_json_envelope_returns_response_plus_trailer():
    envelope = {
        "conversation_id": "cid-1",
        "status": "SUCCESS",
        "response": "the answer\n",
        "usage": {"total_tokens": 10001},
    }
    text = _format_result({"ok": True, "stdout": json.dumps(envelope)})
    assert text.startswith("the answer")
    assert "status=SUCCESS" in text
    assert "conversation_id=cid-1" in text
    assert "total_tokens=10001" in text


def test_format_result_json_envelope_with_empty_response_surfaces_status():
    # The case --output-format json exists to disambiguate: exit 0 with nothing to show.
    text = _format_result(
        {
            "ok": True,
            "stdout": json.dumps({"conversation_id": "cid-2", "status": "ERROR", "response": ""}),
            "stderr": "permission auto-denied",
            "argv": ["agy", "--print", "q"],
            "cwd": "/tmp",
        }
    )
    assert "[WARNING]" in text
    assert "status=ERROR" in text
    assert "conversation_id=cid-2" in text
    assert "permission auto-denied" in text


def test_agy_trailer_omits_absent_fields():
    assert _agy_trailer({"response": ""}) == "[agy] status=UNKNOWN"


def test_format_result_ok_returns_stdout_verbatim():
    # Plain text still passes through: a caller can override --output-format via extra_args.
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


def test_format_result_error_with_json_envelope_adds_the_trailer():
    text = _format_result(
        {
            "ok": False,
            "error": "boom",
            "stdout": json.dumps({"status": "ERROR", "response": "", "conversation_id": "cid-3"}),
        }
    )
    assert "status=ERROR" in text
    assert "conversation_id=cid-3" in text
