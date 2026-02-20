import os
import shlex
import sys

import pytest

from bombshell import PipelineError, Process


class Script:
    @staticmethod
    def echo(text: str) -> Process:
        return Process(sys.executable, "-c", "import sys; print(sys.argv[1])", text)

    @staticmethod
    def echo_command(text: str) -> str:
        return shlex.join(Script.echo(text)._args)

    @staticmethod
    def false(error: int = 1) -> Process:
        return Process(sys.executable, "-c", f"import sys; sys.exit({error})")

    @staticmethod
    def true() -> Process:
        return Process(sys.executable, "-c", "import sys; sys.exit(0)")

    @staticmethod
    def grep(pattern: str) -> Process:
        cmd = """
import sys
pattern = sys.argv[1]
exit_code = 1
for line in sys.stdin:
    if pattern in line:
        sys.stdout.write(line)
        exit_code = 0

sys.exit(exit_code)
"""
        return Process(sys.executable, "-c", cmd.strip(), pattern)

    @staticmethod
    def cat() -> Process:
        return Process(sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())")

    @staticmethod
    def printenv(key: str) -> Process:
        return Process(sys.executable, "-c", "import os, sys; print(os.environ[sys.argv[1]])", key)


def test_basic_execution() -> None:
    res = Script.echo("hello").exec()
    assert res.stdout == "hello\n"
    assert res.exit_code == 0
    assert res.command == Script.echo_command("hello")


def test_basic_execution_check_passes() -> None:
    res = Script.echo("hello").exec()
    res.check(strict=False)
    res.check(strict=True)


def test_basic_executation_failure() -> None:
    res = Script.false().exec()
    assert res.stdout == ""
    assert res.exit_code == 1


def test_basic_execution_failure_check_fails() -> None:
    res = Script.false().exec()

    with pytest.raises(PipelineError, match="Pipeline exited with non-zero exit code"):
        res.check(strict=False)

    with pytest.raises(PipelineError, match="Pipeline exited with non-zero exit code"):
        res.check(strict=True)


def test_basic_pipeline() -> None:
    proc = Script.echo("hello1\nhello2")
    pipeline = proc | Script.grep("1")
    res = pipeline.exec()
    assert res.stdout == "hello1\n"
    assert res.exit_codes == (0, 0)
    assert res.exit_code == 0


def test_basic_pipeline_check_passes() -> None:
    pipeline = Script.echo("hello1\nhello2") | Script.grep("1")
    res = pipeline.exec()
    res.check(strict=False)
    res.check(strict=True)


def test_basic_pipeline_failure() -> None:
    pipeline = Script.echo("hello1\nhello2") | Script.grep("3")
    res = pipeline.exec()
    assert res.stdout == ""
    assert res.exit_codes == (0, 1)
    assert res.exit_code == 1


def test_basic_pipeline_failure_check_fails() -> None:
    pipeline = Script.echo("hello1\nhello2") | Script.grep("3")
    res = pipeline.exec()

    with pytest.raises(PipelineError, match="Pipeline exited with non-zero exit code"):
        res.check(strict=False)

    with pytest.raises(PipelineError, match="Pipeline exited with non-zero exit code"):
        res.check(strict=True)


def test_masked_pipeline_failure() -> None:
    pipeline = Script.false() | Script.true()
    res = pipeline.exec()
    assert res.stdout == ""
    assert res.exit_codes == (1, 0)
    assert res.exit_code == 0


def test_pipeline_string_representation() -> None:
    false = Script.false()
    true = Script.true()

    res = (false | true).exec()
    assert res.command == f"{shlex.join(false._args)} | {shlex.join(true._args)}"


def test_masked_pipeline_failure_passes_check_nonstrict() -> None:
    pipeline = Script.false() | Script.true()
    res = pipeline.exec()
    res.check(strict=False)


def test_masked_pipeline_failure_fails_check_strict() -> None:
    pipeline = Script.false() | Script.true()
    res = pipeline.exec()

    with pytest.raises(PipelineError, match="Pipeline exited with non-zero exit code"):
        res.check(strict=True)


def test_uncaptured_stdout() -> None:
    res = Script.echo("hello").exec(capture=False)
    assert res.stdout == ""
    assert res.exit_code == 0


