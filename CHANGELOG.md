# Changelog

## v0.8.0

- Improves the internal process wait process by leveraging low-level native process wait mechanisms to bypass the need for the busy-wait `os.wait4` handle. This also grants rusage data on Windows by hooking its native reaping:
  - Linux >=5.3: `pidfd_open` + `wait4`
  - macOS/BSD: `kqueue` + `wait4`
  - Windows: `WaitForSingleObject` + `GetProcessTimes` + `GetProcessMemoryInfo`
  - fallbacks to the pre-existing busy-wait wait4 loop where available (POSIX) and blind `Popen.wait` where not

## v0.7.1

- Adds more general functionality to the `spin` function and promotes it to being a top-level function.
  - Renames `SpinState` to `Spinner`
  - Adds `Spinner.message` field, which allows for changing the message throughout the spinner.
  - Changes `Spinner.exit_code: int` to `Spinner.status: str`, which allows for a more general API.
  - Adds `Spinner.ok()` (sets `status = "✓"`) and `Spinner.fail()` (sets `status = "✗"`),
    as well as `Spinner.set_exit_code(exit_code: int)` (sets `status = str(exit_code).zfill(3)`) for internal use.
  - Adds `template` and `complete_template` keywords to `spin`.

## v0.7.0

- Renames `Process.pipe_into` to `.pipe`.
- Adds `Process.then` as an analogue of shell `P ; Q`.
- Adds `Process.or_else` as an analogue of shell `P || Q`.
- Adds `CompletedProcess.ok` as a return-boolean version of `.check`.

## v0.6.1

- Fixes spinner command output for command chains (`P && Q`).

## v0.6.0

- Adds spinner functionality to `exec` and `Process.exec` via the `with_spinner` parameter.
- Fixes `SyntaxWarning` caused in the internal wait4 fallback function.

## v0.5.1

- Changes `CompletedProcess.exit_codes` to `tuple` instead of `list`.
- Fixes bug in `CompletedProcess.__add__` as to how resource data is combined.

## v0.5.0

- Refactors `Process`, `Pipeline`, `CommandChain` into one polymorphic class, simplifying the API slightly.
- Provides `__add__` for `CompletedProcess` and `ResourceData`.

## v0.4.0

- Adds top-level `bombshell.exec` function that is a wrapper around `Process(...).exec(...)`.
- Changes internal detection for `CompletedProcess.timed_out`. Now uses an explicit flag rather than relying on the exit code being 124.

## v0.3.0

- Adds resource usage data (real time, user time, system time, max rss) to `CompletedProcess`. This is accessible per process via the `.resources` attribute, as well as a total resource usage via `.total_resources`. The real time is also available as a top-level attribute (`.runtime`).

## v0.2.0

- Renames the `.then` method to `.and_then` in order to provide better differentiation between `P && Q` (what this method does) and `P ; Q`.
- Adds timeout functionality.
- Adds `cwd` handling, both as a kw-argument to `Process.__init__` and via `.with_env` methods.
- Adds `with_env` and `with_cwd` as methods on `Pipeline` and `CommandChain`.
- Adds `CompletedProcess.exit`, providing a thin wrapper over `sys.exit(res.exit_code)`.
- Rewrote core tests to be platform-independent, allowing for testing to be performed on Windows as well as POSIX.

## v0.1.1

- Adds `py.typed`, allowing for typing information to be conveyed downstream.

## v0.1.0

- Initial release.
