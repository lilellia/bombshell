import os
import subprocess
import time
from typing import Any

from .resources import ResourceData

TIMEOUT_EXIT_CODE = 124


def _wait4(process: subprocess.Popen[Any], timeout: float | None) -> tuple[int, ResourceData]:
    start = time.perf_counter()
    while True:
        pid, wait_status, rusage = os.wait4(process.pid, os.WNOHANG)

        if pid != 0:
            # process exited
            rtime = time.perf_counter() - start
            exit_code = os.waitstatus_to_exitcode(wait_status)
            return (exit_code, ResourceData.from_rusage(rtime, rusage))

        if timeout is not None and time.perf_counter() - start > timeout:
            # timeout
            process.kill()
            process.wait()
            rtime = time.perf_counter() - start
            return (TIMEOUT_EXIT_CODE, ResourceData(rtime))

        time.sleep(0.01)


def _wait_fallback(process: subprocess.Popen[Any], timeout: float | None) -> tuple[int, ResourceData]:
    start = time.perf_counter()
    try:
        process.wait(timeout=timeout)
        exit_code = process.returncode
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        exit_code = TIMEOUT_EXIT_CODE
    finally:
        rtime = time.perf_counter() - start
        return (exit_code, ResourceData(rtime))


def wait(process: subprocess.Popen[Any], timeout: float | None) -> tuple[int, ResourceData]:
    """Wait for the process to exit, returning its exit code and resource usage."""
    if hasattr(os, "wait4"):
        return _wait4(process, timeout)

    return _wait_fallback(process, timeout)
