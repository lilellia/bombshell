from pathlib import Path
import sys

from bombshell import Process


class Script:
    @staticmethod
    def echo(text: str) -> Process:
        return Process(sys.executable, "-c", "import sys; print(sys.argv[1])", text)

    @staticmethod
    def printenv(key: str) -> Process:
        return Process(sys.executable, "-c", "import os, sys; print(os.environ[sys.argv[1]])", key)

    @staticmethod
    def pwd() -> Process:
        return Process(sys.executable, "-c", "import os; print(os.getcwd())")


def test_process_env() -> None:
    res = Script.printenv("FOO").with_env(FOO="bar").exec()
    assert res.stdout == "bar\n"


def test_process_cwd() -> None:
    res = Script.pwd().with_cwd(".").exec()
    assert res.stdout == f"{Path.cwd()}\n"


def test_pipeline_env() -> None:
    pipeline = (Script.printenv("FOO") | Script.printenv("BAR")).with_env(FOO="bar", BAR="baz")
    assert pipeline.processes[0].exec().stdout == "bar\n"
    assert pipeline.processes[1].exec().stdout == "baz\n"


def test_pipeline_cwd() -> None:
    pipeline = (Script.pwd() | Script.pwd()).with_cwd(".")
    assert pipeline.processes[0].exec().stdout == f"{Path.cwd()}\n"
    assert pipeline.processes[1].exec().stdout == f"{Path.cwd()}\n"


def test_command_chain_env() -> None:
    chain = Script.printenv("FOO").and_then(Script.printenv("BAR")).with_env(FOO="bar", BAR="baz")
    assert chain.exec().stdout == "bar\nbaz\n"


def test_command_chain_cwd() -> None:
    chain = Script.pwd().and_then(Script.pwd()).with_cwd(".")
    assert chain.exec().stdout == f"{Path.cwd()}\n{Path.cwd()}\n"
