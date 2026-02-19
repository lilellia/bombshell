from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import itertools
import sys
from threading import Event, Thread
import time
from typing import IO

CLEAR_LINE = "\x1b[K"


def format_duration(duration: float) -> str:
    """Format duration as H:MM:SS.f"""
    minutes, seconds = divmod(duration, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:01.0f}:{minutes:02.0f}:{seconds:04.1f}"


@dataclass
class SpinState:
    exit_code: int = 0


@contextmanager
def spin(
    message: str = "Processing...",
    *,
    chars: Sequence[str] = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏",
    delay: float = 0.1,
    stream: IO[str] = sys.stderr,
) -> Iterator[SpinState]:
    """Run a terminal spinner.

    with spin("Processing...") as state:
        res = Process("echo", "1").exec()
        state.exit_code = res.exit_code
    """
    event = Event()
    state = SpinState()

    def run() -> None:
        start = time.perf_counter()
        symbols = itertools.cycle(chars)
        while not event.is_set():
            duration = format_duration(time.perf_counter() - start)
            stream.write(f"\r[  {next(symbols)}] {duration} {message}{CLEAR_LINE}")
            stream.flush()
            event.wait(delay)

        # write final message
        duration = format_duration(time.perf_counter() - start)
        stream.write(f"\r[{state.exit_code:03}] {duration} {message}{CLEAR_LINE}\n")
        stream.flush()

    try:
        spin_thread = Thread(target=run, daemon=True)
        spin_thread.start()
        yield state
    finally:
        event.set()
        spin_thread.join()
