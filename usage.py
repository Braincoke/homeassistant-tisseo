"""API usage tracking for Tisseo integration."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from .const import (
    API_USAGE_DAILY_RETENTION_DAYS,
    API_USAGE_SAVE_DELAY_SECONDS,
    STORAGE_KEY_API_USAGE,
    STORAGE_VERSION_API_USAGE,
)

TOULOUSE_TZ = ZoneInfo("Europe/Paris")


class TisseoApiUsageTracker:
    """Track API usage across all Tisseo entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the usage tracker."""
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION_API_USAGE,
            STORAGE_KEY_API_USAGE,
        )
        self._save_unsub = None
        self._listeners: set[Callable[[], None]] = set()

        self._total_calls = 0
        self._successful_calls = 0
        self._failed_calls = 0
        self._last_call_at: str | None = None
        self._last_success_at: str | None = None
        self._endpoint_counts: dict[str, int] = {}
        self._daily_counts: dict[str, int] = {}

        self._gtfs_total_calls = 0
        self._gtfs_successful_calls = 0
        self._gtfs_failed_calls = 0
        self._gtfs_last_call_at: str | None = None
        self._gtfs_last_success_at: str | None = None
        self._gtfs_endpoint_counts: dict[str, int] = {}
        self._gtfs_daily_counts: dict[str, int] = {}

    async def async_load(self) -> None:
        """Load persisted usage state."""
        data = await self._store.async_load()
        if not isinstance(data, dict):
            return

        self._total_calls = int(data.get("total_calls", 0))
        self._successful_calls = int(data.get("successful_calls", 0))
        self._failed_calls = int(data.get("failed_calls", 0))
        self._last_call_at = data.get("last_call_at")
        self._last_success_at = data.get("last_success_at")
        self._endpoint_counts = {
            str(key): int(value)
            for key, value in data.get("endpoint_counts", {}).items()
            if isinstance(key, str)
        }
        self._daily_counts = {
            str(key): int(value)
            for key, value in data.get("daily_counts", {}).items()
            if isinstance(key, str)
        }
        self._gtfs_total_calls = int(data.get("gtfs_total_calls", 0))
        self._gtfs_successful_calls = int(data.get("gtfs_successful_calls", 0))
        self._gtfs_failed_calls = int(data.get("gtfs_failed_calls", 0))
        self._gtfs_last_call_at = data.get("gtfs_last_call_at")
        self._gtfs_last_success_at = data.get("gtfs_last_success_at")
        self._gtfs_endpoint_counts = {
            str(key): int(value)
            for key, value in data.get("gtfs_endpoint_counts", {}).items()
            if isinstance(key, str)
        }
        self._gtfs_daily_counts = {
            str(key): int(value)
            for key, value in data.get("gtfs_daily_counts", {}).items()
            if isinstance(key, str)
        }
        self._prune_daily_counts()

    async def async_shutdown(self) -> None:
        """Flush pending state on shutdown."""
        if self._save_unsub is not None:
            self._save_unsub()
            self._save_unsub = None
        await self._async_save()

    @property
    def total_calls(self) -> int:
        """Return total API calls made."""
        return self._total_calls

    @callback
    def record_call(
        self,
        endpoint: str,
        success: bool,
        status: int | None = None,
        source: str = "api",
    ) -> None:
        """Record one real API call."""
        del status  # currently not persisted, kept for callback compatibility
        now = datetime.now(TOULOUSE_TZ)
        day_key = now.date().isoformat()

        if source == "gtfs":
            self._gtfs_total_calls += 1
            if success:
                self._gtfs_successful_calls += 1
                self._gtfs_last_success_at = now.isoformat()
            else:
                self._gtfs_failed_calls += 1

            self._gtfs_last_call_at = now.isoformat()
            self._gtfs_daily_counts[day_key] = self._gtfs_daily_counts.get(day_key, 0) + 1
            self._gtfs_endpoint_counts[endpoint] = self._gtfs_endpoint_counts.get(endpoint, 0) + 1
        else:
            self._total_calls += 1
            if success:
                self._successful_calls += 1
                self._last_success_at = now.isoformat()
            else:
                self._failed_calls += 1

            self._last_call_at = now.isoformat()
            self._daily_counts[day_key] = self._daily_counts.get(day_key, 0) + 1
            self._endpoint_counts[endpoint] = self._endpoint_counts.get(endpoint, 0) + 1

        self._prune_daily_counts()
        self._schedule_save()
        self._notify_listeners()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Add a listener notified on usage updates."""
        self._listeners.add(listener)

        @callback
        def _remove_listener() -> None:
            self._listeners.discard(listener)

        return _remove_listener

    def as_dict(self) -> dict[str, Any]:
        """Return current usage metrics."""
        today_key = datetime.now(TOULOUSE_TZ).date().isoformat()
        recent_days = dict(sorted(self._daily_counts.items(), reverse=True)[:30])
        gtfs_recent_days = dict(sorted(self._gtfs_daily_counts.items(), reverse=True)[:30])
        top_endpoints = dict(
            sorted(self._endpoint_counts.items(), key=lambda item: item[1], reverse=True)[:20]
        )
        gtfs_top_endpoints = dict(
            sorted(self._gtfs_endpoint_counts.items(), key=lambda item: item[1], reverse=True)[:20]
        )
        return {
            # Realtime API metrics (legacy keys kept stable).
            "total_calls": self._total_calls,
            "successful_calls": self._successful_calls,
            "failed_calls": self._failed_calls,
            "today_calls": self._daily_counts.get(today_key, 0),
            "last_call_at": self._last_call_at,
            "last_success_at": self._last_success_at,
            "daily_counts": recent_days,
            "endpoint_counts": top_endpoints,
            # GTFS download/metadata metrics.
            "gtfs_total_calls": self._gtfs_total_calls,
            "gtfs_successful_calls": self._gtfs_successful_calls,
            "gtfs_failed_calls": self._gtfs_failed_calls,
            "gtfs_today_calls": self._gtfs_daily_counts.get(today_key, 0),
            "gtfs_last_call_at": self._gtfs_last_call_at,
            "gtfs_last_success_at": self._gtfs_last_success_at,
            "gtfs_daily_counts": gtfs_recent_days,
            "gtfs_endpoint_counts": gtfs_top_endpoints,
        }

    @callback
    def _schedule_save(self) -> None:
        """Debounce writes to storage."""
        if self._save_unsub is not None:
            return

        self._save_unsub = async_call_later(
            self._hass,
            API_USAGE_SAVE_DELAY_SECONDS,
            self._async_handle_scheduled_save,
        )

    async def _async_handle_scheduled_save(self, _now: Any) -> None:
        """Persist data after debounce delay."""
        self._save_unsub = None
        await self._async_save()

    async def _async_save(self) -> None:
        """Save current usage data to storage."""
        await self._store.async_save(
            {
                "total_calls": self._total_calls,
                "successful_calls": self._successful_calls,
                "failed_calls": self._failed_calls,
                "last_call_at": self._last_call_at,
                "last_success_at": self._last_success_at,
                "endpoint_counts": self._endpoint_counts,
                "daily_counts": self._daily_counts,
                "gtfs_total_calls": self._gtfs_total_calls,
                "gtfs_successful_calls": self._gtfs_successful_calls,
                "gtfs_failed_calls": self._gtfs_failed_calls,
                "gtfs_last_call_at": self._gtfs_last_call_at,
                "gtfs_last_success_at": self._gtfs_last_success_at,
                "gtfs_endpoint_counts": self._gtfs_endpoint_counts,
                "gtfs_daily_counts": self._gtfs_daily_counts,
            }
        )

    @callback
    def _notify_listeners(self) -> None:
        """Notify entities listening for updates."""
        for listener in tuple(self._listeners):
            listener()

    def _prune_daily_counts(self) -> None:
        """Keep only recent daily counts."""
        cutoff = (datetime.now(TOULOUSE_TZ) - timedelta(days=API_USAGE_DAILY_RETENTION_DAYS)).date()
        pruned_api: dict[str, int] = {}
        for day, count in self._daily_counts.items():
            try:
                parsed_day = datetime.fromisoformat(day).date()
            except ValueError:
                continue
            if parsed_day >= cutoff:
                pruned_api[day] = count
        self._daily_counts = pruned_api

        pruned_gtfs: dict[str, int] = {}
        for day, count in self._gtfs_daily_counts.items():
            try:
                parsed_day = datetime.fromisoformat(day).date()
            except ValueError:
                continue
            if parsed_day >= cutoff:
                pruned_gtfs[day] = count
        self._gtfs_daily_counts = pruned_gtfs
