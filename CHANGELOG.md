# Changelog

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
