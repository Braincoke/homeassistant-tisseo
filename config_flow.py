"""Config flow for Tisseo integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    ObjectSelector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import TisseoApiClient, TisseoApiError, TisseoAuthError
from .const import (
    CONF_ACTIVE_WINDOWS,
    CONF_API_KEY,
    CONF_DEBUG,
    CONF_IMMINENT_THRESHOLD,
    CONF_INACTIVE_INTERVAL,
    CONF_LINE,
    CONF_LINE_COLOR,
    CONF_LINE_NAME,
    CONF_LINE_TEXT_COLOR,
    CONF_MESSAGES_REFRESH_INTERVAL,
    CONF_OUTAGES_REFRESH_INTERVAL,
    CONF_ROUTE,
    CONF_ROUTE_DIRECTION,
    CONF_SCHEDULE_ENABLED,
    CONF_STATIC_INTERVAL,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_TRANSPORT_MODE,
    CONF_UPDATE_STRATEGY,
    CONF_USE_MOCK,
    CONF_WINDOW_DAYS,
    CONF_WINDOW_END,
    CONF_WINDOW_NAME,
    CONF_WINDOW_START,
    DAYS_OF_WEEK,
    DEFAULT_INACTIVE_INTERVAL,
    DEFAULT_IMMINENT_THRESHOLD,
    DEFAULT_MESSAGES_REFRESH_INTERVAL,
    DEFAULT_OUTAGES_REFRESH_INTERVAL,
    DEFAULT_STATIC_INTERVAL,
    DEFAULT_UPDATE_STRATEGY,
    DOMAIN,
    UPDATE_STRATEGY_SMART,
    UPDATE_STRATEGY_STATIC,
    UPDATE_STRATEGY_TIME_WINDOW,
)

_LOGGER = logging.getLogger(__name__)
HUB_ENTRY_TITLE = "Tisseo API Usage"

SCHEDULE_WINDOW_DAY_OPTIONS: list[dict[str, str]] = [
    {"value": day["value"], "label": day["label"]} for day in DAYS_OF_WEEK
]
SCHEDULE_WINDOW_DAY_VALUES: set[str] = {day["value"] for day in DAYS_OF_WEEK}


def _normalize_time_value(value: str | None) -> str | None:
    """Normalize selector values to HH:MM for storage/comparison."""
    if not value:
        return None
    return value[:5] if len(value) >= 5 else None


def _time_to_minutes(value: str) -> int:
    """Convert HH:MM to minutes since midnight."""
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _clean_window_name(value: str | None) -> str | None:
    """Normalize a user-provided window name."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _build_strategy_options() -> list[dict[str, str]]:
    """Build selector options for update strategy."""
    return [
        {"value": UPDATE_STRATEGY_STATIC, "label": "Regular updates (fixed interval)"},
        {"value": UPDATE_STRATEGY_SMART, "label": "Smart updates (departure-based)"},
        {"value": UPDATE_STRATEGY_TIME_WINDOW, "label": "Time windows (smart updates in windows)"},
    ]


def _strategy_label(strategy: str) -> str:
    """Return a human-readable strategy label."""
    for option in _build_strategy_options():
        if option["value"] == strategy:
            return option["label"]
    return strategy


def _format_window(window: dict[str, Any], index: int) -> str:
    """Format a single window for display."""
    day_map = {day["value"]: day["label"][:3] for day in DAYS_OF_WEEK}
    days = window.get(CONF_WINDOW_DAYS, [])
    days_label = ", ".join(day_map.get(day, day) for day in days)
    start = window.get(CONF_WINDOW_START, "??:??")
    end = window.get(CONF_WINDOW_END, "??:??")
    name = window.get(CONF_WINDOW_NAME)
    if name:
        return f"{index}. {name}: {days_label} {start}-{end}"
    return f"{index}. {days_label} {start}-{end}"


def _format_windows_summary(windows: list[dict[str, Any]]) -> str:
    """Format all windows for descriptions."""
    if not windows:
        return "None"
    return " | ".join(_format_window(window, i + 1) for i, window in enumerate(windows))


def _build_windows_selector() -> ObjectSelector:
    """Build the object selector used to edit all windows in one place."""
    return ObjectSelector(
        {
            "multiple": True,
            "label_field": CONF_WINDOW_DAYS,
            "description_field": CONF_WINDOW_START,
            "fields": {
                CONF_WINDOW_NAME: {
                    "required": False,
                    "selector": {"text": None},
                },
                CONF_WINDOW_DAYS: {
                    "required": True,
                    "selector": {
                        "select": {
                            "options": SCHEDULE_WINDOW_DAY_OPTIONS,
                            "mode": "list",
                            "multiple": True,
                        }
                    },
                },
                CONF_WINDOW_START: {
                    "required": True,
                    "selector": {"time": None},
                },
                CONF_WINDOW_END: {
                    "required": True,
                    "selector": {"time": None},
                },
            },
        }
    )


