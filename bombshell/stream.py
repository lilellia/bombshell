from io import BytesIO, StringIO
from typing import IO, overload, TypeVar

S = TypeVar("S", str, bytes)


def consume_stream(source: IO[S], sink: IO[S]) -> None:
    try:
        while block := source.read():
            sink.write(block)
    finally:
        source.close()


def feed_stream(sink: IO[S], content: S) -> None:
    try:
        sink.write(content)
    finally:
        sink.close()


@overload
def make_buffer(mode: type[str]) -> StringIO: ...


@overload
def make_buffer(mode: type[bytes]) -> BytesIO: ...


def make_buffer(mode: type[S]) -> BytesIO | StringIO:
    return BytesIO() if mode is bytes else StringIO()
