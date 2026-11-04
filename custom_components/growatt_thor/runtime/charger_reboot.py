"""Expected charger reboot after a configuration change answered RebootRequired.

The THOR acknowledges such a change at once and reboots about 30 seconds
later (observed with G_ChargerMode: answer at 20:10:57, reconnect at
20:11:28). A ChangeConfiguration sent into that gap gets no answer and waits
for its 30 s response timeout; a queued Start is discarded when the socket
drops. Until the charger connects again, user writes and Start are refused
with ``charger_rebooting`` instead of being sent into the reboot.

Stop stays allowed: it must never depend on this window. The window ends on
the next connection or after ``REBOOT_WINDOW_SECONDS``, so a charger that does
not reboot is not locked for longer than that.
"""

from __future__ import annotations

REBOOT_WINDOW_SECONDS = 120.0


class ChargerRebootWindow:
    """Monotonic deadline of one expected reboot; owns no timers or I/O."""

    __slots__ = ("_until",)

    def __init__(self) -> None:
        self._until: float | None = None

    def expect(self, now: float) -> None:
        """Start (or restart) the window at loop time ``now``."""
        self._until = now + REBOOT_WINDOW_SECONDS

    @property
    def is_open(self) -> bool:
        """Return whether a window was started and not cleared yet."""
        return self._until is not None

    def clear(self) -> bool:
        """End the window; return whether one was open."""
        was_open = self._until is not None
        self._until = None
        return was_open

    def pending(self, now: float) -> bool:
        """Return whether a reboot is still expected at loop time ``now``."""
        return self._until is not None and now < self._until
