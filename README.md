# bombshell

A library for easily running subprocesses in Python, whether single or piped.

## Why?

Python's `subprocess` library is capable of running whatever you need it to, but isn't always the most friendly or readable option, even when running a single process:

```py
res = subprocess.run(("echo", "1"), capture_output=True, text=True)
print(res.stdout)  # "1\n"
```

Needing to pass `capture_output=True, text=True` all the time is annoying when those are probably the most common default. Plus, the command has to be passed as a tuple/list, rather than just the arguments themselves.

```py
res = Process("echo", "1").exec()
print(res.stdout)        # "1\n"
print(type(res.stdout))  # <class 'str'>
```

But if you want bytes, then you can have bytes:

```py
res = Process("echo", "1").exec(mode=bytes)
print(res.stdout)        # b"1\n"
print(type(res.stdout))  # <class 'bytes'>
```

`subprocess` is also really picky about the types of arguments you pass in:

```py
res = subprocess.run(("echo", 1))
TypeError: "expected str, bytes or os.PathLike object, not int"
```

Why, though? `bombshell` automatically calls `str()` on every argument passed to it.

```py
res = Process("echo", 1).exec()
print(res.stdout)     # "1\n"
print(res.exit_code)  # 0
```

`subprocess` also makes piping commands way more difficult than it needs to be. What's easy in Bash...

```bash
res=$(echo "hello\nworld\ngoodbye" | grep "l")
echo "$res"  # "hello\nworld"
```

...is way more complicated with `subprocess` since you have to individually manage both sides of the pipe.

```py
parent = subprocess.Popen(("echo", "hello\nworld\ngoodbye"), stdout=subprocess.PIPE)
child = subprocess.Popen(("grep", "l"), stdin=parent.stdout, capture_output=True, text=True)
stdout, _ = child.communicate()

print(stdout)  # "hello\nworld"
```

There must be a better way.

```py
res = Process("echo", "hello\nworld\ngoodbye").pipe_into("grep", "l").exec()
print(res.stdout)  # "hello\nworld"

# Process supports .__or__, so we can also do
p1 = Process("echo", "hello\nworld\ngoodbye")
p2 = Process("grep", "l")
res = (p1 | p2).exec()
print(res.stdout)  # "hello\nworld"
```

We can also pass environment variables to individual commands:

```py
res = subprocess.run(("printenv", "FOO"), capture_output=True, text=True, env={"FOO": "bar"})
print(res.stdout)  # "bar\n"


res = Process("printenv", "FOO", env={"FOO": "bar"}).exec()
res = Process("printenv", "FOO").with_env(FOO="bar").exec()
print(res.stdout)  # "bar\n"
```

or set the current working directory:

```py
res = subprocess.run(("pwd",), capture_output=True, text=True, cwd="/tmp")
print(res.stdout)  # "/tmp\n"


res = Process("pwd", cwd="/tmp").exec()
res = Process("pwd").with_cwd("/tmp").exec()
print(res.stdout)  # "/tmp\n"
```

`subprocess` also makes it somewhat difficult to chain commands (`command1 && command2`), preferring:

```py
# only "echo 1" and "echo 2" will successfully run; "echo 3" will not
procs = [("echo", "1"), ("echo", "2"), ("false",), ("echo", "3")]
for proc in procs:
    res = subprocess.run(proc, capture_output=True, text=True)
    if res.returncode:
        break
```

whereas we can do

```py
res = Process("echo", 1).and_then("echo", 2).and_then("false").and_then("echo", "3").exec()
print(res.command)     # echo 1 && echo 2 && false && echo 3
print(res.stdout)      # "1\n2\n"
print(res.exit_code)   # 1
print(res.exit_codes)  # [0, 0, 1]  <-- indicating that the first two echo commands exited with 0, then false exited with 1
```

For convenience, a top-level `exec` function is also provided as a wrapper around `Process(...).exec(...)`. In general, `Process(...).exec(...)` should be preferred for clarity. The top-level `exec` function does not support pipes and still requires the arguments to be provided as variadic arguments, rather than as a string.

## Installation

`bombshell` is supported on Python 3.10 and newer and can be easily installed with a package manager such as:

```bash
# using pip
$ pip install bombshell

# using uv
$ uv add bombshell
```

`bombshell` has no other external dependencies (except `typing_extensions`, only on Python 3.10).

## Documentation

### `PipelineError`

An error that is thrown by `CompletedProcess.check()` when the pipeline has errored. It stores the calling process under its `.process` attribute.

```py
try:
    Process("false").exec().check()
except PipelineError as err:
    # err.process == Process("false").exec()
    print(err.process.command)     # "false"
    print(err.process.exit_codes)  # [1]
```

### `ResourceData`

A NamedTuple with the following attributes:

- `real_time` (alias: `rtime`): the real time used by the process (seconds)
- `user_time` (alias: `utime`): the user time used by the process (seconds)
- `system_time` (alias: `stime`): the system time used by the process (seconds)
- `max_resident_set_size` (alias: `maxrss`): the maximum resident set size used by the process (bytes)

