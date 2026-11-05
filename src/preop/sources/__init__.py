"""Input sources. A new input (for example a robot) only has to implement `Source`."""

from collections.abc import Iterator
from typing import Protocol, TypeVar

T_co = TypeVar("T_co", covariant=True)


class Source(Protocol[T_co]):
    def stream(self) -> Iterator[T_co]:
        """Yield samples until the source ends or `stop()` is called."""
        ...

    def stop(self) -> None: ...
