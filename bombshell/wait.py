from collections.abc import Callable
from contextlib import suppress
import ctypes
from enum import IntEnum
import os
import select
import selectors
import signal
import subprocess
import time
from typing import Any, cast, NamedTuple

from .resources import ResourceData

TIMEOUT_EXIT_CODE = 124


class WaitResult(NamedTuple):
    exit_code: int
    resource_data: ResourceData
    timed_out: bool


def _query_selector(get_events: Callable[[], list[Any]], start_time: float, pid: int) -> WaitResult:
    events = get_events()
    rtime = time.perf_counter() - start_time
    if events:
        # process exited normally
        _, wait_status, rusage = os.wait4(pid, 0)  # block until the zombie is reaped
        exit_code = os.waitstatus_to_exitcode(wait_status)
        timed_out = False
    else:
        # process timed out
        os.kill(pid, signal.SIGKILL)
        _, _, rusage = os.wait4(pid, 0)  # block until the zombie is reaped
        exit_code = TIMEOUT_EXIT_CODE
        timed_out = True

    resource_data = ResourceData.from_rusage(rtime, rusage)
    return WaitResult(exit_code, resource_data, timed_out=timed_out)


def _wait_on_pidfd(pid: int, timeout: float | None) -> WaitResult:
    """Wait for the process to exit, returning its exit code and resource usage.
    This implementation is only available on Linux >=5.3.
    """
    start_time = time.perf_counter()
    fd = os.pidfd_open(pid)

    # the file descriptor becomes marked as readable when the process exits
    sel = selectors.DefaultSelector()
    sel.register(fd, selectors.EVENT_READ)

    def _get_events() -> list[Any]:
        return cast(list[Any], sel.select(timeout=timeout))

    try:
        return _query_selector(_get_events, start_time, pid)
    finally:
        sel.close()
        os.close(fd)


def _wait_kqueue(process: subprocess.Popen[Any], timeout: float | None) -> WaitResult:
    """Wait for the process to exit, returning its exit code and resource usage.
    This implementation is only available on macOS/BSD.
    """
    start_time = time.perf_counter()

    # mypy type ignores are necessary because kqueue is not cross-compatible
    kq = select.kqueue()  # type: ignore[attr-defined]
    event = select.kevent(  # type: ignore[attr-defined]
        process.pid,
        filter=select.KQ_FILTER_PROC,  # type: ignore[attr-defined]
        flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT,  # type: ignore[attr-defined]
        fflags=select.KQ_NOTE_EXIT,  # type: ignore[attr-defined]
    )

    def _get_events() -> list[Any]:
        return cast(list[Any], kq.control((event,), maxevents=1, timeout=timeout))

    try:
        return _query_selector(_get_events, start_time, process.pid)
    finally:
        kq.close()


