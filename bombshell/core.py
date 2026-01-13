from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import itertools
import os
import shlex
import subprocess
import sys
from threading import Thread
from typing import Any, cast, Generic, IO, overload, TypeVar

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from .stream import consume_stream, feed_stream

S = TypeVar("S", str, bytes)


class PipelineError(Exception, Generic[S]):
    def __init__(self, process: CompletedProcess[S]) -> None:
        msg = f"Pipeline exited with non-zero exit code(s): {process.exit_codes}"
        super().__init__(msg)
        self.process: CompletedProcess[S] = process


@dataclass(frozen=True, slots=True)
class CompletedProcess(Generic[S]):
    args: tuple[tuple[str, ...], ...]
    command: str
    exit_codes: list[int]
    stdout: S
    stderr: S

    @property
    def exit_code(self) -> int:
        return self.exit_codes[-1]

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


class Process:
    def __init__(self, *args: Any, env: Mapping[str, str] | None = None):
        self.args = tuple(str(arg) for arg in args)
        self.env = {**os.environ, **(env or {})}

    def with_env(self, **kwargs: str) -> Self:
        return type(self)(*self.args, env={**self.env, **kwargs})

    def then(self, *args: Any) -> CommandChain:
        match args:
            case ():
                raise ValueError(".then requires at least one argument")
            case [obj] if isinstance(obj, (type(self), Pipeline, CommandChain)):
                # Process("echo", 1).then(Process("echo", 2))
                return CommandChain(self, obj)
            case _:
                # Process("echo", 1).then("echo", 2)
                return CommandChain(self, Process(*args))

    @overload
    def exec(
        self,
        stdin: str | None = None,
        *,
        capture: bool = True,
        mode: type[str] = str,
        merge_stderr: bool = False,
    ) -> CompletedProcess[str]: ...

    @overload
    def exec(
        self,
        stdin: bytes | None = None,
        *,
        capture: bool = True,
        mode: type[bytes],
        merge_stderr: bool = False,
    ) -> CompletedProcess[bytes]: ...

    def exec(
        self,
        stdin: S | None = None,
        *,
        capture: bool = True,
        mode: type[S] = str,  # type: ignore
        merge_stderr: bool = False,
    ) -> CompletedProcess[S]:
        return Pipeline(self)(stdin=stdin, capture=capture, mode=mode, merge_stderr=merge_stderr)

    @overload
    def __call__(
        self,
        stdin: str | None = None,
        *,
        capture: bool = True,
        mode: type[str] = str,
        merge_stderr: bool = False,
    ) -> CompletedProcess[str]: ...

    @overload
    def __call__(
        self,
        stdin: bytes | None = None,
        *,
        capture: bool = True,
        mode: type[bytes],
        merge_stderr: bool = False,
    ) -> CompletedProcess[bytes]: ...

    def __call__(
        self,
        stdin: S | None = None,
        *,
        capture: bool = True,
        mode: type[S] = str,  # type: ignore
        merge_stderr: bool = False,
    ) -> CompletedProcess[S]:
        return self.exec(stdin=stdin, capture=capture, mode=mode, merge_stderr=merge_stderr)

    def __or__(self, other: Self) -> Pipeline:
        """Create a pipeline between this process and other. Example: Process("ls", "-1") | Process("tail", 5)"""
        if isinstance(other, type(self)):
            return Pipeline(self, other)

        return NotImplemented

    def pipe_into(self, *args: str, env: Mapping[str, str] | None = None) -> Pipeline:
        """Create a pipeline between this process and a command. Example: Process("ls", "-1").pipe_into("tail", 5)"""
        match args:
            case ():
                raise ValueError(".pipe_into requires at least one argument")
            case [obj] if isinstance(obj, type(self)):
                # Process("echo", 1).pipe_into(Process("echo", 2))
                return Pipeline(self, obj)
            case _:
                # Process("echo", 1).pipe_into("echo", 2)
                return Pipeline(self, Process(*args))

        if args:
            return Pipeline(self, Process(*args, env=env))

        raise NotImplementedError

    def __str__(self) -> str:
        return shlex.join(self.args)

    def __repr__(self) -> str:
        args = ", ".join(repr(arg) for arg in self.args)
        return f"{self.__class__.__name__}({args})"


