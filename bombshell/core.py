from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from enum import Enum
import os
from os import PathLike
import shlex
import subprocess
import sys
from threading import Thread
import time
from typing import Any, NamedTuple, overload, TypeVar

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


from .resources import ResourceData
from .results import CompletedProcess
from .spin import spin
from .stream import consume_stream, feed_stream, make_buffer
from .wait import wait

S = TypeVar("S", str, bytes)


class CommandRelation(Enum):
    NONE = ""
    PIPE = "|"
    THEN = ";"
    CHAIN = "&&"


class _ActiveProcess(NamedTuple):
    process: subprocess.Popen[Any]
    start_time: float


@overload
def exec(
    *args: str,
    env: Mapping[str, str] | None = None,
    cwd: str | PathLike[str] | None = None,
    capture: bool = True,
    mode: type[bytes] = bytes,
    merge_stderr: bool = False,
    timeout: float | None = None,
    with_spinner: bool = False,
) -> CompletedProcess[bytes]: ...


@overload
def exec(
    *args: str,
    env: Mapping[str, str] | None = None,
    cwd: str | PathLike[str] | None = None,
    capture: bool = True,
    mode: type[str] = str,
    merge_stderr: bool = False,
    timeout: float | None = None,
    with_spinner: bool = False,
) -> CompletedProcess[str]: ...


def exec(
    *args: str,
    env: Mapping[str, str] | None = None,
    cwd: str | PathLike[str] | None = None,
    capture: bool = True,
    mode: type[S] = str,  # type: ignore
    merge_stderr: bool = False,
    timeout: float | None = None,
    with_spinner: bool = False,
) -> CompletedProcess[S]:
    """Execute the given command and return the result as a CompletedProcess object."""
    return Process(*args, env=env, cwd=cwd).exec(
        capture=capture, mode=mode, merge_stderr=merge_stderr, timeout=timeout, with_spinner=with_spinner
    )


