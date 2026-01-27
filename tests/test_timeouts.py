import sys
import time

import pytest

from bombshell import PipelineError, Process


class Script:
    @staticmethod
    def sleep(seconds: float) -> Process:
        return Process(sys.executable, "-c", f"import time; time.sleep({seconds})")


def test_basic_timeout() -> None:
    start_time = time.monotonic()
    res = Script.sleep(1).exec(timeout=0.1)
    elapsed = time.monotonic() - start_time

    assert res.exit_code == 124
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
