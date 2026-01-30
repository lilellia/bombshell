import sys
import time

import pytest

from bombshell import PipelineError, Process
from bombshell.wait import TIMEOUT_EXIT_CODE


class Script:
    @staticmethod
    def sleep(seconds: float) -> Process:
        return Process(sys.executable, "-c", f"import time; time.sleep({seconds})")

    @staticmethod
    def exit(ec: int) -> Process:
        return Process(sys.executable, "-c", f"import sys; sys.exit({ec})")


def test_basic_timeout() -> None:
    start_time = time.monotonic()
    res = Script.sleep(1).exec(timeout=0.1)
    elapsed = time.monotonic() - start_time

    assert res.exit_code == TIMEOUT_EXIT_CODE
    assert res.timed_out()
    assert elapsed < 1.0


def test_basic_timeout_check() -> None:
    res = Script.sleep(1).exec(timeout=0.1)
    assert res.timed_out()

    with pytest.raises(PipelineError, match="Pipeline exited with non-zero exit code"):
        res.check()


def test_pipeline_timeout_is_shared() -> None:
    p1 = Script.sleep(0.2)
    p2 = Script.sleep(0.2)

    res = (p1 | p2).exec(timeout=0.2)
    assert res.timed_out()


def test_chain_timeout_is_shared() -> None:
    p1 = Script.sleep(0.2)
    p2 = Script.sleep(0.2)

    res = p1.and_then(p2).exec(timeout=0.3)
    assert res.timed_out()


def natural_exit_124_is_not_timeout() -> None:
    res = Script.exit(TIMEOUT_EXIT_CODE).exec()
    assert res.exit_code == TIMEOUT_EXIT_CODE
    assert not res.timed_out()