class Pipeline:
    def __init__(self, *processes: Process) -> None:
        self.processes = processes

    def pipe_into(self, *args: Any, env: Mapping[str, str] | None = None) -> Self:
        match args:
            case ():
                raise ValueError(".pipe_into requires at least one argument")
            case [obj] if isinstance(obj, Process):
                return type(self)(*self.processes, obj)
            case [obj] if isinstance(obj, type(self)):
                return type(self)(*self.processes, *obj.processes)
            case _:
                # Process("echo", 1).pipe_into("echo", 2)
                return type(self)(*self.processes, Process(*args))

    def __or__(self, other: Process) -> Self:
        return self.pipe_into(other)

    def then(self, *args: Any) -> CommandChain:
        match args:
            case ():
                raise ValueError(".then requires at least one argument")
            case [obj] if isinstance(obj, (Process, type(self), CommandChain)):
                # Process("echo", 1).then(Process("echo", 2))
                return CommandChain(self, obj)
            case _:
                # Process("echo", 1).then("echo", 2)
                return CommandChain(self, Process(*args))

    @overload
    def _setup_chain(
        self, stdin: str | None, capture: bool, mode: type[str], merge_stderr: bool
    ) -> list[subprocess.Popen[str]]: ...

    @overload
    def _setup_chain(
        self, stdin: bytes | None, capture: bool, mode: type[bytes], merge_stderr: bool
    ) -> list[subprocess.Popen[bytes]]: ...

    def _setup_chain(
        self, stdin: S | None, capture: bool, mode: type[S], merge_stderr: bool
    ) -> list[subprocess.Popen[S]]:
        procs: list[subprocess.Popen[S]] = []
        is_text = mode is str

        for i, proc in enumerate(self.processes):
            # determine where to get input
            proc_stdin: int | IO[Any] | None
            if i == 0 and stdin is not None:
                proc_stdin = subprocess.PIPE
            elif i > 0:
                proc_stdin = procs[i - 1].stdout
            else:
                proc_stdin = None

            # determine where to send output
            if capture or i < len(self.processes) - 1:
                proc_stdout = subprocess.PIPE
            else:
                proc_stdout = None

            # determine where to send stderr
            if i < len(self.processes) - 1:
                # intermediate process
                proc_stderr = subprocess.PIPE if capture else None
            elif capture:
                # final process
                proc_stderr = subprocess.STDOUT if merge_stderr else subprocess.PIPE
            else:
                proc_stderr = None

            p = subprocess.Popen(
                proc.args, stdin=proc_stdin, stdout=proc_stdout, stderr=proc_stderr, text=is_text, env=proc.env
            )
            procs.append(p)

            # close the stdout of the previous process in order to allow it to receive SIGPIPE
            if i > 0 and (prev_stdout := procs[i - 1].stdout):
                prev_stdout.close()

        return procs

    @overload
    def exec(
        self,
        stdin: str | None = None,
        *,
        capture: bool = True,
        mode: type[str] = str,
        merge_stderr: bool = False,
    ) -> CompletedProcess[str]: ...

    @overload
    def exec(
        self,
        stdin: bytes | None = None,
        *,
        capture: bool = True,
        mode: type[bytes],
        merge_stderr: bool = False,
    ) -> CompletedProcess[bytes]: ...

    def exec(
        self,
        stdin: S | None = None,
        *,
        capture: bool = True,
        mode: type[S] = str,  # type: ignore
        merge_stderr: bool = False,
    ) -> CompletedProcess[S]:
        procs = self._setup_chain(stdin=stdin, capture=capture, mode=mode, merge_stderr=merge_stderr)

        # --- set up stdout/stderr handlers --- #
        stdout_block: list[S] = []
        stderr_blocks: list[list[S]] = [[] for _ in procs]
        threads: list[Thread] = []

        for idx, proc in enumerate(procs):
            if proc.stderr:
                t = Thread(target=consume_stream, args=(proc.stderr, stderr_blocks[idx]))
                t.start()
                threads.append(t)

        if procs[-1].stdout:
            t = Thread(target=consume_stream, args=(procs[-1].stdout, stdout_block))
            t.start()
            threads.append(t)

        # --- handle stdin to first process --- #
        if stdin is not None:
            assert procs[0].stdin is not None
            t = Thread(target=feed_stream, args=(procs[0].stdin, stdin))
            t.start()
            threads.append(t)

        # --- wait for all processes to finish --- #
        for t in threads:
            t.join()

        exit_codes: list[int] = []
        for p in procs:
            p.wait()
            exit_codes.append(p.returncode)

        # --- build completed process object --- #
        stdout = mode().join(stdout_block) if capture else mode()
        stderr = mode().join(mode().join(block) for block in stderr_blocks) if capture and not merge_stderr else mode()
        args = tuple(proc.args for proc in self.processes)

        return CompletedProcess(args=args, command=str(self), exit_codes=exit_codes, stdout=stdout, stderr=stderr)

    @overload
    def __call__(
        self,
        stdin: str | None = None,
        *,
        capture: bool = True,
        mode: type[str] = str,
        merge_stderr: bool = False,
    ) -> CompletedProcess[str]: ...

    @overload
    def __call__(
        self,
        stdin: bytes | None = None,
        *,
        capture: bool = True,
        mode: type[bytes],
        merge_stderr: bool = False,
    ) -> CompletedProcess[bytes]: ...

    def __call__(
        self,
        stdin: S | None = None,
        *,
        capture: bool = True,
        mode: type[S] = str,  # type: ignore
        merge_stderr: bool = False,
    ) -> CompletedProcess[S]:
        return self.exec(stdin=stdin, capture=capture, mode=mode, merge_stderr=merge_stderr)

    def __str__(self) -> str:
        return " | ".join(str(process) for process in self.processes)

    def __repr__(self) -> str:
        args = ", ".join(repr(process) for process in self.processes)
        return f"{self.__class__.__name__}({args})"