> [!NOTE]
> `real_time` (`rtime`) is guaranteed to exist. **On non-Unix systems, the other values will be None as they are not reported by the operating system.** On Unix, they may be None in rare situations where the process is not reaped normally.

Further note that **`max_resident_set_size` is given in bytes on all platforms**. On Linux, this value is natively reported in KiB, but it's converted here for compatibility. Due to the overhead of launching these processes from within Python, in most cases, the reported value will be higher than what /usr/bin/time reports:

```bash
$ uname
Linux

# %M = maximum resident set size in KiB
$ /usr/bin/time -f "%M" sleep 2
2048

# .max_resident_set_size (.maxrss) = maximum in B
# 14,708,736 B = 14,364 KiB
$ uv run python -c "from bombshell import Process; res = Process('sleep', 2).exec(); print(res.resources[0].maxrss)
14708736
```

### `CompletedProcess[S]`

An object that stores the state of a completed process. In particular, its attributes are:

| **attribute** | **type**                      | **description**                                                                                                                                                           |
|---------------|-------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `args`        | `tuple[tuple[str, ...], ...]` | the arguments that were passed to the process(es) that gave this result                                                                                                   |
| `command`     | `str`                         | a string representation of the command as would be run on the command line (formatted for POSIX)                                                                          |
| `exit_codes`  | `list[int]`                   | all of the exit codes for the various processes in the pipeline                                                                                                           |
| `exit_code`   | `int`                         | the exit code of the last executed part of the pipeline (and thus the exit code of the pipeline)                                                                          |
| `stdout`      | `S` (str or bytes)            | the contents of the stdout pipes, if captured. `p1.pipe_into(p2).exec().stdout` will contain only the output of `p2`; `p1.and_then(p2).exec().stdout` will contain both. |
| `stderr`      | `S` (str or bytes)            | the contents of the stderr pipes, if captured. This will always include the combination of all stderr pipes.                                                              |
| `runtime`     | `float`                       | the real (wall) time of the command's execution (seconds) |
| `resources`   | `tuple[ResourceData, ...]`    | a tuple of objects describing the resource usage (real time, user time, system time, memory usage) of each process |
| `total_resources` | `ResourceData`            | an object describing the aggregating resource usage for the entire execution |

```py
res = (
    Process("echo", 1)
    .pipe_into("echo", 2)
    .pipe_into("false")
    .pipe_into("echo", 3)
    .exec()
)

print(res.args)          # (("echo", "1"), ("echo", "2"), ("false",), ("echo", "3"))
print(res.command)       # "echo 1 | echo 2 | false | echo 3"
print(res.exit_codes)    # [0, 0, 1, 0]
print(res.exit_code)     # 0
print(res.stdout)        # "3\n"
print(res.stderr)        # ""

# resources for the individual processes
print(res.resources[0])  # ResourceData(real_time=2.4565961211919785e-05, user_time=0.0, system_time=0.001305, max_resident_set_size=17125376)
print(res.resources[1])  # ResourceData(real_time=5.985284224152565e-05, user_time=0.0, system_time=0.0010999999999999998, max_resident_set_size=17125376)
print(res.resources[2])  # ResourceData(real_time=6.692949682474136e-06, user_time=0.001215, system_time=0.0, max_resident_set_size=17125376)
print(res.resources[3])  # ResourceData(real_time=5.029840394854546e-06, user_time=0.0, system_time=0.0016669999999999999, max_resident_set_size=17125376)

# total resource usage
print(res.runtime)          # 0.005894029047340155
print(res.total_resources)  # ResourceData(real_time=0.005894029047340155, user_time=0.001215, system_time=0.004071999999999999, max_resident_set_size=17125376)
```

This class also defines the following methods:

- `check(*, strict: bool = False)`: Raise PipelineError if the process exited in error. With `strict=True`, any of the processes will trigger the exception; with `strict=False` (the default), only the final process determines whether an exception is raised.

```py
res = (
    Process("echo", 1)
    .pipe_into("echo", 2)
    .pipe_into("false")
    .pipe_into("echo", 3)
    .exec()
)

res.check()             # passes since the final exit code was zero
res.check(strict=True)  # raises PipelineError since there was a failure along the pipeline
```

- `timed_out() -> bool`: Return True if any of the processes timed out (and False otherwise).

```py
res = Process("sleep", 1).exec(timeout=2)
print(res.exit_code)    # 0
print(res.timed_out())  # False

res = Process("sleep", 10).exec(timeout=2)
print(res.exit_code)    # 124
print(res.timed_out())  # True
res.check()             # raises PipelineError
```

- `exit() -> None`: raises SystemExit, exiting the Python process with the same exit code as the process in question.

```bash
$ python3 -c "from bombshell import exec; exec('exit', 17).exit()" ; echo $?
17
```

### Timeouts

