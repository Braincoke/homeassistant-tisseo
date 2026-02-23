"""Data coordinator for Tisseo integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dt_time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Departure, Outage, ServiceAlert, StopInfo, TisseoApiClient, TisseoApiError, TisseoAuthError
from .const import (
    CONF_WINDOW_DAYS,
    CONF_WINDOW_END,
    CONF_WINDOW_START,
    COUNTDOWN_UPDATE_INTERVAL,
    DAY_TO_WEEKDAY,
    DEFAULT_MESSAGES_REFRESH_INTERVAL,
    DEFAULT_OUTAGES_REFRESH_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SMART_POST_DEPARTURE_SECONDS,
    SMART_PRE_DEPARTURE_SECONDS,
    UPDATE_STRATEGY_SMART,
    UPDATE_STRATEGY_STATIC,
    UPDATE_STRATEGY_TIME_WINDOW,
)

# Toulouse timezone
TOULOUSE_TZ = ZoneInfo("Europe/Paris")

_LOGGER = logging.getLogger(__name__)


class TisseoStopCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for a single Tisseo stop with smart/static update strategies."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: TisseoApiClient,
        stop_id: str,
        stop_name: str,
        line_id: str | None = None,
        line_color: str | None = None,
        line_text_color: str | None = None,
        route_id: str | None = None,
        update_strategy: str = UPDATE_STRATEGY_SMART,
        static_interval: int = DEFAULT_SCAN_INTERVAL,
        messages_refresh_interval: int = DEFAULT_MESSAGES_REFRESH_INTERVAL,
        outages_refresh_interval: int = DEFAULT_OUTAGES_REFRESH_INTERVAL,
        schedule_enabled: bool = False,
        active_windows: list[dict] | None = None,
        inactive_interval: int = 0,
    ) -> None:
        """Initialize the coordinator."""
        self._client = client
        self.stop_id = stop_id
        self.stop_name = stop_name
        self.line_id = line_id
        self.line_color = line_color
        self.line_text_color = line_text_color
        self.route_id = route_id
        self._update_strategy = update_strategy
        self._static_interval = static_interval
        self._messages_refresh_interval = max(0, int(messages_refresh_interval))
        self._outages_refresh_interval = max(0, int(outages_refresh_interval))

        # Time-window scheduling
        self._schedule_enabled = schedule_enabled
        self._active_windows = active_windows or []
        self._inactive_interval = inactive_interval
        self._boundary_timer: asyncio.TimerHandle | None = None
        self._is_currently_active: bool | None = None  # None = not yet determined

        self.stop_info: StopInfo | None = None
        self.departures: list[Departure] = []
        self.alerts: list[ServiceAlert] = []
        self.outages: list[Outage] = []

        # For smart updates
        self._next_api_call: datetime | None = None
        self._scheduled_refresh: asyncio.TimerHandle | None = None
        self._countdown_unsub: callback | None = None

        # Last API fetch time for countdown interpolation
        self._last_api_fetch: datetime | None = None

        # Alert caching
        self._last_alert_fetch: datetime | None = None
        self._cached_alerts: list[ServiceAlert] = []
        self._previous_alert_ids: set[str] = set()  # Track for new alert detection
        self._new_alerts: list[ServiceAlert] = []  # Alerts that are new since last check

        # Outage caching
        self._last_outage_fetch: datetime | None = None
        self._cached_outages: list[Outage] = []
        self._planned_window_result: dict[str, Any] | None = None

        # Failure tracking for repair issues
        self._consecutive_failures: int = 0
        self._failure_threshold: int = 5  # Create repair issue after 5 consecutive failures
        self._repair_issue_id: str = f"api_failure_{stop_id}"

        # Determine initial update interval
        if update_strategy == UPDATE_STRATEGY_STATIC:
            update_interval = timedelta(seconds=static_interval)
        else:
            # Smart mode: we'll manage updates ourselves, start with one fetch
            update_interval = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{stop_id}",
            update_interval=update_interval,
        )

    async def async_config_entry_first_refresh(self) -> None:
        """Fetch initial data and set up smart scheduling."""
        await super().async_config_entry_first_refresh()

        if self._schedule_enabled:
            # Scheduled mode controls whether we are active or inactive.
            self._apply_scheduling_mode()
        elif self._update_strategy in (UPDATE_STRATEGY_SMART, UPDATE_STRATEGY_TIME_WINDOW):
            # Start countdown timer for display updates
            self._start_countdown_timer()
            # Schedule next smart API call
            self._schedule_next_smart_update()

    @staticmethod
    def _parse_window_time(value: str, fallback: dt_time) -> dt_time:
        """Parse a time string from options (HH:MM or HH:MM:SS)."""
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                continue
        return fallback

    def is_in_active_window(self) -> bool:
        """Check if current local time is inside any configured active window."""
        if not self._schedule_enabled or not self._active_windows:
            return True

        now = datetime.now(TOULOUSE_TZ)
        current_weekday = now.weekday()
        current_time = now.time()

        for window in self._active_windows:
            days = window.get(CONF_WINDOW_DAYS, [])
            day_matches = any(
                DAY_TO_WEEKDAY.get(day) == current_weekday for day in days
            )
            if not day_matches:
                continue

            start_time = self._parse_window_time(
                window.get(CONF_WINDOW_START, "00:00"),
                dt_time(0, 0),
            )
            end_time = self._parse_window_time(
                window.get(CONF_WINDOW_END, "23:59"),
                dt_time(23, 59),
            )

            if start_time <= current_time <= end_time:
                return True

        return False

    def _seconds_until_next_boundary(self) -> float | None:
        """Return seconds until the next active/inactive transition."""
        if not self._schedule_enabled or not self._active_windows:
            return None

        now = datetime.now(TOULOUSE_TZ)
        candidates: list[float] = []

        # Look ahead one week to find the next window start/end.
        for day_offset in range(8):
            check_date = (now + timedelta(days=day_offset)).date()
            check_weekday = check_date.weekday()

            for window in self._active_windows:
                days = window.get(CONF_WINDOW_DAYS, [])
                if not any(DAY_TO_WEEKDAY.get(day) == check_weekday for day in days):
                    continue

                start_time = self._parse_window_time(
                    window.get(CONF_WINDOW_START, "00:00"),
                    dt_time(0, 0),
                )
                end_time = self._parse_window_time(
                    window.get(CONF_WINDOW_END, "23:59"),
                    dt_time(23, 59),
                )

                start_dt = datetime.combine(check_date, start_time, tzinfo=TOULOUSE_TZ)
                end_dt = datetime.combine(check_date, end_time, tzinfo=TOULOUSE_TZ)

                for boundary in (start_dt, end_dt):
                    seconds = (boundary - now).total_seconds()
                    if seconds > 5:
                        candidates.append(seconds)

        return min(candidates) if candidates else None

    def _apply_scheduling_mode(self) -> None:
        """Apply active/inactive mode based on the current schedule state."""
        if not self._schedule_enabled:
            return

        is_active = self.is_in_active_window()
        if self._is_currently_active != is_active:
            if is_active:
                self._enter_active_mode()
            else:
                self._enter_inactive_mode()
            self._is_currently_active = is_active

        self._schedule_boundary_timer()

    def _enter_active_mode(self) -> None:
        """Switch to active mode and resume normal refresh behavior."""
        _LOGGER.info("%s: Entering active window, resuming updates", self.stop_name)

        if self._update_strategy in (UPDATE_STRATEGY_SMART, UPDATE_STRATEGY_TIME_WINDOW):
            if self._scheduled_refresh is not None:
                self._scheduled_refresh.cancel()
                self._scheduled_refresh = None

            # Smart mode is self-scheduled; disable periodic polling.
            self.update_interval = None
            self._start_countdown_timer()
            self.hass.loop.call_soon(
                lambda: asyncio.create_task(self._async_smart_refresh())
            )
            return

        self.update_interval = timedelta(seconds=self._static_interval)
        self._start_countdown_timer()
        self.hass.loop.call_soon(lambda: asyncio.create_task(self.async_refresh()))

    def _enter_inactive_mode(self) -> None:
        """Switch to inactive mode and reduce/disable refresh behavior."""
        _LOGGER.info("%s: Leaving active window, reducing updates", self.stop_name)

        if self._scheduled_refresh is not None:
            self._scheduled_refresh.cancel()
            self._scheduled_refresh = None

        if self._countdown_unsub is not None:
            self._countdown_unsub()
            self._countdown_unsub = None

        if self._inactive_interval > 0:
            self.update_interval = timedelta(seconds=self._inactive_interval)
        else:
            self.update_interval = None

    def _schedule_boundary_timer(self) -> None:
        """Schedule the next timer for active/inactive boundary transition."""
        if self._boundary_timer is not None:
            self._boundary_timer.cancel()
            self._boundary_timer = None

        seconds = self._seconds_until_next_boundary()
        if seconds is None:
            return

        _LOGGER.debug(
            "%s: Next schedule boundary in %.0f seconds",
            self.stop_name,
            seconds,
        )
        self._boundary_timer = self.hass.loop.call_later(
            seconds,
            lambda: asyncio.create_task(self._async_boundary_transition()),
        )

    async def _async_boundary_transition(self) -> None:
        """Handle active/inactive transition at the configured boundary."""
        _LOGGER.debug("%s: Boundary transition fired", self.stop_name)
        self._boundary_timer = None
        self._apply_scheduling_mode()

    def _start_countdown_timer(self) -> None:
        """Start the timer for updating countdown display every 30 seconds."""
        if self._countdown_unsub is not None:
            self._countdown_unsub()

        self._countdown_unsub = async_track_time_interval(
            self.hass,
            self._async_countdown_tick,
            timedelta(seconds=COUNTDOWN_UPDATE_INTERVAL),
        )

    @callback
    def _async_countdown_tick(self, _now: datetime) -> None:
        """Handle countdown tick - notify listeners to update display."""
        # Just notify listeners to re-render with updated countdown
        self.async_set_updated_data(self.data)

    def _schedule_next_smart_update(self) -> None:
        """Schedule the next API call based on departure times."""
        if self._scheduled_refresh is not None:
            self._scheduled_refresh.cancel()
            self._scheduled_refresh = None

        if not self.departures:
            # No departures: retry in 60 seconds
            delay = 60
            _LOGGER.debug(
                "%s: No departures, scheduling API call in %ds",
                self.stop_name,
                delay,
            )
        else:
            # Calculate when to call API next
            next_departure = self.departures[0]
            now = datetime.now(TOULOUSE_TZ)
            departure_time = next_departure.departure_time

            # Time until departure
            seconds_until = (departure_time - now).total_seconds()

            if seconds_until <= 0:
                # Departure already passed, call in POST_DEPARTURE seconds
                delay = SMART_POST_DEPARTURE_SECONDS
                _LOGGER.debug(
                    "%s: Departure passed, scheduling API call in %ds",
                    self.stop_name,
                    delay,
                )
            elif seconds_until <= SMART_PRE_DEPARTURE_SECONDS:
                # We're within the pre-departure window, schedule post-departure
                delay = seconds_until + SMART_POST_DEPARTURE_SECONDS
                _LOGGER.debug(
                    "%s: Within pre-departure window, scheduling in %.1fs",
                    self.stop_name,
                    delay,
                )
            else:
                # Schedule for PRE_DEPARTURE seconds before departure
                delay = seconds_until - SMART_PRE_DEPARTURE_SECONDS
                _LOGGER.debug(
                    "%s: Next departure in %.1fs, scheduling API call in %.1fs",
                    self.stop_name,
                    seconds_until,
                    delay,
                )

        # Ensure minimum delay of 10 seconds
        delay = max(10, delay)

        # Schedule the refresh
        self._scheduled_refresh = self.hass.loop.call_later(
            delay,
            lambda: asyncio.create_task(self._async_smart_refresh()),
        )

    def _clear_failure_state_if_recovered(self) -> None:
        """Reset failure tracking and clear any open repair issue."""
        if self._consecutive_failures > 0:
            self._consecutive_failures = 0
            async_delete_issue(self.hass, DOMAIN, self._repair_issue_id)
            _LOGGER.info(
                "Tisseo API recovered for %s, cleared repair issue",
                self.stop_name,
            )

    def _register_api_failure(self, err: TisseoApiError) -> None:
        """Track API failures and open a repair issue if needed."""
        self._consecutive_failures += 1

        if self._consecutive_failures >= self._failure_threshold:
            async_create_issue(
                self.hass,
                DOMAIN,
                self._repair_issue_id,
                is_fixable=False,
                severity=IssueSeverity.WARNING,
                translation_key="api_failure",
                translation_placeholders={
                    "stop_name": self.stop_name,
                    "failures": str(self._consecutive_failures),
                    "error": str(err),
                },
            )
            _LOGGER.warning(
                "Tisseo API unreachable for %s (%d consecutive failures): %s",
                self.stop_name,
                self._consecutive_failures,
                err,
            )

    async def async_refresh_departures_only(self) -> None:
        """Refresh only departures (one API call) for manual button usage."""
        try:
            self.departures = await self._client.get_departures(
                stop_id=self.stop_id,
                line_id=self.line_id,
                route_id=self.route_id,
                number=10,
            )
            self._last_api_fetch = datetime.now(TOULOUSE_TZ)
            self._clear_failure_state_if_recovered()

            self.async_set_updated_data(
                {
                    "stop_info": self.stop_info,
                    "departures": self.departures,
                    "next_departure": self.departures[0] if self.departures else None,
                    "alerts": self.alerts,
                    "new_alerts": self._new_alerts,
                    "outages": self.outages,
                    "planned_window": self._planned_window_result,
                    "last_api_fetch": self._last_api_fetch,
                    "last_alert_fetch": self._last_alert_fetch,
                    "last_outage_fetch": self._last_outage_fetch,
                }
            )

            if self._update_strategy in (UPDATE_STRATEGY_SMART, UPDATE_STRATEGY_TIME_WINDOW):
                if not self._schedule_enabled or self.is_in_active_window():
                    self._schedule_next_smart_update()
        except TisseoAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Tisseo API authentication failed: {err}"
            ) from err
        except TisseoApiError as err:
            self._register_api_failure(err)
            raise UpdateFailed(f"Error communicating with Tisseo API: {err}") from err

    async def async_fetch_planned_departures(
        self,
        start_datetime: datetime,
        end_datetime: datetime,
        *,
        number: int = 40,
        display_realtime: bool = False,
        store_result: bool = True,
    ) -> dict[str, Any]:
        """Fetch departures for a future time window and optionally store the result."""
        try:
            departures = await self._client.get_departures(
                stop_id=self.stop_id,
                line_id=self.line_id,
                route_id=self.route_id,
                number=number,
                query_datetime=start_datetime,
                display_realtime=display_realtime,
            )

            filtered_departures = [
                dep
                for dep in departures
                if start_datetime <= dep.departure_time <= end_datetime
            ]

            result = {
                "stop_id": self.stop_id,
                "stop_name": self.stop_name,
                "line_id": self.line_id,
                "route_id": self.route_id,
                "window_start": start_datetime.isoformat(),
                "window_end": end_datetime.isoformat(),
                "fetched_at": datetime.now(TOULOUSE_TZ).isoformat(),
                "display_realtime": display_realtime,
                "count": len(filtered_departures),
                "total_candidates": len(departures),
                "departures": [
                    {
                        "line_short_name": dep.line_short_name,
                        "line_name": dep.line_name,
                        "line_color": dep.line_color or self.line_color or "#808080",
                        "line_text_color": dep.line_text_color or self.line_text_color or "#FFFFFF",
                        "destination": dep.destination,
                        "departure_time": dep.departure_time.isoformat(),
                        "waiting_time": dep.waiting_time,
                        "is_realtime": dep.is_realtime,
                        "transport_mode": dep.transport_mode,
                    }
                    for dep in filtered_departures
                ],
            }

            if store_result:
                self._planned_window_result = result
                updated_data = dict(self.data or {})
                updated_data["planned_window"] = result
                self.async_set_updated_data(updated_data)

            return result
        except TisseoAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Tisseo API authentication failed: {err}"
            ) from err
        except TisseoApiError as err:
            self._register_api_failure(err)
            raise UpdateFailed(f"Error communicating with Tisseo API: {err}") from err

    async def _async_smart_refresh(self) -> None:
        """Perform a smart refresh and schedule the next one."""
        try:
            await self.async_refresh()
        except Exception as err:
            _LOGGER.error("Error during smart refresh: %s", err)
        finally:
            if self._schedule_enabled and not self.is_in_active_window():
                self._apply_scheduling_mode()
            else:
                self._schedule_next_smart_update()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Tisseo API."""
        try:
            # Get stop info if we don't have it yet
            if self.stop_info is None:
                self.stop_info = await self._client.get_stop_info(self.stop_id)
                _LOGGER.debug("Got stop info: %s", self.stop_info)

            # Get departures (filtered by line/route if specified)
            self.departures = await self._client.get_departures(
                stop_id=self.stop_id,
                line_id=self.line_id,
                route_id=self.route_id,
                number=10,
            )
            if self.departures:
                # Backfill static line colors for legacy entries created before
                # line colors were persisted in config entry data.
                if not self.line_color:
                    self.line_color = self.departures[0].line_color
                if not self.line_text_color:
                    self.line_text_color = self.departures[0].line_text_color
            _LOGGER.debug(
                "Got %d departures for %s", len(self.departures), self.stop_name
            )

            now = datetime.now(TOULOUSE_TZ)
            should_fetch_alerts = (
                self._messages_refresh_interval > 0
                and (
                    self._last_alert_fetch is None
                    or (now - self._last_alert_fetch).total_seconds()
                    >= self._messages_refresh_interval
                )
            )
            if should_fetch_alerts:
                try:
                    fetched_alerts = await self._client.get_messages(
                        line_id=self.line_id,
                    )
                    _LOGGER.debug(
                        "Fetched %d alerts for %s", len(fetched_alerts), self.stop_name
                    )

                    # Detect new alerts
                    current_alert_ids = {alert.id for alert in fetched_alerts}
                    new_alert_ids = current_alert_ids - self._previous_alert_ids

                    if new_alert_ids:
                        self._new_alerts = [
                            alert for alert in fetched_alerts
                            if alert.id in new_alert_ids
                        ]
                        _LOGGER.info(
                            "New alerts detected for %s: %s",
                            self.stop_name,
                            [a.title for a in self._new_alerts]
                        )
                    else:
                        self._new_alerts = []

                    # Update cache
                    self._cached_alerts = fetched_alerts
                    self._previous_alert_ids = current_alert_ids
                    self._last_alert_fetch = now

                except Exception as err:
                    _LOGGER.warning("Failed to fetch alerts: %s", err)
                    # Keep cached alerts on error
            else:
                if self._messages_refresh_interval <= 0:
                    _LOGGER.debug(
                        "Messages refresh disabled for %s; reusing cached alerts",
                        self.stop_name,
                    )
                else:
                    _LOGGER.debug(
                        "Using cached alerts for %s (%d alerts)",
                        self.stop_name,
                        len(self._cached_alerts),
                    )

            should_fetch_outages = (
                self._outages_refresh_interval > 0
                and (
                    self._last_outage_fetch is None
                    or (now - self._last_outage_fetch).total_seconds()
                    >= self._outages_refresh_interval
                )
            )
            if should_fetch_outages:
                try:
                    fetched_outages = await self._client.get_outages(
                        line_id=self.line_id,
                    )
                    self._cached_outages = fetched_outages
                    self._last_outage_fetch = now
                    _LOGGER.debug(
                        "Fetched %d outages for %s",
                        len(fetched_outages), self.stop_name
                    )
                except Exception as err:
                    _LOGGER.warning("Failed to fetch outages: %s", err)
                    # Keep cached outages on error
            else:
                if self._outages_refresh_interval <= 0:
                    _LOGGER.debug(
                        "Outages refresh disabled for %s; reusing cached outages",
                        self.stop_name,
                    )
                else:
                    _LOGGER.debug(
                        "Using cached outages for %s (%d outages)",
                        self.stop_name,
                        len(self._cached_outages),
                    )

            self.alerts = self._cached_alerts
            self.outages = self._cached_outages

            # Record when we fetched from API
            self._last_api_fetch = now

            # Success — reset failure counter and clear any repair issue
            self._clear_failure_state_if_recovered()

            return {
                "stop_info": self.stop_info,
                "departures": self.departures,
                "next_departure": self.departures[0] if self.departures else None,
                "alerts": self.alerts,
                "new_alerts": self._new_alerts,
                "outages": self.outages,
                "planned_window": self._planned_window_result,
                "last_api_fetch": self._last_api_fetch,
                "last_alert_fetch": self._last_alert_fetch,
                "last_outage_fetch": self._last_outage_fetch,
            }

        except TisseoAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Tisseo API authentication failed: {err}"
            ) from err
        except TisseoApiError as err:
            self._register_api_failure(err)
            raise UpdateFailed(f"Error communicating with Tisseo API: {err}") from err

    async def async_shutdown(self) -> None:
        """Clean up on shutdown."""
        if self._scheduled_refresh is not None:
            self._scheduled_refresh.cancel()
            self._scheduled_refresh = None

        if self._boundary_timer is not None:
            self._boundary_timer.cancel()
            self._boundary_timer = None

        if self._countdown_unsub is not None:
            self._countdown_unsub()
            self._countdown_unsub = None

        # Clear any repair issue for this stop
        async_delete_issue(self.hass, DOMAIN, self._repair_issue_id)

        await super().async_shutdown()
