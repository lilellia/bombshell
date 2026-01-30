import os
import subprocess
import time
from typing import Any, NamedTuple

from .resources import ResourceData

TIMEOUT_EXIT_CODE = 124


class WaitResult(NamedTuple):
    exit_code: int
    resource_data: ResourceData
    timed_out: bool


def _wait4(process: subprocess.Popen[Any], timeout: float | None) -> WaitResult:
    start = time.perf_counter()
    while True:
        pid, wait_status, rusage = os.wait4(process.pid, os.WNOHANG)

        if pid != 0:
            # process exited
            rtime = time.perf_counter() - start
            exit_code = os.waitstatus_to_exitcode(wait_status)
            return WaitResult(exit_code, ResourceData.from_rusage(rtime, rusage), timed_out=False)

        if timeout is not None and time.perf_counter() - start > timeout:
            # timeout
            process.kill()
            process.wait()
            rtime = time.perf_counter() - start
            return WaitResult(TIMEOUT_EXIT_CODE, ResourceData(rtime), timed_out=True)

        time.sleep(0.01)


def _wait_fallback(process: subprocess.Popen[Any], timeout: float | None) -> WaitResult:
    start = time.perf_counter()
    try:
        process.wait(timeout=timeout)
        exit_code = process.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        exit_code = TIMEOUT_EXIT_CODE
        timed_out = True
    finally:
        rtime = time.perf_counter() - start
        return WaitResult(exit_code, ResourceData(rtime), timed_out=timed_out)


def wait(process: subprocess.Popen[Any], timeout: float | None) -> WaitResult:
    """Wait for the process to exit, returning its exit code and resource usage."""
    if hasattr(os, "wait4"):
        return _wait4(process, timeout)

    return _wait_fallback(process, timeout)