class CommandChain:
    def __init__(self, *items: Process | Pipeline | Self) -> None:
        self.items: list[Process | Pipeline] = []

        for item in items:
            if isinstance(item, type(self)):
                self.items.extend(item.items)
            else:
                item = cast(Process | Pipeline, item)
                self.items.append(item)

    def then(self, *args: Any) -> Self:
        match args:
            case ():
                raise ValueError(".then requires at least one argument")
            case [obj] if isinstance(obj, (Process, Pipeline, type(self))):
                # Process("echo", 1).then(Process("echo", 2))
                return type(self)(self, obj)
            case _:
                # Process("echo", 1).then("echo", 2)
                return type(self)(self, Process(*args))

    @overload
    def exec(
        self, stdin: str | None = None, *, capture: bool = True, mode: type[str] = str, merge_stderr: bool = False
    ) -> CompletedProcess[str]: ...

    @overload
    def exec(
        self, stdin: bytes | None = None, *, capture: bool = True, mode: type[bytes], merge_stderr: bool = False
    ) -> CompletedProcess[bytes]: ...

    def exec(
        self,
        stdin: S | None = None,
        *,
        capture: bool = True,
        mode: type[S] = str,  # type: ignore
        merge_stderr: bool = False,
    ) -> CompletedProcess[S]:
        all_args: list[tuple[tuple[str, ...], ...]] = []
        all_exit_codes: list[int] = []

        stdout_parts: list[S] = []
        stderr_parts: list[S] = []

        for idx, item in enumerate(self.items):
            proc_stdin = stdin if idx == 0 else None
            res = item.exec(stdin=proc_stdin, capture=capture, mode=mode, merge_stderr=merge_stderr)

            all_args.append(res.args)
            all_exit_codes.extend(res.exit_codes)
            stdout_parts.append(res.stdout)
            stderr_parts.append(res.stderr)

            if res.exit_code != 0:
                break

        return CompletedProcess(
            args=tuple(itertools.chain.from_iterable(all_args)),
            command=str(self),
            exit_codes=all_exit_codes,
            stdout=mode().join(stdout_parts),
            stderr=mode().join(stderr_parts),
        )

    @overload
    def __call__(
        self, stdin: str | None = None, *, capture: bool = True, mode: type[str] = str, merge_stderr: bool = False
    ) -> CompletedProcess[str]: ...

    @overload
    def __call__(
        self, stdin: bytes | None = None, *, capture: bool = True, mode: type[bytes], merge_stderr: bool = False
    ) -> CompletedProcess[bytes]: ...

    def __call__(
        self,
        stdin: S | None = None,
        *,
        capture: bool = True,
        mode: type[S] = str,  # type: ignore
        merge_stderr: bool = False,
    ) -> CompletedProcess[S]:
        return self.exec(stdin=stdin, capture=capture, mode=mode, merge_stderr=merge_stderr)

    def __str__(self) -> str:
        return " && ".join(str(item) for item in self.items)

    def __repr__(self) -> str:
        args = ", ".join(repr(item) for item in self.items)
        return f"{self.__class__.__name__}({args})"
