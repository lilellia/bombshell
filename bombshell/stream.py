from typing import IO, TypeVar

S = TypeVar("S", str, bytes)


def consume_stream(stream: IO[S], buffer: list[S]) -> None:
    try:
        while block := stream.read():
            buffer.append(block)
    finally:
        stream.close()


def feed_stream(stream: IO[S], content: S) -> None:
    try:
        stream.write(content)
    finally:
        stream.close()
