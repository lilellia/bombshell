# Changelog

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