def _normalize_windows(raw_windows: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Validate and normalize window definitions coming from the object selector."""
    if raw_windows is None:
        return [], None

    if not isinstance(raw_windows, list):
        raw_windows = [raw_windows]

    normalized: list[dict[str, Any]] = []

    for raw_window in raw_windows:
        if not isinstance(raw_window, dict):
            return [], "window_definition_invalid"

        name = _clean_window_name(raw_window.get(CONF_WINDOW_NAME))
        raw_days = raw_window.get(CONF_WINDOW_DAYS, [])
        if not isinstance(raw_days, list):
            return [], "window_days_required"

        days: list[str] = []
        for day in raw_days:
            if isinstance(day, str) and day in SCHEDULE_WINDOW_DAY_VALUES:
                if day not in days:
                    days.append(day)

        if not days:
            return [], "window_days_required"

        start = _normalize_time_value(raw_window.get(CONF_WINDOW_START))
        end = _normalize_time_value(raw_window.get(CONF_WINDOW_END))

        if not start or not end:
            return [], "invalid_time_range"

        if _time_to_minutes(start) >= _time_to_minutes(end):
            return [], "invalid_time_range"

        window: dict[str, Any] = {
            CONF_WINDOW_DAYS: days,
            CONF_WINDOW_START: start,
            CONF_WINDOW_END: end,
        }
        if name:
            window[CONF_WINDOW_NAME] = name

        normalized.append(window)

    return normalized, None


class TisseoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tisseo.

    Each config entry represents one bus stop (like Météo-France pattern).
    The wizard guides: API setup -> Transport mode -> Line -> Direction -> Stop -> Options
    """

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._client: TisseoApiClient | None = None
        self._api_key: str | None = None
        self._use_mock: bool = False
        self._debug: bool = False
        self._update_strategy: str = DEFAULT_UPDATE_STRATEGY
        self._static_interval: int = DEFAULT_STATIC_INTERVAL
        self._transport_mode: str | None = None
        self._transport_mode_name: str | None = None
        self._line_id: str | None = None
        self._line_name: str | None = None
        self._line_color: str | None = None
        self._line_text_color: str | None = None
        self._route_id: str | None = None
        self._route_direction: str | None = None
        self._stop_id: str | None = None
        self._stop_name: str | None = None
        self._imminent_threshold: int = DEFAULT_IMMINENT_THRESHOLD
        self._active_windows: list[dict[str, Any]] = []
        self._inactive_interval: int = DEFAULT_INACTIVE_INTERVAL
        self._messages_refresh_interval: int = DEFAULT_MESSAGES_REFRESH_INTERVAL
        self._outages_refresh_interval: int = DEFAULT_OUTAGES_REFRESH_INTERVAL

    def _get_client(self) -> TisseoApiClient:
        """Get or create an API client."""
        if self._client is None:
            self._client = TisseoApiClient(
                api_key=self._api_key,
                use_mock=self._use_mock,
                debug=self._debug,
            )
        return self._client

    async def _async_close_client(self) -> None:
        """Close the API client if it exists."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def _async_create_config_entry(
        self,
        *,
        schedule_enabled: bool,
        active_windows: list[dict[str, Any]],
        inactive_interval: int,
    ) -> ConfigFlowResult:
        """Create the final config entry and close transient client."""
        await self._async_close_client()

        title = (
            f"Tisseo {self._transport_mode_name} {self._line_name} - "
            f"{self._stop_name} (-> {self._route_direction})"
        )

        unique_id = f"{self._stop_id}_{self._line_id}_{self._route_id}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=title,
            data={
                CONF_API_KEY: self._api_key,
                CONF_USE_MOCK: self._use_mock,
                CONF_DEBUG: self._debug,
                CONF_UPDATE_STRATEGY: self._update_strategy,
                CONF_STATIC_INTERVAL: self._static_interval,
                CONF_STOP_ID: self._stop_id,
                CONF_STOP_NAME: self._stop_name,
                CONF_LINE: self._line_id,
                CONF_LINE_NAME: self._line_name,
                CONF_LINE_COLOR: self._line_color,
                CONF_LINE_TEXT_COLOR: self._line_text_color,
                CONF_ROUTE: self._route_id,
                CONF_ROUTE_DIRECTION: self._route_direction,
                CONF_TRANSPORT_MODE: self._transport_mode_name,
                CONF_IMMINENT_THRESHOLD: self._imminent_threshold,
                CONF_MESSAGES_REFRESH_INTERVAL: self._messages_refresh_interval,
                CONF_OUTAGES_REFRESH_INTERVAL: self._outages_refresh_interval,
                CONF_SCHEDULE_ENABLED: schedule_enabled,
                CONF_ACTIVE_WINDOWS: active_windows,
                CONF_INACTIVE_INTERVAL: inactive_interval,
            },
        )

    async def _async_create_hub_entry(
        self,
        *,
        schedule_enabled: bool,
        active_windows: list[dict[str, Any]],
        inactive_interval: int,
    ) -> ConfigFlowResult:
        """Create the dedicated global hub entry (API usage + shared settings)."""
        await self._async_close_client()
        await self.async_set_unique_id("tisseo_api_usage_hub")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=HUB_ENTRY_TITLE,
            data={
                CONF_API_KEY: self._api_key,
                CONF_USE_MOCK: self._use_mock,
                CONF_DEBUG: self._debug,
                CONF_UPDATE_STRATEGY: self._update_strategy,
                CONF_STATIC_INTERVAL: self._static_interval,
                CONF_MESSAGES_REFRESH_INTERVAL: self._messages_refresh_interval,
                CONF_OUTAGES_REFRESH_INTERVAL: self._outages_refresh_interval,
                CONF_SCHEDULE_ENABLED: schedule_enabled,
                CONF_ACTIVE_WINDOWS: active_windows,
                CONF_INACTIVE_INTERVAL: inactive_interval,
            },
        )

    def _get_global_entry(self) -> ConfigEntry | None:
        """Return the dedicated global entry if present, otherwise first entry."""
        entries = self._async_current_entries()
        for entry in entries:
            if CONF_STOP_ID not in entry.data:
                return entry
        return entries[0] if entries else None

    def _get_existing_schedule_settings(self) -> tuple[list[dict[str, Any]], int]:
        """Get schedule settings from an existing entry if available."""
        entry = self._get_global_entry()
        if entry is not None:
            windows = entry.options.get(
                CONF_ACTIVE_WINDOWS,
                entry.data.get(CONF_ACTIVE_WINDOWS, []),
            )
            inactive = int(
                entry.options.get(
                    CONF_INACTIVE_INTERVAL,
                    entry.data.get(CONF_INACTIVE_INTERVAL, DEFAULT_INACTIVE_INTERVAL),
                )
            )
            return windows, inactive
        return [], DEFAULT_INACTIVE_INTERVAL

    def _get_existing_credentials(self) -> tuple[str | None, bool, bool]:
        """Get API credentials from an existing entry if available."""
        entry = self._get_global_entry()
        if entry is not None and (
            entry.data.get(CONF_API_KEY) or entry.data.get(CONF_USE_MOCK)
        ):
            return (
                entry.data.get(CONF_API_KEY),
                entry.data.get(CONF_USE_MOCK, False),
                entry.data.get(CONF_DEBUG, False),
            )
        return None, False, False

    def _get_existing_settings(self) -> tuple[str, int, int, int]:
        """Get update settings from an existing entry if available."""
        entry = self._get_global_entry()
        if entry is not None:
            return (
                entry.options.get(
                    CONF_UPDATE_STRATEGY,
                    entry.data.get(CONF_UPDATE_STRATEGY, DEFAULT_UPDATE_STRATEGY),
                ),
                entry.options.get(
                    CONF_STATIC_INTERVAL,
                    entry.data.get(CONF_STATIC_INTERVAL, DEFAULT_STATIC_INTERVAL),
                ),
                int(
                    entry.options.get(
                        CONF_MESSAGES_REFRESH_INTERVAL,
                        entry.data.get(
                            CONF_MESSAGES_REFRESH_INTERVAL,
                            DEFAULT_MESSAGES_REFRESH_INTERVAL,
                        ),
                    )
                ),
                int(
                    entry.options.get(
                        CONF_OUTAGES_REFRESH_INTERVAL,
                        entry.data.get(
                            CONF_OUTAGES_REFRESH_INTERVAL,
                            DEFAULT_OUTAGES_REFRESH_INTERVAL,
                        ),
                    )
                ),
            )
        return (
            DEFAULT_UPDATE_STRATEGY,
            DEFAULT_STATIC_INTERVAL,
            DEFAULT_MESSAGES_REFRESH_INTERVAL,
            DEFAULT_OUTAGES_REFRESH_INTERVAL,
        )

    def _is_stop_already_configured(self, stop_id: str, line_id: str, route_id: str) -> bool:
        """Check if this specific stop+line+route combination is already configured."""
        entries = self._async_current_entries()
        for entry in entries:
            if (
                entry.data.get(CONF_STOP_ID) == stop_id
                and entry.data.get(CONF_LINE) == line_id
                and entry.data.get(CONF_ROUTE) == route_id
            ):
                return True
        return False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - configure API access or use existing credentials."""
        errors: dict[str, str] = {}

        # Check if we already have credentials from another entry
        existing_api_key, existing_use_mock, existing_debug = self._get_existing_credentials()
        has_dedicated_hub_entry = any(
            CONF_STOP_ID not in entry.data for entry in self._async_current_entries()
        )

        if existing_api_key or existing_use_mock:
            # Reuse existing credentials, skip to transport mode selection
            self._api_key = existing_api_key
            self._use_mock = existing_use_mock
            self._debug = existing_debug
            (
                self._update_strategy,
                self._static_interval,
                self._messages_refresh_interval,
                self._outages_refresh_interval,
            ) = self._get_existing_settings()
            self._active_windows, self._inactive_interval = self._get_existing_schedule_settings()

            if not has_dedicated_hub_entry:
                schedule_enabled = self._update_strategy == UPDATE_STRATEGY_TIME_WINDOW
                return await self._async_create_hub_entry(
                    schedule_enabled=schedule_enabled,
                    active_windows=self._active_windows if schedule_enabled else [],
                    inactive_interval=(
                        self._inactive_interval
                        if schedule_enabled
                        else DEFAULT_INACTIVE_INTERVAL
                    ),
                )
            return await self.async_step_transport_mode()

        form_use_mock = self._use_mock
        form_debug = self._debug
        form_update_strategy = self._update_strategy
        form_static_interval = self._static_interval
        form_messages_refresh_interval = self._messages_refresh_interval
        form_outages_refresh_interval = self._outages_refresh_interval

        # First entry - need to configure API access
        if user_input is not None:
            submitted_api_key = user_input.get(CONF_API_KEY)
            if isinstance(submitted_api_key, str):
                submitted_api_key = submitted_api_key.strip()
            api_key_to_use = submitted_api_key or self._api_key

            form_use_mock = bool(user_input.get(CONF_USE_MOCK, self._use_mock))
            form_debug = bool(user_input.get(CONF_DEBUG, self._debug))
            form_update_strategy = user_input.get(
                CONF_UPDATE_STRATEGY, self._update_strategy
            )
            form_static_interval = int(
                user_input.get(CONF_STATIC_INTERVAL, self._static_interval)
            )
            form_messages_refresh_interval = int(
                user_input.get(
                    CONF_MESSAGES_REFRESH_INTERVAL,
                    self._messages_refresh_interval,
                )
            )
            form_outages_refresh_interval = int(
                user_input.get(
                    CONF_OUTAGES_REFRESH_INTERVAL,
                    self._outages_refresh_interval,
                )
            )

            self._use_mock = form_use_mock
            self._api_key = api_key_to_use
            self._debug = form_debug

            if not self._use_mock and not self._api_key:
                errors["base"] = "api_key_required"
            else:
                # Validate API key if provided
                if self._api_key and not self._use_mock:
                    client = TisseoApiClient(api_key=self._api_key, use_mock=False)
                    try:
                        await client.search_stops("Capitole")
                    except TisseoAuthError:
                        errors["base"] = "invalid_auth"
                    except TisseoApiError:
                        errors["base"] = "cannot_connect"
                    finally:
                        await client.close()

                if not errors:
                    # Store global settings and create the dedicated hub entry.
                    self._update_strategy = form_update_strategy
                    self._static_interval = form_static_interval
                    self._messages_refresh_interval = form_messages_refresh_interval
                    self._outages_refresh_interval = form_outages_refresh_interval

                    if (
                        self._update_strategy == UPDATE_STRATEGY_STATIC
                        and CONF_STATIC_INTERVAL not in user_input
                    ):
                        pass
                    elif self._update_strategy == UPDATE_STRATEGY_TIME_WINDOW:
                        return await self.async_step_schedule()
                    else:
                        return await self._async_create_hub_entry(
                            schedule_enabled=False,
                            active_windows=[],
                            inactive_interval=DEFAULT_INACTIVE_INTERVAL,
                        )

        # Show the API configuration form
        strategy_options = _build_strategy_options()

        schema_dict: dict[Any, Any] = {
            vol.Optional(CONF_API_KEY): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_USE_MOCK, default=form_use_mock): bool,
            vol.Optional(
                CONF_UPDATE_STRATEGY, default=form_update_strategy
            ): SelectSelector(
                SelectSelectorConfig(
                    options=strategy_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_MESSAGES_REFRESH_INTERVAL,
                default=form_messages_refresh_interval,
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=3600,
                    step=30,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_OUTAGES_REFRESH_INTERVAL,
                default=form_outages_refresh_interval,
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=3600,
                    step=30,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(CONF_DEBUG, default=form_debug): bool,
        }

        if form_update_strategy == UPDATE_STRATEGY_STATIC:
            schema_dict[
                vol.Optional(
                    CONF_STATIC_INTERVAL,
                    default=form_static_interval,
                )
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=30,
                    max=300,
                    step=10,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.SLIDER,
                )
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure global time windows when time-window strategy is selected."""
        errors: dict[str, str] = {}
        form_inactive_interval = self._inactive_interval
        form_windows = self._active_windows

        if user_input is not None:
            form_inactive_interval = int(
                user_input.get(CONF_INACTIVE_INTERVAL, self._inactive_interval)
            )
            raw_windows = user_input.get(CONF_ACTIVE_WINDOWS, [])
            form_windows = raw_windows if isinstance(raw_windows, list) else []
            windows, error = _normalize_windows(raw_windows)

            if error:
                errors["base"] = error
            elif not windows:
                errors["base"] = "no_windows_configured"
            else:
                self._inactive_interval = form_inactive_interval
                self._active_windows = windows
                return await self._async_create_hub_entry(
                    schedule_enabled=True,
                    active_windows=windows,
                    inactive_interval=form_inactive_interval,
                )

        return self.async_show_form(
            step_id="schedule",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_INACTIVE_INTERVAL,
                        default=form_inactive_interval,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=3600,
                            step=60,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_ACTIVE_WINDOWS,
                        default=form_windows,
                    ): _build_windows_selector(),
                }
            ),
            errors=errors,
            description_placeholders={
                "windows": _format_windows_summary(form_windows),
            },
        )

    async def async_step_transport_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Select transport mode."""
        errors: dict[str, str] = {}

        # Get available transport modes
        client = self._get_client()
        try:
            modes = await client.get_transport_modes()
        except TisseoApiError:
            modes = []

        if not modes:
            await self._async_close_client()
            return self.async_abort(reason="no_transport_modes")

        if user_input is not None:
            self._transport_mode = user_input.get(CONF_TRANSPORT_MODE)
            if self._transport_mode:
                # Store the transport mode name for later use
                for mode in modes:
                    if mode.id == self._transport_mode:
                        self._transport_mode_name = mode.name
                        break
                return await self.async_step_line()
            errors["base"] = "mode_required"

        # Build options for selector
        mode_options = [
            {"value": mode.id, "label": mode.name}
            for mode in modes
        ]

        data_schema = vol.Schema(
            {
                vol.Required(CONF_TRANSPORT_MODE): SelectSelector(
                    SelectSelectorConfig(
                        options=mode_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="transport_mode",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_line(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: Select line."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._line_id = user_input.get(CONF_LINE)
            if self._line_id:
                # Store line name for later
                client = self._get_client()
                lines = await client.get_lines(self._transport_mode)
                for line in lines:
                    if line.id == self._line_id:
                        self._line_name = line.short_name
                        self._line_color = line.color
                        self._line_text_color = line.text_color
                        break
                return await self.async_step_route()
            errors["base"] = "line_required"

        # Get lines for selected transport mode
        client = self._get_client()
        try:
            lines = await client.get_lines(self._transport_mode)
        except TisseoApiError:
            lines = []

        if not lines:
            await self._async_close_client()
            return self.async_abort(reason="no_lines")

        # Build options for selector
        line_options = [
            {"value": line.id, "label": f"{line.short_name} - {line.name}"}
            for line in lines
        ]

        data_schema = vol.Schema(
            {
                vol.Required(CONF_LINE): SelectSelector(
                    SelectSelectorConfig(
                        options=line_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="line",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_route(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 4: Select route/direction."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._route_id = user_input.get(CONF_ROUTE)
            if self._route_id:
                # Store direction for display name
                client = self._get_client()
                routes = await client.get_routes(self._line_id)
                for route in routes:
                    if route.id == self._route_id:
                        self._route_direction = route.direction
                        break
                return await self.async_step_stop()
            errors["base"] = "route_required"

        # Get routes for selected line
        client = self._get_client()
        try:
            routes = await client.get_routes(self._line_id)
        except TisseoApiError:
            routes = []

        if not routes:
            await self._async_close_client()
            return self.async_abort(reason="no_routes")

        # Build options for selector
        route_options = [
            {"value": route.id, "label": route.name}
            for route in routes
        ]

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ROUTE): SelectSelector(
                    SelectSelectorConfig(
                        options=route_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="route",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 5: Select stop."""
        errors: dict[str, str] = {}

        if user_input is not None:
            stop_id = user_input.get(CONF_STOP_ID)
            if stop_id:
                # Check if this stop is already configured for this line/route
                if self._is_stop_already_configured(stop_id, self._line_id, self._route_id):
                    errors["base"] = "stop_already_configured"
                else:
                    # Store stop info and proceed to options step
                    self._stop_id = stop_id
                    client = self._get_client()
                    stops = await client.get_stops(self._line_id, self._route_id)
                    for stop in stops:
                        if stop.id == stop_id:
                            self._stop_name = stop.name
                            break
                    if not self._stop_name:
                        self._stop_name = stop_id

                    return await self.async_step_options()
            else:
                errors["base"] = "stop_required"

        # Get stops for selected line and route
        client = self._get_client()
        try:
            stops = await client.get_stops(self._line_id, self._route_id)
        except TisseoApiError:
            stops = []

        if not stops:
            await self._async_close_client()
            return self.async_abort(reason="no_stops")

        # Build options for selector - use display_name which includes direction
        stop_options = [
            {"value": stop.id, "label": stop.display_name}
            for stop in stops
        ]

        data_schema = vol.Schema(
            {
                vol.Required(CONF_STOP_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=stop_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="stop",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 6: Configure stop-specific options."""
        form_threshold = self._imminent_threshold

        if user_input is not None:
            form_threshold = int(
                user_input.get(
                    CONF_IMMINENT_THRESHOLD,
                    self._imminent_threshold,
                )
            )
            self._imminent_threshold = form_threshold

            if self._update_strategy == UPDATE_STRATEGY_TIME_WINDOW:
                return await self._async_create_config_entry(
                    schedule_enabled=True,
                    active_windows=self._active_windows,
                    inactive_interval=self._inactive_interval,
                )

            return await self._async_create_config_entry(
                schedule_enabled=False,
                active_windows=[],
                inactive_interval=DEFAULT_INACTIVE_INTERVAL,
            )

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_IMMINENT_THRESHOLD,
                        default=form_threshold,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=15,
                            step=1,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                }
            ),
            errors={},
            description_placeholders={
                "windows": _format_windows_summary(self._active_windows),
            },
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth when the API key has become invalid."""
        self._api_key = entry_data.get(CONF_API_KEY)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to re-enter a valid API key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            new_api_key = user_input.get(CONF_API_KEY, "")

            if not new_api_key:
                errors["base"] = "api_key_required"
            else:
                # Validate the new key
                client = TisseoApiClient(api_key=new_api_key, use_mock=False)
                try:
                    await client.search_stops("Capitole")
                except TisseoAuthError:
                    errors["base"] = "invalid_auth"
                except TisseoApiError:
                    errors["base"] = "cannot_connect"
                finally:
                    await client.close()

                if not errors:
                    # Update the API key in ALL existing entries that share the old key
                    reauth_entry = self._get_reauth_entry()
                    old_key = reauth_entry.data.get(CONF_API_KEY)

                    for entry in self._async_current_entries():
                        if entry.data.get(CONF_API_KEY) == old_key:
                            new_data = {**entry.data, CONF_API_KEY: new_api_key}
                            self.hass.config_entries.async_update_entry(
                                entry, data=new_data
                            )

                    await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        data_schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return TisseoOptionsFlowHandler(config_entry)


class TisseoOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Tisseo options for a single stop entry."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._strategy_override: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        is_hub_entry = CONF_STOP_ID not in self._config_entry.data

        if not is_hub_entry:
            current_threshold = self._config_entry.options.get(
                CONF_IMMINENT_THRESHOLD,
                self._config_entry.data.get(
                    CONF_IMMINENT_THRESHOLD, DEFAULT_IMMINENT_THRESHOLD
                ),
            )
            form_threshold = int(current_threshold)

            if user_input is not None:
                form_threshold = int(
                    user_input.get(CONF_IMMINENT_THRESHOLD, current_threshold)
                )
                new_options = dict(self._config_entry.options)
                new_options[CONF_IMMINENT_THRESHOLD] = form_threshold
                return self.async_create_entry(title="", data=new_options)

            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Optional(
                            CONF_IMMINENT_THRESHOLD, default=form_threshold
                        ): NumberSelector(
                            NumberSelectorConfig(
                                min=1,
                                max=15,
                                step=1,
                                unit_of_measurement="min",
                                mode=NumberSelectorMode.SLIDER,
                            )
                        )
                    }
                ),
                errors={},
                description_placeholders={
                    "windows": "None",
                    "current_strategy": "Stop-specific",
                },
            )

        if user_input is not None:
            # Backward-compatible: if this step receives payload directly, treat it as edit.
            return await self.async_step_edit_settings(user_input)
        return await self.async_step_menu()

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Hub options menu with explicit actions."""
        current_strategy = self._strategy_override or self._config_entry.options.get(
            CONF_UPDATE_STRATEGY,
            self._config_entry.data.get(CONF_UPDATE_STRATEGY, DEFAULT_UPDATE_STRATEGY),
        )
        return self.async_show_menu(
            step_id="menu",
            menu_options=["edit_settings", "update_strategy"],
            description_placeholders={
                "current_strategy": _strategy_label(current_strategy),
            },
        )

    async def async_step_edit_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit global settings for the currently selected strategy."""
        errors: dict[str, str] = {}
        current_strategy = self._config_entry.options.get(
            CONF_UPDATE_STRATEGY,
            self._config_entry.data.get(CONF_UPDATE_STRATEGY, DEFAULT_UPDATE_STRATEGY),
        )
        form_strategy = self._strategy_override or current_strategy
        current_interval = self._config_entry.options.get(
            CONF_STATIC_INTERVAL,
            self._config_entry.data.get(CONF_STATIC_INTERVAL, DEFAULT_STATIC_INTERVAL),
        )
        current_debug = self._config_entry.options.get(
            CONF_DEBUG,
            self._config_entry.data.get(CONF_DEBUG, False),
        )
        current_messages_refresh_interval = int(
            self._config_entry.options.get(
                CONF_MESSAGES_REFRESH_INTERVAL,
                self._config_entry.data.get(
                    CONF_MESSAGES_REFRESH_INTERVAL,
                    DEFAULT_MESSAGES_REFRESH_INTERVAL,
                ),
            )
        )
        current_outages_refresh_interval = int(
            self._config_entry.options.get(
                CONF_OUTAGES_REFRESH_INTERVAL,
                self._config_entry.data.get(
                    CONF_OUTAGES_REFRESH_INTERVAL,
                    DEFAULT_OUTAGES_REFRESH_INTERVAL,
                ),
            )
        )
        current_inactive_interval = int(
            self._config_entry.options.get(
                CONF_INACTIVE_INTERVAL,
                self._config_entry.data.get(
                    CONF_INACTIVE_INTERVAL,
                    DEFAULT_INACTIVE_INTERVAL,
                ),
            )
        )
        current_windows = self._config_entry.options.get(
            CONF_ACTIVE_WINDOWS,
            self._config_entry.data.get(CONF_ACTIVE_WINDOWS, []),
        )

        form_interval = int(current_interval)
        form_debug = bool(current_debug)
        form_messages_refresh_interval = current_messages_refresh_interval
        form_outages_refresh_interval = current_outages_refresh_interval
        form_inactive_interval = current_inactive_interval
        form_windows = current_windows if isinstance(current_windows, list) else []
        current_api_key = self._config_entry.data.get(CONF_API_KEY, "")
        pending_api_key: str | None = None

        if user_input is not None:
            form_interval = int(user_input.get(CONF_STATIC_INTERVAL, current_interval))
            form_debug = bool(user_input.get(CONF_DEBUG, current_debug))
            form_messages_refresh_interval = int(
                user_input.get(
                    CONF_MESSAGES_REFRESH_INTERVAL,
                    current_messages_refresh_interval,
                )
            )
            form_outages_refresh_interval = int(
                user_input.get(
                    CONF_OUTAGES_REFRESH_INTERVAL,
                    current_outages_refresh_interval,
                )
            )
            form_inactive_interval = int(
                user_input.get(CONF_INACTIVE_INTERVAL, current_inactive_interval)
            )
            raw_windows = user_input.get(CONF_ACTIVE_WINDOWS, current_windows)
            form_windows = raw_windows if isinstance(raw_windows, list) else []
            submitted_api_key = user_input.get(CONF_API_KEY, "")
            new_api_key = (
                submitted_api_key.strip()
                if isinstance(submitted_api_key, str)
                else ""
            )

            if new_api_key and new_api_key != current_api_key:
                client = TisseoApiClient(api_key=new_api_key, use_mock=False)
                try:
                    await client.search_stops("Capitole")
                except TisseoAuthError:
                    errors["base"] = "invalid_auth"
                except TisseoApiError:
                    errors["base"] = "cannot_connect"
                finally:
                    await client.close()

                if "base" not in errors:
                    pending_api_key = new_api_key

            if not errors and form_strategy == UPDATE_STRATEGY_TIME_WINDOW:
                windows, error = _normalize_windows(raw_windows)
                if error:
                    errors["base"] = error
                elif not windows:
                    errors["base"] = "no_windows_configured"
                else:
                    if pending_api_key:
                        self.hass.config_entries.async_update_entry(
                            self._config_entry,
                            data={**self._config_entry.data, CONF_API_KEY: pending_api_key},
                        )
                        hub_data = self.hass.data.get(DOMAIN)
                        if hub_data is not None:
                            hub_data.client.api_key = pending_api_key
                    return self.async_create_entry(
                        title="",
                        data={
                            CONF_UPDATE_STRATEGY: form_strategy,
                            CONF_STATIC_INTERVAL: form_interval,
                            CONF_DEBUG: form_debug,
                            CONF_MESSAGES_REFRESH_INTERVAL: form_messages_refresh_interval,
                            CONF_OUTAGES_REFRESH_INTERVAL: form_outages_refresh_interval,
                            CONF_SCHEDULE_ENABLED: True,
                            CONF_ACTIVE_WINDOWS: windows,
                            CONF_INACTIVE_INTERVAL: form_inactive_interval,
                        },
                    )

            if not errors:
                if pending_api_key:
                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        data={**self._config_entry.data, CONF_API_KEY: pending_api_key},
                    )
                    hub_data = self.hass.data.get(DOMAIN)
                    if hub_data is not None:
                        hub_data.client.api_key = pending_api_key
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_UPDATE_STRATEGY: form_strategy,
                        CONF_STATIC_INTERVAL: form_interval,
                        CONF_DEBUG: form_debug,
                        CONF_MESSAGES_REFRESH_INTERVAL: form_messages_refresh_interval,
                        CONF_OUTAGES_REFRESH_INTERVAL: form_outages_refresh_interval,
                        CONF_SCHEDULE_ENABLED: False,
                        CONF_ACTIVE_WINDOWS: [],
                        CONF_INACTIVE_INTERVAL: DEFAULT_INACTIVE_INTERVAL,
                    },
                )

        if form_strategy != UPDATE_STRATEGY_TIME_WINDOW:
            form_windows = []
            form_inactive_interval = DEFAULT_INACTIVE_INTERVAL

        schema_dict: dict[Any, Any] = {
            vol.Optional(CONF_DEBUG, default=form_debug): bool,
            vol.Optional(CONF_API_KEY): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_MESSAGES_REFRESH_INTERVAL,
                default=form_messages_refresh_interval,
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=3600,
                    step=30,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_OUTAGES_REFRESH_INTERVAL,
                default=form_outages_refresh_interval,
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=3600,
                    step=30,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
        }
        if form_strategy == UPDATE_STRATEGY_STATIC:
            schema_dict[
                vol.Optional(
                    CONF_STATIC_INTERVAL,
                    default=form_interval,
                )
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=30,
                    max=300,
                    step=10,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.SLIDER,
                )
            )
        if form_strategy == UPDATE_STRATEGY_TIME_WINDOW:
            schema_dict[
                vol.Optional(
                    CONF_INACTIVE_INTERVAL,
                    default=form_inactive_interval,
                )
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=3600,
                    step=60,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.SLIDER,
                )
            )
            schema_dict[
                vol.Optional(
                    CONF_ACTIVE_WINDOWS,
                    default=form_windows,
                )
            ] = _build_windows_selector()

        return self.async_show_form(
            step_id="edit_settings",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "windows": _format_windows_summary(form_windows),
                "current_strategy": _strategy_label(form_strategy),
            },
        )

    async def async_step_update_strategy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a new update strategy in a dedicated dialog step."""
        current_strategy = self._strategy_override or self._config_entry.options.get(
            CONF_UPDATE_STRATEGY,
            self._config_entry.data.get(CONF_UPDATE_STRATEGY, DEFAULT_UPDATE_STRATEGY),
        )

        if user_input is not None:
            self._strategy_override = user_input.get(
                CONF_UPDATE_STRATEGY, current_strategy
            )
            return await self.async_step_edit_settings()

        return self.async_show_form(
            step_id="update_strategy",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_STRATEGY, default=current_strategy
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=_build_strategy_options(),
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors={},
            description_placeholders={
                "current_strategy": _strategy_label(current_strategy),
            },
        )
