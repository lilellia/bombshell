from dataclasses import dataclass, field
import sys
from typing import cast, Generic, TypeVar

from .resources import ResourceData

S = TypeVar("S", str, bytes)


if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


@dataclass(frozen=True, slots=True)
class CompletedProcess(Generic[S]):
    args: tuple[tuple[str, ...], ...]
    command: str
    exit_codes: tuple[int, ...]
    stdout: S
    stderr: S
    runtime: float
    resources: tuple[ResourceData, ...]
    _timed_out: bool = field(init=True, repr=False)

    def __add__(self, other: Self) -> Self:
        if not isinstance(other, type(self)):
            return NotImplemented

        return type(self)(
            args=self.args + other.args,
            command=f"{self.command} && {other.command}",
            exit_codes=(*self.exit_codes, *other.exit_codes),
            stdout=self.stdout + other.stdout,
            stderr=self.stderr + other.stderr,
            runtime=self.runtime + other.runtime,
            resources=(*self.resources, *other.resources),
            _timed_out=self._timed_out or other._timed_out,
        )

    @property
    def exit_code(self) -> int:
        return self.exit_codes[-1]

    @property
    def total_resources(self) -> ResourceData:
        """Return the total resource usage for all processes in the pipeline.
        On non-Unix systems, only `real_time` can be non-None.
        """
        rtime = self.runtime

        all_user_times = [r.user_time for r in self.resources]
        utime = None if None in all_user_times else sum(cast(list[float], all_user_times))

        all_system_times = [r.system_time for r in self.resources]
        stime = None if None in all_system_times else sum(cast(list[float], all_system_times))

        all_maxrss = [r.max_resident_set_size for r in self.resources]
        maxrss = None if None in all_maxrss else max(cast(list[int], all_maxrss))

        return ResourceData(
            real_time=rtime,
            user_time=utime,
            system_time=stime,
            max_resident_set_size=maxrss,
        )

    def timed_out(self) -> bool:
        """Return True if any of the processes in the pipeline timed out."""
        return self._timed_out

    def check(self, *, strict: bool = False) -> None:
        """Raise a PipelineError if the pipeline exited with a non-zero exit code.

        :arg strict:
            If True, raise PipelineError if any process exited with a non-zero exit code.
            If False, raise PipelineError if the last process exited with a non-zero exit code.

        :return: None
        :raise PipelineError: If any (strict=True) or the last (strict=False) process exited with a non-zero exit code.
        """
        if strict and any(ec != 0 for ec in self.exit_codes):
            raise PipelineError(self)

        if not strict and self.exit_code != 0:
            raise PipelineError(self)

    def exit(self) -> None:
        """Raise SystemExit with the same exit code as the last process in the pipeline."""
        sys.exit(self.exit_code)


class PipelineError(Exception, Generic[S]):
    def __init__(self, process: CompletedProcess[S]) -> None:
        msg = f"Pipeline exited with non-zero exit code(s): {process.exit_codes}"
        super().__init__(msg)
        self.process: CompletedProcess[S] = process
