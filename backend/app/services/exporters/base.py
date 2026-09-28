from typing import Protocol


class Exporter(Protocol):
    name: str
    batch_size: int

    def enabled(self) -> bool: ...

    def describe(self) -> str | None: ...

    def ship(self, events: list[dict]) -> None:
        """Deliver the events or raise. Must be safe to call again with the same events."""
