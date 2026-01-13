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
res = bombshell.Process("echo", "1").exec()
print(res.stdout)        # "1\n"
print(type(res.stdout))  # <class 'str'>
```

But if you want bytes, then you can have bytes:

```py
res = bombshell.Process("echo", "1").exec(mode=bytes)
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
res = bombshell.Process("echo", 1).exec()
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
res = bombshell.Process("echo", "hello\nworld\ngoodbye").pipe_into("grep", "l")
print(res.stdout)  # "hello\nworld"

# Process supports .__or__, so we can also do
p1 = bombshell.Process("echo", "hello\nworld\ngoodbye")
p2 = bombshell.Process("grep", "l")
res = (p1 | p2).exec()
print(res.stdout)  # "hello\nworld"
```

We can also pass environment variables to individual commands:

```py
res = subprocess.run(("printenv", "FOO"), capture_output=True, text=True, env={"FOO": "bar"})
print(res.stdout)  # "bar\n"


res = bombshell.Process("printenv", "FOO").with_env(FOO="bar").exec()
print(res.stdout)  # "bar\n"
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
res = bombshell.Process("echo", 1).then("echo", 2).then("false").then("echo", "3")
print(res.command)     # echo 1 && echo 2 && false && echo 3
print(res.stdout)      # "1\n2\n"
print(res.exit_code)   # 1
print(res.exit_codes)  # [0, 0, 1]  <-- indicating that the first two echo commands exited with 0, then false exited with 1
```

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
    bombshell.Process("false").exec().check()
except bombshell.PipelineError as err:
    # err.process == bombshell.Process("false").exec()
    print(err.process.command)     # "false"
    print(err.process.exit_codes)  # [1]
```

### `CompletedProcess[S]`

An object that stores the state of a completed process. In particular, its attributes are:

- `args: tuple[tuple[str, ...], ...]`: the arguments that were passed to the process(es) that gave this result
- `command: str`: a string representation of the command as would be run on the command line
- `exit_codes: list[int]`: all of the exit codes for the various processes in the pipeline
- `exit_code: int`: the exit code of the last executed part of the pipeline (and thus the exit code for the entire pipeline)
- `stdout: str | bytes`: the contents of the stdout pipes, if captured. `.exec(mode=str)` (the default) means that this will be a string; `.exec(mode=bytes)` means this will be a byte string. Note: `(p1 | p2).exec().stdout` will contain only the stdout for `p2`; `p1.then(p2).exec().stdout` will contain both.
- `stderr: str | bytes`: the contents of the stderr pipes, if captured. `.exec(mode=str)` (the default) means that this will be a string; `.exec(mode=bytes)` means this will be a byte string. This will always include the combination of all stderr pipes, if captured.

```py
res = (
    bombshell.Process("echo", 1)
    .pipe_into("echo", 2)
    .pipe_into("false")
    .pipe_into("echo", 3)
    .exec()
)

print(res.args)        # (("echo", "1"), ("echo", "2"), ("false",), ("echo", "3"))
print(res.command)     # "echo 1 | echo 2 | false | echo 3"
print(res.exit_codes)  # [0, 0, 1, 0]
print(res.exit_code)   # 0
print(res.stdout)      # "3\n"
print(res.stderr)      # ""
```

This class also defines a `.check` method:

```py
res = (
    bombshell.Process("echo", 1)
    .pipe_into("echo", 2)
    .pipe_into("false")
    .pipe_into("echo", 3)
    .exec()
)

res.check()             # passes since the final exit code was zero
res.check(strict=True)  # raises PipelineError since there was a failure along the pipeline
```

### `Process`

A `Process` object takes a command to run as arguments, along with (optionally) an `env` mapping to use for it. The object defines:

- `exec(self, stdin: S | None = None, *, capture: bool = True, mode: type[S] = str, merge_stderr: bool = False) -> CompletedProcess[S]`: Run the given command. `S` is either `str` or `bytes` (but must match in all cases). `stdin` is a str/bytes value (not a pipe/file) to pass as stdin to this command. `capture=True` (default) means that stdout and stderr will be captured in the resulting CompletedProcess object. `mode` determines whether the output is of type `str` or `bytes`. If `merge_stderr` is True, then stderr is redirected to stdout (meaning that `exec().stdout` will contain both streams and `.stderr` will be empty).

- `__call__(...)`: an alias for `.exec(...)`.

- `with_env(self, **kwargs) -> Self`: return a new Process object with the updated environment variables. Note that this updates the current environment, rather than replacing it.

- `pipe_into(self, *args: Any, env: Mapping[str, str] = None | None) -> Pipeline`: return a new Pipeline object that represents `command1 | command2`. The given `args` can eithe ra series of values to use as a command (such as `Process("echo", 1).pipe_into("echo", 2)`, equivalent to `echo 1 | echo 2`), or it can be a single `Process` object (such as `Process("echo", 1).pipe_into(Process("echo", 2))`.)

- `__or__(self, other: Self) -> Pipeline`: an alias for `.pipe_into`, but requires that the other object is a `Process` object.

- `then(self, *args: Any) -> CommandChain`: return a CommandChain object that represents `command1 && command2`. The given `args` can be either a series of values to use as a command (such as `Process("echo", 1).then("echo", 2)`, equivalent to `echo 1 && echo 2`), or it can be a single Process/Pipeline/CommandChain object (such as `Process("echo", 1).then(Process("echo", 2)).)

### `Pipeline`

A `Pipeline` is an object that represents a piped series of commands. It provides the same methods to provide parity with `Process`, though `Pipeline.pipe_into` and `Pipeline.__or__` both support `Pipeline` as an object.

In practice, it is unlikely that you would create Pipeline objects directly, but rather as `Process(...).pipe_into(...)`.

### `CommandChain`

Like `Pipeline`, this is an object that represents a chained series of commands. It also provides the same methods to provide parity with `Process`.

It is unlikely that you would create CommandChain objects directly, but rather as `Process(...).then(...)`.
