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
class Spinner:
    message: str
    status: str = "✓"

    def ok(self) -> None:
        self.status = "✓"

    def warn(self) -> None:
        self.status = "!"

    def fail(self) -> None:
        self.status = "✗"

    def set_exit_code(self, exit_code: int) -> None:
        self.status = str(exit_code).zfill(3)


@contextmanager
def spin(
    message: str = "Processing...",
    *,
    chars: Sequence[str] = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏",
    delay: float = 0.1,
    stream: IO[str] = sys.stderr,
    template: str = "[  {char}] {duration} {message}",
    complete_template: str = "[{status:>3}] {duration} {message}",
) -> Iterator[Spinner]:
    """Run a terminal spinner.

    with spin("Processing...") as spinner:
        res = Process("echo", "1").exec()
        spinner.status = str(res.exit_code).zfill(3)

    :arg message: initial message to display
    :arg chars: characters to cycle through
    :arg delay: delay between each character
    :arg stream: stream to write to
    :arg template: template to use for the spinner while it's running
        The available variables are `char` (the current character from `chars`),
        `duration` (the formatted duration as H:MM:SS.f), and `message` (the message).
        The message can be changed mid-run by setting `spinner.message = new_message`.
    :arg complete_template: template to use when the spinner is complete. The available variables are
        `status` (set by `spinner.status`), `duration` (the formatted duration as H:MM:SS.f), and `message`
        (the message).
    """
    event = Event()
    state = Spinner(message)

    def run() -> None:
        start = time.perf_counter()
        symbols = itertools.cycle(chars)
        while not event.is_set():
            env = {
                "char": next(symbols),
                "duration": format_duration(time.perf_counter() - start),
                "message": state.message,
            }

            stream.write(f"\r{template.format(**env)}{CLEAR_LINE}")
            stream.flush()
            event.wait(delay)

        # write final message
        env = {
            "status": state.status,
            "duration": format_duration(time.perf_counter() - start),
            "message": state.message,
        }
        stream.write(f"\r{complete_template.format(**env)}{CLEAR_LINE}\n")
        stream.flush()

    try:
        spin_thread = Thread(target=run, daemon=True)
        spin_thread.start()
        yield state
    finally:
        event.set()
        spin_thread.join()
