"""Pure-function tests for argv construction. Subprocess execution is not tested here."""

from antigravity_cli_mcp_slim.server import AGY_CMD, _build_argv


def test_build_argv_minimal():
    argv = _build_argv(query="hello")
    assert argv == [AGY_CMD, "--print", "hello", "--output-format", "json"]


def test_build_argv_prompt_is_token_right_after_print():
    # Regression guard: the prompt must sit immediately after --print so agy
    # does not swallow a following flag as the prompt value. Observed failure mode:
    # `agy --print --output-format json "<prompt>"` exits 0 having answered the
    # question "what is --output-format" in plain text, so nothing looks wrong.
    argv = _build_argv(query="q", dangerously_skip_permissions=True)
    assert argv[:3] == [AGY_CMD, "--print", "q"]


def test_build_argv_requests_json_output():
    # The envelope is what lets the server tell "nothing to report" from "could not
    # work" and hand back a conversation_id.
    argv = _build_argv(query="q")
    assert argv[argv.index("--output-format") + 1] == "json"


def test_build_argv_extra_args_come_after_output_format():
    # extra_args is the documented escape hatch, so a caller that passes its own
    # --output-format has to win.
    argv = _build_argv(query="q", extra_args=["--output-format", "text"])
    assert argv[-2:] == ["--output-format", "text"]


def test_build_argv_add_dir_is_repeated_not_comma_joined():
    argv = _build_argv(query="q", add_dir=["/a", "/b", "/c"])
    assert argv.count("--add-dir") == 3
    for d in ("/a", "/b", "/c"):
        idx = argv.index(d)
        assert argv[idx - 1] == "--add-dir"
    # The comma-joined form must never appear.
    assert "/a,/b,/c" not in argv


def test_build_argv_dangerously_skip_permissions():
    argv = _build_argv(query="q", dangerously_skip_permissions=True)
    assert "--dangerously-skip-permissions" in argv


def test_build_argv_sandbox():
    argv = _build_argv(query="q", sandbox=True)
    assert "--sandbox" in argv


def test_build_argv_continue():
    argv = _build_argv(query="q", continue_=True)
    assert "--continue" in argv


def test_build_argv_conversation():
    argv = _build_argv(query="q", conversation="abc123")
    idx = argv.index("--conversation")
    assert argv[idx + 1] == "abc123"


def test_build_argv_conversation_wins_over_continue():
    # consult_agy rejects both at once, but if both reach _build_argv, the
    # explicit conversation id takes precedence over --continue.
    argv = _build_argv(query="q", continue_=True, conversation="abc123")
    assert "--conversation" in argv
    assert "--continue" not in argv


def test_build_argv_print_timeout():
    argv = _build_argv(query="q", print_timeout="10m0s")
    idx = argv.index("--print-timeout")
    assert argv[idx + 1] == "10m0s"


def test_build_argv_extra_args_appended_verbatim():
    argv = _build_argv(query="q", extra_args=["--log-file", "/tmp/agy.log"])
    assert argv[-2:] == ["--log-file", "/tmp/agy.log"]


def test_build_argv_all_typed_flags_combine():
    argv = _build_argv(
        query="q",
        add_dir=["/x"],
        dangerously_skip_permissions=True,
        sandbox=True,
        conversation="cid",
        print_timeout="5m0s",
        extra_args=["--custom"],
    )
    for token in (
        "--add-dir",
        "/x",
        "--dangerously-skip-permissions",
        "--sandbox",
        "--conversation",
        "cid",
        "--print-timeout",
        "5m0s",
        "--custom",
    ):
        assert token in argv
