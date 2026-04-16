"""Compensation execution state tracker."""


class _CompensationTracker:
    """Tracks state during compensation execution."""

    __slots__ = ("errors", "executed", "failed", "failed_set", "should_stop", "skipped")

    def __init__(self):
        """Initialise all tracking collections to empty/default state."""
        self.executed: list[str] = []
        self.failed: list[str] = []
        self.skipped: list[str] = []
        self.errors: dict[str, Exception] = {}
        self.failed_set: set[str] = set()
        self.should_stop: bool = False
