"""Tests for schedule logic in the Tisseo coordinator."""
from datetime import datetime, timedelta

import pytest

import custom_components.tisseo.coordinator as coordinator_module
from custom_components.tisseo.coordinator import TOULOUSE_TZ, TisseoStopCoordinator


def _freeze_now(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    """Patch coordinator datetime.now() to return a fixed local time."""

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return now.replace(tzinfo=None)
            return now.astimezone(tz)

    monkeypatch.setattr(coordinator_module, "datetime", FrozenDateTime)


def _make_schedule_coordinator(active_windows: list[dict]) -> TisseoStopCoordinator:
    """Create a coordinator instance with only schedule attributes initialized."""
    coord = object.__new__(TisseoStopCoordinator)
    coord._schedule_enabled = True
    coord._active_windows = active_windows
    coord._is_currently_active = None
    coord.stop_name = "Test stop"
    coord._boundary_timer = None
    return coord


def test_is_in_active_window_disabled_schedule() -> None:
    """Disabled scheduling should always be treated as active."""
    coord = object.__new__(TisseoStopCoordinator)
    coord._schedule_enabled = False
    coord._active_windows = []
    assert coord.is_in_active_window() is True


def test_is_in_active_window_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Current time inside configured window should return True."""
    now = datetime(2026, 1, 5, 7, 30, tzinfo=TOULOUSE_TZ)  # Monday
    _freeze_now(monkeypatch, now)
    coord = _make_schedule_coordinator(
        [{"days": ["mon"], "start": "06:00", "end": "09:30"}]
    )
    assert coord.is_in_active_window() is True


def test_is_in_active_window_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Current time outside configured window should return False."""
    now = datetime(2026, 1, 5, 10, 0, tzinfo=TOULOUSE_TZ)  # Monday
    _freeze_now(monkeypatch, now)
    coord = _make_schedule_coordinator(
        [{"days": ["mon"], "start": "06:00", "end": "09:30"}]
    )
    assert coord.is_in_active_window() is False


def test_seconds_until_next_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Boundary delay should point to the next start/end transition."""
    now = datetime(2026, 1, 5, 8, 0, tzinfo=TOULOUSE_TZ)  # Monday
    _freeze_now(monkeypatch, now)
    coord = _make_schedule_coordinator(
        [{"days": ["mon"], "start": "06:00", "end": "09:30"}]
    )

    seconds = coord._seconds_until_next_boundary()
    assert seconds is not None
    assert 5390 <= seconds <= 5410  # 1h30m


def test_seconds_until_next_boundary_next_week(monkeypatch: pytest.MonkeyPatch) -> None:
    """When all today's boundaries are passed, next match should be in following days."""
    now = datetime(2026, 1, 5, 22, 0, tzinfo=TOULOUSE_TZ)  # Monday
    _freeze_now(monkeypatch, now)
    coord = _make_schedule_coordinator(
        [{"days": ["mon"], "start": "06:00", "end": "09:30"}]
    )

    seconds = coord._seconds_until_next_boundary()
    assert seconds is not None
    assert seconds > timedelta(days=6).total_seconds()


def test_apply_scheduling_mode_transitions() -> None:
    """Mode orchestration should trigger transition method + boundary scheduling."""
    coord = _make_schedule_coordinator([])
    calls: list[str] = []

    coord.is_in_active_window = lambda: True
    coord._enter_active_mode = lambda: calls.append("active")
    coord._enter_inactive_mode = lambda: calls.append("inactive")
    coord._schedule_boundary_timer = lambda: calls.append("timer")

    coord._apply_scheduling_mode()
    assert calls == ["active", "timer"]
