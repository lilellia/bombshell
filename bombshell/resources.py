import sys
import time
from typing import NamedTuple, Protocol

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


class RUsage(Protocol):
    @property
    def ru_utime(self) -> float: ...

    @property
    def ru_stime(self) -> float: ...

    @property
    def ru_maxrss(self) -> int: ...


class ResourceData(NamedTuple):
    """Information regarding the resource usage of a process. On non-Unix systems, only `real_time` can be non-None.
    In most cases, Unix systems will have all values, though it's possible for them to be None if the process could
    not be reaped normally.

    Attributes:
        real_time: The real time used by the process. This value is guaranteed to be non-None, even on Windows.
        user_time: The user time used by the process.
        system_time: The system time used by the process.
        max_resident_set_size: The maximum resident set size used by the process, in bytes.
            Note that Linux natively uses kibibytes for this value.
    """

    real_time: float
    user_time: float | None = None
    system_time: float | None = None
    max_resident_set_size: int | None = None

    @classmethod
    def from_rusage(cls, real_time: float, rusage: RUsage) -> Self:
        # MacOS reports rss in bytes; Linux reports it in KiB
        multiplier = 1 if sys.platform == "darwin" else 1024

        return cls(
            real_time=real_time,
            user_time=rusage.ru_utime,
            system_time=rusage.ru_stime,
            max_resident_set_size=multiplier * rusage.ru_maxrss,
        )

    @classmethod
    def from_start_time(cls, start: float) -> Self:
        return cls(real_time=time.perf_counter() - start)

    @property
    def rtime(self) -> float:
        """Return the real time used by the process."""
        return self.real_time

    @property
    def utime(self) -> float | None:
        """Return the user time used by the process."""
        return self.user_time

    @property
    def stime(self) -> float | None:
        """Return the system time used by the process."""
        return self.system_time

    @property
    def maxrss(self) -> int | None:
        """Return the maximum resident set size used by the process."""
        return self.max_resident_set_size