class Process:
    def __init__(
        self,
        *args: Any,
        env: Mapping[str, str] | None = None,
        cwd: str | PathLike[str] | None = None,
        _relation: CommandRelation = CommandRelation.NONE,
        _children: tuple[Process, Process] | None = None,
    ):
        self._args = tuple(str(arg) for arg in args)
        self.env = {**os.environ, **(env or {})}
        self.cwd = cwd

        self._relation = _relation
        self._children = _children

    @property
    def args(self) -> tuple[tuple[str, ...], ...]:
        if self._children:
            left, right = self._children

            return left.args + right.args

        return (self._args,)

    def _bridge(
        self,
        *args: Any,
        env: Mapping[str, str] | None = None,
        cwd: str | PathLike[str] | None = None,
        relation: CommandRelation = CommandRelation.NONE,
    ) -> Self:
        match args:
            case []:
                raise ValueError("function requires at least one argument")
            case [obj] if isinstance(obj, (Process, type(self))):
                # Command("echo", 1).pipe_into(Command("echo", 2))
                other = obj
            case _:
                # Command("echo", 1).pipe_into("echo", 2)
                other = type(self)(*args, env=env, cwd=cwd)

        return type(self)(_relation=relation, _children=(self, other))

    def pipe_into(
        self, *args: Any, env: Mapping[str, str] | None = None, cwd: str | PathLike[str] | None = None
    ) -> Self:
        return self._bridge(*args, env=env, cwd=cwd, relation=CommandRelation.PIPE)

    def __or__(self, other: Self) -> Self:
        if not isinstance(other, type(self)):
            return NotImplemented

        return self.pipe_into(other)

    def then(self, *args: Any, env: Mapping[str, str] | None = None, cwd: str | PathLike[str] | None = None) -> Self:
        return self._bridge(*args, env=env, cwd=cwd, relation=CommandRelation.THEN)

    def and_then(
        self, *args: Any, env: Mapping[str, str] | None = None, cwd: str | PathLike[str] | None = None
    ) -> Self:
        return self._bridge(*args, env=env, cwd=cwd, relation=CommandRelation.CHAIN)

    def with_cwd(self, cwd: str | PathLike[str] | None) -> Self:
        if self._children:
            left, right = self._children

            return type(self)(
                _relation=self._relation,
                _children=(left.with_cwd(cwd), right.with_cwd(cwd)),
            )

        return type(self)(*self._args, env=self.env, cwd=cwd)

    def with_env(self, **kwargs: str) -> Self:
        if self._children:
            left, right = self._children

            return type(self)(
                _relation=self._relation,
                _children=(left.with_env(**kwargs), right.with_env(**kwargs)),
            )

        return type(self)(*self._args, env={**self.env, **kwargs}, cwd=self.cwd)

    @overload
    def exec(
        self,
        stdin: str | None = None,
        *,
        capture: bool = True,
        mode: type[str] = str,
        merge_stderr: bool = False,
        timeout: float | None = None,
        with_spinner: bool = False,
    ) -> CompletedProcess[str]: ...

    @overload
    def exec(
        self,
        stdin: bytes | None = None,
        *,
        capture: bool = True,
        mode: type[bytes] = bytes,
        merge_stderr: bool = False,
        timeout: float | None = None,
        with_spinner: bool = False,
    ) -> CompletedProcess[bytes]: ...

    def exec(
        self,
        stdin: S | None = None,
        *,
        capture: bool = True,
        mode: type[S] = str,  # type: ignore[assignment]
        merge_stderr: bool = False,
        timeout: float | None = None,
        with_spinner: bool = False,
    ) -> CompletedProcess[S]:
        match self._relation:
            case CommandRelation.NONE | CommandRelation.PIPE:
                procs = self._launch(
                    stdin_fd=subprocess.PIPE if stdin is not None else None,
                    stdout_fd=subprocess.PIPE if capture else None,
                    stderr_fd=subprocess.STDOUT if merge_stderr else (subprocess.PIPE if capture else None),
                    text=(mode is str),
                )

                with spin(message=str(self)) if with_spinner else nullcontext() as spin_state:
                    res = self._exec_pipeline(procs, stdin=stdin, capture=capture, mode=mode, timeout=timeout)

                    if spin_state:
                        spin_state.exit_code = res.exit_code
                    return res

            case CommandRelation.THEN | CommandRelation.CHAIN:
                check = self._relation == CommandRelation.CHAIN
                return self._exec_chain(
                    stdin,
                    capture=capture,
                    mode=mode,
                    merge_stderr=merge_stderr,
                    timeout=timeout,
                    with_spinner=with_spinner,
                    check=check,
                )

            case _:
                raise ValueError(f"invalid relation: {self._relation}")

    def _launch(
        self, stdin_fd: int | None, stdout_fd: int | None, stderr_fd: int | None, text: bool
    ) -> list[_ActiveProcess]:
        match self._relation:
            case CommandRelation.NONE:
                p = subprocess.Popen(
                    self._args,
                    stdin=stdin_fd,
                    stdout=stdout_fd,
                    stderr=stderr_fd,
                    text=text,
                    env=self.env,
                    cwd=self.cwd,
                )
                return [_ActiveProcess(p, time.perf_counter())]

            case CommandRelation.PIPE:
                assert self._children is not None
                left, right = self._children
                r, w = os.pipe()

                p1 = left._launch(stdin_fd, w, stderr_fd, text)
                p2 = right._launch(r, stdout_fd, stderr_fd, text)

                os.close(r)
                os.close(w)

                return p1 + p2

            case CommandRelation.THEN | CommandRelation.CHAIN:
                raise NotImplementedError

    def _exec_pipeline(
        self,
        procs: Sequence[_ActiveProcess],
        stdin: S | None,
        *,
        capture: bool,
        mode: type[S],
        timeout: float | None,
    ) -> CompletedProcess[S]:
        start_time = min(p.start_time for p in procs)

        stdout = make_buffer(mode)
        stderrs = [make_buffer(mode) for _ in procs]

        threads: list[Thread] = []

        # --- set up stdin to first process --- #
        if stdin:
            assert (sink := procs[0].process.stdin) is not None
            stdin_producer = Thread(target=feed_stream, kwargs=dict(sink=sink, content=stdin))
            stdin_producer.start()
            threads.append(stdin_producer)

        # --- set up stderr consumers --- #
        for (proc, _), buffer in zip(procs, stderrs):
            if proc.stderr:
                t = Thread(target=consume_stream, kwargs=dict(source=proc.stderr, sink=buffer))
                t.start()
                threads.append(t)

        # --- set up stdout consumer --- #
        if (stream := procs[-1].process.stdout) is not None:
            t = Thread(target=consume_stream, kwargs=dict(source=stream, sink=stdout))
            t.start()
            threads.append(t)

        # --- wait for all processes to exit --- #
        resource_data: list[ResourceData] = []
        exit_codes: list[int] = []
        timed_out = False

        for proc, start in procs:
            if timeout is None:
                remaining = None
            else:
                remaining = max(0, timeout - (time.perf_counter() - start_time))

            exit_code, resources, p_timed_out = wait(proc, timeout=remaining)
            exit_codes.append(exit_code)
            resource_data.append(resources)
            timed_out |= p_timed_out

        for t in threads:
            t.join()

        # --- build completed process object --- #
        stdout_content = stdout.getvalue()
        stderr_content = mode().join(buffer.getvalue() for buffer in stderrs)

        return CompletedProcess(
            args=self.args,
            command=str(self),
            exit_codes=tuple(exit_codes),
            stdout=stdout_content,
            stderr=stderr_content,
            resources=tuple(resource_data),
            runtime=time.perf_counter() - start_time,
            _timed_out=timed_out,
        )

    def _exec_chain(
        self,
        stdin: S | None,
        *,
        capture: bool,
        mode: type[S],
        merge_stderr: bool,
        timeout: float | None,
        with_spinner: bool,
        check: bool,
    ) -> CompletedProcess[S]:
        assert self._children is not None
        left, right = self._children

        with spin(message=str(left)) if with_spinner else nullcontext() as spin_state:
            res1 = left.exec(stdin=stdin, capture=capture, mode=mode, merge_stderr=merge_stderr, timeout=timeout)

            if spin_state:
                spin_state.exit_code = res1.exit_code

        if check and res1.exit_code:
            return res1

        if timeout is None:
            remaining = None
        else:
            remaining = max(0, timeout - res1.runtime)

        with spin(message=str(right)) if with_spinner else nullcontext() as spin_state:
            res2 = right.exec(stdin=None, capture=capture, mode=mode, merge_stderr=merge_stderr, timeout=remaining)

            if spin_state:
                spin_state.exit_code = res2.exit_code

        return res1 + res2

    __call__ = exec

    def __str__(self) -> str:
        match self._relation:
            case CommandRelation.NONE:
                return shlex.join(self._args)

            case CommandRelation.PIPE | CommandRelation.CHAIN | CommandRelation.THEN:
                assert self._children is not None
                left, right = self._children
                return f"{left} {self._relation.value} {right}"

            case _:
                raise ValueError(f"invalid relation: {self._relation}")