def _wait_on_windows(process: subprocess.Popen[Any], timeout: float | None) -> WaitResult:
    """Wait for the process to exit, returning its exit code and resource usage.
    This implementation is only available on Windows.
    """
    INFINITE = 0xFFFFFFFF

    DWORD = ctypes.wintypes.DWORD  # type: ignore[attr-defined]

    class AccessRights(IntEnum):
        # https://learn.microsoft.com/en-us/windows/win32/procthread/process-security-and-access-rights

        # standard access rights
        DELETE = 0x0001 << 32  # required to delete the object
        READ_CONTROL = 0x0002 << 32  # required to read information in the security descriptor (but not info in SACL)
        WRITE_DAC = 0x0004 << 32  # required to modify the DACL in the security descriptor
        WRITE_OWNER = 0x0008 << 32  # required to modify the owner in the security descriptor
        SYNCHRONIZE = 0x0010 << 32  # enables thread to wait until the object is in the signaled state

        # process-specific access rights
        PROCESS_TERMINATE = 0x0001  # required to terminate the process
        PROCESS_CREATE_THREAD = 0x0002  # required to create a thread in the process
        PROCESS_VM_OPERATION = 0x0008  # required to access the virtual memory of the process
        PROCESS_VM_READ = 0x0010  # required to read memory in the process
        PROCESS_VM_WRITE = 0x0020  # required to write to memory in the process
        PROCESS_DUP_HANDLE = 0x0040  # required to duplicate handles using DuplicateHandle
        PROCESS_CREATE_PROCESS = 0x0080  # required to use this process as the parent process
        PROCESS_SET_QUOTA = 0x0100  # required to change memory quotas for the process
        PROCESS_SET_INFORMATION = 0x0200  # required to set certain information about the process
        PROCESS_QUERY_INFORMATION = 0x0400  # required to retrieve certain information about the process
        PROCESS_SUSPEND_RESUME = 0x0800  # required to suspend or resume a process
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # required to retrieve limited information about the process
        PROCESS_ALL_ACCESS = 0xFFFF  # all possible access rights for a process object

    class WaitSingleObjectResult(IntEnum):
        # https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject#return-value
        WAIT_OBJECT_0 = 0  # specified object is signaled
        WAIT_ABANDONED = 0x80  # specified object was not released by the owner thread before the thread terminated
        WAIT_TIMEOUT = 0x102  # the time-out interval elapsed; the object is not signaled
        WAIT_FAILED = 0xFFFFFFFF  # the function failed

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", DWORD),
            ("dwHighDateTime", DWORD),
        ]

        def as_seconds(self) -> float:
            """Return the number of seconds represented by the FILETIME structure.
            Note: the FILETIME structure is in 100-nanosecond (1e-7 second) intervals.
            """
            intervals = cast(int, (self.dwHighDateTime << 32) + self.dwLowDateTime)
            return intervals * 1e-7

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", DWORD),
            ("PageFaultCount", DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    def OpenProcess(desired_access: int, inherit_handle: bool, process_id: int) -> int | None:
        """OpenProcess(DWORD dwDesiredAccess, BOOL bInheritHandle, DWORD dwProcessId)
        https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess
        """
        f = ctypes.windll.kernel32.OpenProcess  # type: ignore[attr-defined]
        f.argtypes = (DWORD, ctypes.c_bool, DWORD)
        f.restype = ctypes.c_void_p

        result = f(desired_access, inherit_handle, process_id)
        return cast(int | None, result)

    def CloseHandle(handle: int) -> bool:
        """CloseHandle(HANDLE hObject)
        https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-closehandle
        """
        f = ctypes.windll.kernel32.CloseHandle  # type: ignore[attr-defined]
        f.argtypes = (ctypes.c_void_p,)
        f.restype = ctypes.c_bool

        result = f(handle)
        return cast(bool, result)

    def WaitForSingleObject(handle: int, timeout_ms: int) -> int:
        """WaitForSingleObject(HANDLE hObject, DWORD dwMilliseconds)
        https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject
        """
        f = ctypes.windll.kernel32.WaitForSingleObject  # type: ignore[attr-defined]
        f.argtypes = (ctypes.c_void_p, DWORD)
        f.restype = ctypes.c_uint32

        result = f(handle, timeout_ms)
        return cast(int, result)

    def GetProcessTimes(
        handle: int,
        out_create_time: FILETIME,
        out_exit_time: FILETIME,
        out_kernel_time: FILETIME,
        out_user_time: FILETIME,
    ) -> bool:
        """GetProcessTimes(
            HANDLE hProcess,
            LPFILETIME lpCreationTime,
            LPFILETIME lpExitTime,
            LPFILETIME lpKernelTime,
            LPFILETIME lpUserTime
        )
        https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes
        """
        f = ctypes.windll.kernel32.GetProcessTimes  # type: ignore[attr-defined]
        f.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
        )
        f.restype = ctypes.c_bool

        result = f(
            handle,
            ctypes.byref(out_create_time),
            ctypes.byref(out_exit_time),
            ctypes.byref(out_kernel_time),
            ctypes.byref(out_user_time),
        )
        return cast(bool, result)

    def GetProcessMemoryInfo(handle: int, out_memory: PROCESS_MEMORY_COUNTERS, size: int) -> bool:
        """GetProcessMemoryInfo(HANDLE hProcess, PPROCESS_MEMORY_COUNTERS lpProcessMemoryCounters, DWORD cb)
        https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocessmemoryinfo
        """
        f = ctypes.windll.psapi.GetProcessMemoryInfo  # type: ignore[attr-defined]
        f.argtypes = (ctypes.c_void_p, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), DWORD)
        f.restype = ctypes.c_bool

        result = f(handle, ctypes.byref(out_memory), size)
        return cast(bool, result)

    def get_windows_rusage(handle: int, start_time: float) -> ResourceData:
        """Get the resource usage of a process on Windows."""

        # These structs are used as out parameters
        creation_time = FILETIME()
        exit_time = FILETIME()
        kernel_time = FILETIME()
        user_time = FILETIME()
        memory = PROCESS_MEMORY_COUNTERS()

        if GetProcessTimes(handle, creation_time, exit_time, kernel_time, user_time):
            # successfully got data
            rtime = exit_time.as_seconds() - creation_time.as_seconds()
            stime = kernel_time.as_seconds()
            utime = user_time.as_seconds()
        else:
            # failed to get process times, so... :shrug:
            rtime = time.perf_counter() - start_time
            stime = None
            utime = None

        if GetProcessMemoryInfo(handle, memory, ctypes.sizeof(memory)):
            # successfully got memory info
            maxrss = memory.PeakWorkingSetSize
        else:
            # failed to get memory info, so... :shrug:
            maxrss = None

        return ResourceData(real_time=rtime, user_time=utime, system_time=stime, max_resident_set_size=maxrss)

    # get Windows handle for the process
    access = AccessRights.SYNCHRONIZE | AccessRights.PROCESS_TERMINATE | AccessRights.PROCESS_QUERY_INFORMATION
    handle = OpenProcess(desired_access=access, inherit_handle=False, process_id=process.pid)

    if handle is None:
        raise OSError(f"Could not retrieve process handle for pid {process.pid}")

    start_time = time.perf_counter()

    try:
        # wait on the handle
        timeout_ms = round(timeout * 1000) if timeout is not None else INFINITE
        match WaitForSingleObject(handle, timeout_ms):
            case WaitSingleObjectResult.WAIT_OBJECT_0:
                # process exited normally
                rusage = get_windows_rusage(handle, start_time)
                process.wait()  # allow the process to be reaped so we can query its exit code
                return WaitResult(process.returncode, rusage, timed_out=False)

            case WaitSingleObjectResult.WAIT_TIMEOUT:
                # process timed out
                rusage = get_windows_rusage(handle, start_time)
                process.kill()
                process.wait()
                return WaitResult(TIMEOUT_EXIT_CODE, rusage, timed_out=True)
    finally:
        CloseHandle(handle)

    # if we're here, then something went wrong, so I guess we'll just fall back to the blind interpretation
    res = _blind_wait_fallback(process, timeout)
    resource_data = ResourceData(time.perf_counter() - start_time)
    return WaitResult(res.exit_code, resource_data, timed_out=res.timed_out)


def _busy_wait4_fallback(process: subprocess.Popen[Any], timeout: float | None) -> WaitResult:
    """Wait for the process to exit, returning its exit code and resource usage.
    This implementation is available on any POSIX system.
    """
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


def _blind_wait_fallback(process: subprocess.Popen[Any], timeout: float | None) -> WaitResult:
    """Wait for the process to exit, returning its exit code and resource usage.
    This implementation is always available.
    """
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
    """Wait for the process to exit, returning its exit code and resource usage.

    The exact implementation is determined by the native capabilities of the OS.
    """
    if hasattr(os, "wait4") and hasattr(os, "pidfd_open"):
        # Linux >=5.3
        return _wait_on_pidfd(pid=process.pid, timeout=timeout)

    if hasattr(os, "wait4") and hasattr(select, "kqueue"):
        # macOS/BSD
        return _wait_kqueue(process, timeout)

    if os.name == "nt":
        # Windows
        # (OSError is raised if any of the C-level translation calls fails)
        with suppress(OSError):
            return _wait_on_windows(process, timeout)

    if hasattr(os, "wait4"):
        # any other POSIX system
        return _busy_wait4_fallback(process, timeout)

    # any other system
    return _blind_wait_fallback(process, timeout)
