import pytest

from bombshell import PipelineError, Process


def test_basic_execution() -> None:
    res = Process("echo", "hello").exec()
    assert res.stdout == "hello\n"
    assert res.exit_code == 0
    assert res.command == "echo hello"


def test_basic_execution_check_passes() -> None:
    res = Process("echo", "hello").exec()
    res.check(strict=False)
    res.check(strict=True)


def test_basic_executation_failure() -> None:
    res = Process("false").exec()
    assert res.stdout == ""
    assert res.exit_code != 0


def test_basic_execution_failure_check_fails() -> None:
    res = Process("false").exec()

    with pytest.raises(PipelineError, match="Pipeline exited with non-zero exit code"):
        res.check(strict=False)

    with pytest.raises(PipelineError, match="Pipeline exited with non-zero exit code"):
        res.check(strict=True)


def test_basic_pipeline() -> None:
    pipeline = Process("echo", "hello1\nhello2") | Process("grep", "1")
    res = pipeline.exec()
    assert res.stdout == "hello1\n"
    assert res.exit_codes == [0, 0]
    assert res.exit_code == 0
    assert res.command == "echo 'hello1\nhello2' | grep 1"


def test_basic_pipeline_check_passes() -> None:
    pipeline = Process("echo", "hello1\nhello2") | Process("grep", "1")
    res = pipeline.exec()
    res.check(strict=False)
    res.check(strict=True)


def test_basic_pipeline_failure() -> None:
    pipeline = Process("echo", "hello1\nhello2") | Process("grep", "3")
    res = pipeline.exec()
    assert res.stdout == ""
    assert res.exit_codes == [0, 1]
    assert res.exit_code == 1


def test_basic_pipeline_failure_check_fails() -> None:
    pipeline = Process("echo", "hello1\nhello2") | Process("grep", "3")
    res = pipeline.exec()

    with pytest.raises(PipelineError, match="Pipeline exited with non-zero exit code"):
        res.check(strict=False)

    with pytest.raises(PipelineError, match="Pipeline exited with non-zero exit code"):
        res.check(strict=True)


def test_masked_pipeline_failure() -> None:
    pipeline = Process("false") | Process("true")
    res = pipeline.exec()
    assert res.stdout == ""
    assert res.exit_codes == [1, 0]
    assert res.exit_code == 0


def test_masked_pipeline_failure_passes_check_nonstrict() -> None:
    pipeline = Process("false") | Process("true")
    res = pipeline.exec()
    res.check(strict=False)


def test_masked_pipeline_failure_fails_check_strict() -> None:
    pipeline = Process("false") | Process("true")
    res = pipeline.exec()

    with pytest.raises(PipelineError, match="Pipeline exited with non-zero exit code"):
        res.check(strict=True)


def test_uncaptured_stdout() -> None:
    res = Process("echo", "hello").exec(capture=False)
    assert res.stdout == ""
    assert res.exit_code == 0


def test_uncaptured_stderr() -> None:
    res = Process("echo", "hello").exec(capture=False)
    assert res.stderr == ""
    assert res.exit_code == 0


def test_merged_stderr() -> None:
    res = Process("sh", "-c", """echo "hello"; echo "goodbye" >&2; exit 0""").exec(merge_stderr=True)
    assert res.stdout == "hello\ngoodbye\n"
    assert res.stderr == ""
    assert res.exit_code == 0


def test_get_all_stderr_from_pipeline() -> None:
    p1 = Process("python", "-c", "import sys; sys.stderr.write('hello'); sys.exit(0)")
    p2 = Process("python", "-c", "import sys; sys.stderr.write('goodbye'); sys.exit(0)")
    res = (p1 | p2).exec()
    assert res.stdout == ""
    assert res.stderr == "hellogoodbye"
    assert res.exit_code == 0


def test_stdin() -> None:
    res = Process("cat").exec("hello")
    assert res.stdout == "hello"
    assert res.exit_code == 0


def test_5mb_stdin_without_deadlock() -> None:
    res = Process("cat").exec("hello" * 2**20)
    assert res.stdout == "hello" * 2**20
    assert res.exit_code == 0


def test_5mb_stdin_piped_without_deadlock() -> None:
    res = Process("cat").pipe_into("grep", "hello").exec("hello\n" * 2**20)
    assert res.stdout == "hello\n" * 2**20
    assert res.exit_code == 0


def test_bytes_mode() -> None:
    res = Process("echo", "hello").pipe_into("cat").exec(mode=bytes)
    assert res.stdout == b"hello\n"
    assert res.exit_code == 0


def test_environment_setting() -> None:
    res = Process("python3", "-c", "import os; print(os.environ['FOO'])").with_env(FOO="bar").exec()
    assert res.stdout == "bar\n"
    assert res.exit_code == 0


def test_command_chain() -> None:
    chain = Process("echo", 1).then("echo", 2).then("echo", 3)
    assert str(chain) == "echo 1 && echo 2 && echo 3"

    res = chain.exec()
    assert res.stdout == "1\n2\n3\n"
    assert res.exit_code == 0


def test_failed_chain_stops() -> None:
    chain = Process("echo", 1).then("false").then("echo", 3)
    res = chain.exec()
    assert res.stdout == "1\n"
    assert res.exit_code == 1
    assert res.exit_codes == [0, 1]


def test_multiple_environment_settings() -> None:
    p1 = Process("python3", "-c", "import os; print(os.environ['FOO'])").with_env(FOO="p1")
    p2 = Process("python3", "-c", "import os; print(os.environ['FOO'])").with_env(FOO="p2")
    p3 = Process("python3", "-c", "import os; print(os.environ['FOO'])").with_env(FOO="p3")

    res = p1.then(p2).then(p3).exec()
    assert res.stdout == "p1\np2\np3\n"
    assert res.exit_code == 0