`.exec()` takes an optional `timeout` parameter. If provided, it should be a number of seconds that serves as a maximum duration for the command. For command chains (`p.and_then(q).exec(timeout=...)`), the timeout is shared across the entire chain, rather than each process having its own individual timeout.

Note that, unlike `subprocess`, `bombshell` does not use exception flow for timeouts. As shown above, when a timeout occurs, the exit code for offending processes is set to 124 (the standard Unix timeout signal):

```bash
$ timeout 1 sleep 3 ; echo $?
124

$ python -c "from bombshell import exec; exec('sleep', 3, timeout=1).exit()" ; echo $?
124

$ python -c "from bombshell import exec; print(exec('sleep', 3, timeout=1).timed_out())"
True
```

To determine if a timeout has occurred, use `if p.exec().timed_out():`. Note that `p.exec().check()` can raise an exception in the event of a timeout as well since the offending process's exit code is set to a nonzero value. Further note that the process's actual timeout state is observed as a result of the internal execution method: thus,

```py
>>> res = Process("exit", 124).exec()
>>> res.exit_code
124
>>> res.timed_out()
False
```

### `exec`

A top-level function that wraps `Process(...).exec(...)`. The signature is `def exec(*args: str, **kwargs) -> CompletedProcess[S]`. The available kwargs are all of the keyword arguments to `Process.__init__` (`cwd` and `env`) and `.exec` (`stdin`, `capture`, `mode`, `merge_stderr`, `timeout`).

`*args` must still be given as variadic arguments: `exec` does not support single-string commands (à la `shell=True`). Thus, the following are equivalent:

```py
>>> Process("printenv", "FOO", env={"FOO": "7"}).exec(capture=False)
>>> exec("printenv", "FOO", env={"FOO": "7"}, capture=False)
```

In general, the top one (`Process(...).exec(...)`) should be preferred for clarity but the latter may sometimes be preferable in "shell script" types of programs.

### `Process`

A `Process` object takes a command to run as arguments, along with (optionally) an `env` mapping to use for it and a `cwd` parameter. The object defines:

- `exec(self, stdin: S | None = None, *, capture: bool = True, mode: type[S] = str, merge_stderr: bool = False, timeout: float | None = None) -> CompletedProcess[S]`: Run the given command. `S` is either `str` or `bytes` (but must match in all cases). `stdin` is a str/bytes value (not a pipe/file) to pass as stdin to this command. `capture=True` (default) means that stdout and stderr will be captured in the resulting CompletedProcess object. `mode` determines whether the output is of type `str` or `bytes`. If `merge_stderr` is True, then stderr is redirected to stdout (meaning that `exec().stdout` will contain both streams and `.stderr` will be empty). `timeout`, if provided, is the maximum number of seconds to allow the command to run.

- `__call__(...)`: an alias for `.exec(...)`.

- `with_env(self, **kwargs) -> Self`: return a new Process object with the updated environment variables. Note that this updates the current environment, rather than replacing it. In particular, `Process(..., env=env1).with_env(**env2)` will have its environment be equivalent to `{**os.environ, **env1, **env2}`.

- `with_cwd(self, cwd: PathLike[str] | None)`: return a new Process object with the updated working directory.

- `pipe_into(self, *args: Any, env: Mapping[str, str] | None = None) -> Pipeline`: return a new Pipeline object that represents `command1 | command2`. The given `args` can be either a series of values to use as a command (such as `Process("echo", 1).pipe_into("echo", 2)`, equivalent to `echo 1 | echo 2`), or it can be a single `Process` object (such as `Process("echo", 1).pipe_into(Process("echo", 2))`.)

- `and_then(self, *args: Any) -> CommandChain`: return a CommandChain object that represents `command1 && command2`. The given `args` can be either a series of values to use as a command (such as `Process("echo", 1).and_then("echo", 2)`, equivalent to `echo 1 && echo 2`), or it can be a single Process/Pipeline/CommandChain object (such as `Process("echo", 1).and_then(Process("echo", 2))`.)

- `__or__(self, other: Self) -> Pipeline`: an alias for `.pipe_into`, but requires that the other object is a `Process` object.

### `Pipeline`

A `Pipeline` is an object that represents a piped series of commands. It provides the same methods to provide parity with `Process`, though `Pipeline.pipe_into` and `Pipeline.__or__` both support `Pipeline` as an object.

Note that `Pipeline.with_env` and `.with_cwd` will affect the environment variable dict and working directory of all processes in the pipeline.

In practice, it is unlikely that you would create Pipeline objects directly, but rather as `Process(...).pipe_into(...)`.

### `CommandChain`

Like `Pipeline`, this is an object that represents a chained series of commands. It also provides the same methods to provide parity with `Process`.

Note that `CommandChain.with_env` and `.with_cwd` will affect the environment variable dict and working directory of all processes in the chain.

It is unlikely that you would create CommandChain objects directly, but rather as `Process(...).and_then(...)`.