def test_uncaptured_stderr() -> None:
    res = Script.echo("hello").exec(capture=False)
    assert res.stderr == ""
    assert res.exit_code == 0


def test_merged_stderr() -> None:
    cmd = (
        "import sys; "
        "sys.stdout.write(sys.argv[1]); sys.stdout.flush(); "
        "sys.stderr.write(sys.argv[2]); sys.stderr.flush(); "
        "sys.exit(0)"
    )
    res = Process(sys.executable, "-c", cmd, "hello\n", "goodbye\n").exec(merge_stderr=True)
    assert res.stdout == "hello\ngoodbye\n"
    assert res.stderr == ""
    assert res.exit_code == 0


def test_get_all_stderr_from_pipeline() -> None:
    p1 = Process(sys.executable, "-c", "import sys; sys.stderr.write('hello'); sys.exit(0)")
    p2 = Process(sys.executable, "-c", "import sys; sys.stderr.write('goodbye'); sys.exit(0)")
    res = (p1 | p2).exec()
    assert res.stdout == ""
    assert res.stderr == "hellogoodbye"
    assert res.exit_code == 0


def test_stdin() -> None:
    res = Script.cat().exec("hello")
    assert res.stdout == "hello"
    assert res.exit_code == 0


def test_5mb_stdin_without_deadlock() -> None:
    res = Script.cat().exec("hello" * 2**20)
    assert res.stdout == "hello" * 2**20
    assert res.exit_code == 0


def test_5mb_stdin_piped_without_deadlock() -> None:
    res = Script.cat().pipe(Script.grep("hello")).exec("hello\n" * 2**20)
    assert res.stdout == "hello\n" * 2**20
    assert res.exit_code == 0


def test_bytes_mode() -> None:
    res = Script.echo("hello").pipe(Script.cat()).exec(mode=bytes)
    assert res.stdout in (b"hello\n", b"hello\r\n")
    assert res.exit_code == 0


def test_environment_setting() -> None:
    res = Script.printenv("FOO").with_env(FOO="bar").exec()
    assert res.stdout == "bar\n"
    assert res.exit_code == 0


def test_command_chain() -> None:
    echo_1 = Script.echo("1")
    echo_2 = Script.echo("2")
    echo_3 = Script.echo("3")

    chain = echo_1.and_then(echo_2).and_then(echo_3)
    assert str(chain) == f"{Script.echo_command('1')} && {Script.echo_command('2')} && {Script.echo_command('3')}"

    res = chain.exec()
    assert res.stdout == "1\n2\n3\n"
    assert res.exit_code == 0


def test_failed_chain_stops() -> None:
    p1 = Script.echo("1")
    p2 = Script.false()
    p3 = Script.echo("3")

    chain = p1.and_then(p2).and_then(p3)
    res = chain.exec()
    assert res.stdout == "1\n"
    assert res.exit_code == 1
    assert res.exit_codes == (0, 1)


def test_multiple_environment_settings() -> None:
    p1 = Script.printenv("FOO").with_env(FOO="p1")
    p2 = Script.printenv("FOO").with_env(FOO="p2")
    p3 = Script.printenv("FOO").with_env(FOO="p3")

    res = p1.and_then(p2).and_then(p3).exec()
    assert res.stdout == "p1\np2\np3\n"
    assert res.exit_code == 0


@pytest.mark.skipif(os.name == "nt", reason="Windows doesn't handle SIGPIPE")
def test_sigpipe_exit_code() -> None:
    p1 = Process(
        sys.executable,
        "-c",
        #            v-- force Python to exit with SIGPIPE instead of 1 --v
        "import sys, signal; signal.signal(signal.SIGPIPE, signal.SIG_DFL); sys.stdout.write('a' * 1024 * 1024)",
    )  # write 1 MiB
    p2 = Process(sys.executable, "-c", "import sys; sys.stdout.write('b' * 1024 * 1024)")  # write 1 MiB, ignoring p1
    p3 = Script.cat()

    res = (p1 | p2 | p3).exec()
    assert res.exit_codes == (-13, 0, 0)  # -13/141 is SIGPIPE
    assert res.stdout == "b" * 1024 * 1024
