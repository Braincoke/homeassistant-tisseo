"""The Tisseo integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .api import TisseoApiClient, TisseoAuthError
from .const import (
    API_USAGE_ENTITY_ID,
    CONF_ACTIVE_WINDOWS,
    CONF_API_KEY,
    CONF_DEBUG,
    CONF_LINE,
    CONF_LINE_COLOR,
    CONF_MESSAGES_REFRESH_INTERVAL,
    CONF_LINE_TEXT_COLOR,
    CONF_OUTAGES_REFRESH_INTERVAL,
    CONF_ROUTE,
    CONF_SCHEDULE_ENABLED,
    CONF_STATIC_INTERVAL,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_UPDATE_STRATEGY,
    CONF_USE_MOCK,
    DEFAULT_MESSAGES_REFRESH_INTERVAL,
    DEFAULT_OUTAGES_REFRESH_INTERVAL,
    DEFAULT_STATIC_INTERVAL,
    DEFAULT_UPDATE_STRATEGY,
    DOMAIN,
    UPDATE_STRATEGY_TIME_WINDOW,
)
from .coordinator import TisseoStopCoordinator
from .usage import TisseoApiUsageTracker

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]
GLOBAL_OPTION_KEYS = (
    CONF_UPDATE_STRATEGY,
    CONF_STATIC_INTERVAL,
    CONF_MESSAGES_REFRESH_INTERVAL,
    CONF_OUTAGES_REFRESH_INTERVAL,
    CONF_SCHEDULE_ENABLED,
    CONF_ACTIVE_WINDOWS,
)
SYNC_IN_PROGRESS: set[str] = set()

_LOGGER = logging.getLogger(__name__)

# Service constants
SERVICE_NEARBY_STOPS = "get_nearby_stops"
SERVICE_PLANNED_DEPARTURES = "get_planned_departures"
ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"
ATTR_MAX_DISTANCE = "max_distance"
ATTR_MAX_RESULTS = "max_results"
ATTR_STOP_ENTITY_ID = "stop_entity_id"
ATTR_START_DATETIME = "start_datetime"
ATTR_END_DATETIME = "end_datetime"
ATTR_NUMBER = "number"
ATTR_DISPLAY_REALTIME = "display_realtime"
ATTR_STORE_RESULT = "store_result"

TOULOUSE_TZ = ZoneInfo("Europe/Paris")

NEARBY_STOPS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_LATITUDE): vol.Coerce(float),
        vol.Required(ATTR_LONGITUDE): vol.Coerce(float),
        vol.Optional(ATTR_MAX_DISTANCE, default=500): vol.All(
            vol.Coerce(int), vol.Range(min=100, max=2000)
        ),
        vol.Optional(ATTR_MAX_RESULTS, default=10): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=20)
        ),
    }
)

PLANNED_DEPARTURES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_STOP_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_START_DATETIME): str,
        vol.Required(ATTR_END_DATETIME): str,
        vol.Optional(ATTR_NUMBER, default=40): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=200)
        ),
        vol.Optional(ATTR_DISPLAY_REALTIME, default=False): bool,
        vol.Optional(ATTR_STORE_RESULT, default=True): bool,
    }
)


def _parse_service_datetime(value: Any) -> datetime:
    """Parse service datetime input and normalize to Toulouse timezone."""
    parsed: datetime | None = None

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = dt_util.parse_datetime(value)
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as err:
                raise vol.Invalid(
                    "Invalid datetime format. Use YYYY-MM-DD HH:MM or ISO format."
                ) from err
    else:
        raise vol.Invalid("Datetime value must be a string or datetime")

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TOULOUSE_TZ)
    return parsed.astimezone(TOULOUSE_TZ)


@dataclass
class TisseoHubData:
    """Shared data for all Tisseo config entries (one per HA instance)."""

    client: TisseoApiClient
    usage_tracker: TisseoApiUsageTracker
    entry_count: int = 0
    usage_sensor_owner_entry_id: str | None = None


@dataclass
class TisseoRuntimeData:
    """Runtime data for a single config entry."""

    coordinator: TisseoStopCoordinator | None = None


type TisseoConfigEntry = ConfigEntry[TisseoRuntimeData]


async def _async_get_or_create_hub(hass: HomeAssistant, entry: ConfigEntry) -> TisseoHubData:
    """Get or create the shared Tisseo hub (shared API client + session)."""
    if DOMAIN not in hass.data:
        source_entry = entry
        for candidate in hass.config_entries.async_entries(DOMAIN):
            if CONF_STOP_ID not in candidate.data:
                source_entry = candidate
                break

        api_key = source_entry.options.get(
            CONF_API_KEY,
            source_entry.data.get(CONF_API_KEY),
        )
        use_mock = source_entry.options.get(
            CONF_USE_MOCK,
            source_entry.data.get(CONF_USE_MOCK, False),
        )
        debug = source_entry.options.get(
            CONF_DEBUG,
            source_entry.data.get(CONF_DEBUG, False),
        )

        client = TisseoApiClient(
            api_key=api_key,
            use_mock=use_mock,
            debug=debug,
        )
        usage_tracker = TisseoApiUsageTracker(hass)
        await usage_tracker.async_load()
        client.set_usage_callback(usage_tracker.record_call)
        # Remove stale standalone state from previous releases.
        hass.states.async_remove(API_USAGE_ENTITY_ID)

        hass.data[DOMAIN] = TisseoHubData(
            client=client,
            usage_tracker=usage_tracker,
            entry_count=0,
        )
        _LOGGER.debug("Created shared Tisseo API client (mock=%s)", use_mock)

    return hass.data[DOMAIN]


def _unbind_usage_device_from_entry(hass: HomeAssistant, entry_id: str) -> None:
    """Remove stale associations between usage device and a non-owner entry."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device({(DOMAIN, "api_usage")}, set())
    if device and entry_id in device.config_entries:
        device_registry.async_update_device(
            device.id,
            remove_config_entry_id=entry_id,
        )


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register Tisseo services (idempotent — safe to call multiple times)."""
    async def handle_nearby_stops(call: ServiceCall) -> ServiceResponse:
        """Handle the get_nearby_stops service call."""
        hub: TisseoHubData | None = hass.data.get(DOMAIN)
        if hub is None:
            return {"error": "Tisseo integration not loaded"}

        latitude = call.data[ATTR_LATITUDE]
        longitude = call.data[ATTR_LONGITUDE]
        max_distance = call.data.get(ATTR_MAX_DISTANCE, 500)
        max_results = call.data.get(ATTR_MAX_RESULTS, 10)

        try:
            nearby = await hub.client.get_nearby_stops(
                latitude=latitude,
                longitude=longitude,
                max_distance=max_distance,
                max_results=max_results,
            )

            stops_data = []
            for stop in nearby:
                lines_data = []
                for line in stop.lines:
                    lines_data.append({
                        "line_id": line.line_id,
                        "line_short_name": line.line_short_name,
                        "line_name": line.line_name,
                        "line_color": line.line_color,
                        "line_text_color": line.line_text_color,
                        "transport_mode": line.transport_mode,
                        "direction": line.direction,
                    })

                stops_data.append({
                    "name": stop.name,
                    "latitude": stop.latitude,
                    "longitude": stop.longitude,
                    "distance": stop.distance,
                    "lines": lines_data,
                })

            return {"stops": stops_data}

        except Exception as err:
            _LOGGER.error("Error fetching nearby stops: %s", err)
            return {"error": str(err), "stops": []}

    async def handle_planned_departures(call: ServiceCall) -> ServiceResponse:
        """Handle the get_planned_departures service call."""
        stop_entity_id = call.data[ATTR_STOP_ENTITY_ID]
        try:
            start_datetime = _parse_service_datetime(call.data[ATTR_START_DATETIME])
            end_datetime = _parse_service_datetime(call.data[ATTR_END_DATETIME])
        except vol.Invalid as err:
            return {"error": str(err)}

        if end_datetime <= start_datetime:
            return {"error": "end_datetime must be after start_datetime"}

        entity_registry = er.async_get(hass)
        entity_entry = entity_registry.async_get(stop_entity_id)
        if entity_entry is None:
            return {"error": f"Entity not found: {stop_entity_id}"}

        config_entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
        if config_entry is None:
            return {"error": f"No config entry found for entity: {stop_entity_id}"}
        if CONF_STOP_ID not in config_entry.data:
            return {"error": "The selected entity is not attached to a Tisseo stop entry"}
        if config_entry.state is not ConfigEntryState.LOADED:
            return {"error": "The selected stop entry is not loaded"}

        coordinator = config_entry.runtime_data.coordinator
        if coordinator is None:
            return {"error": "Coordinator is not available for the selected stop"}

        try:
            result = await coordinator.async_fetch_planned_departures(
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                number=int(call.data[ATTR_NUMBER]),
                display_realtime=bool(call.data[ATTR_DISPLAY_REALTIME]),
                store_result=bool(call.data[ATTR_STORE_RESULT]),
            )
        except Exception as err:
            _LOGGER.error(
                "Failed planned departures request for %s: %s",
                stop_entity_id,
                err,
            )
            return {"error": str(err)}

        return {
            "stop_entity_id": stop_entity_id,
            "window_start": start_datetime.isoformat(),
            "window_end": end_datetime.isoformat(),
            "count": result["count"],
            "departures": result["departures"],
        }

    if not hass.services.has_service(DOMAIN, SERVICE_NEARBY_STOPS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_NEARBY_STOPS,
            handle_nearby_stops,
            schema=NEARBY_STOPS_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        _LOGGER.debug("Registered %s.%s service", DOMAIN, SERVICE_NEARBY_STOPS)

    if not hass.services.has_service(DOMAIN, SERVICE_PLANNED_DEPARTURES):
        hass.services.async_register(
            DOMAIN,
            SERVICE_PLANNED_DEPARTURES,
            handle_planned_departures,
            schema=PLANNED_DEPARTURES_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        _LOGGER.debug("Registered %s.%s service", DOMAIN, SERVICE_PLANNED_DEPARTURES)


async def async_setup_entry(hass: HomeAssistant, entry: TisseoConfigEntry) -> bool:
    """Set up Tisseo from a config entry.

    One dedicated entry stores global settings/usage, additional entries are stops.
    All entries share a single API client (shared aiohttp session).
    """
    _LOGGER.debug("Setting up Tisseo entry: %s", entry.title)

    # Get or create the shared hub (shared API client for all entries)
    hub = await _async_get_or_create_hub(hass, entry)
    hub.entry_count += 1
    is_hub_entry = CONF_STOP_ID not in entry.data

    # Update debug flag if any entry has it enabled
    # Mutable settings: prefer options, fall back to data for migration
    debug = entry.options.get(CONF_DEBUG, entry.data.get(CONF_DEBUG, False))
    if debug:
        hub.client.debug = True

    if is_hub_entry:
        hub.usage_sensor_owner_entry_id = entry.entry_id
        entry.runtime_data = TisseoRuntimeData()

        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
        await _async_register_services(hass)
        entry.async_on_unload(entry.add_update_listener(async_update_listener))

        _LOGGER.debug("Successfully set up Tisseo hub entry: %s", entry.title)
        return True

    # Get stop configuration (immutable — always from data)
    stop_id = entry.data[CONF_STOP_ID]
    stop_name = entry.data.get(CONF_STOP_NAME, stop_id)
    line_id = entry.data.get(CONF_LINE)
    line_color = entry.data.get(CONF_LINE_COLOR)
    line_text_color = entry.data.get(CONF_LINE_TEXT_COLOR)
    route_id = entry.data.get(CONF_ROUTE)

    # Get update settings (mutable — prefer options, fall back to data)
    update_strategy = entry.options.get(
        CONF_UPDATE_STRATEGY, entry.data.get(CONF_UPDATE_STRATEGY, DEFAULT_UPDATE_STRATEGY)
    )
    static_interval = entry.options.get(
        CONF_STATIC_INTERVAL, entry.data.get(CONF_STATIC_INTERVAL, DEFAULT_STATIC_INTERVAL)
    )
    messages_refresh_interval = int(
        entry.options.get(
            CONF_MESSAGES_REFRESH_INTERVAL,
            entry.data.get(
                CONF_MESSAGES_REFRESH_INTERVAL,
                DEFAULT_MESSAGES_REFRESH_INTERVAL,
            ),
        )
    )
    outages_refresh_interval = int(
        entry.options.get(
            CONF_OUTAGES_REFRESH_INTERVAL,
            entry.data.get(
                CONF_OUTAGES_REFRESH_INTERVAL,
                DEFAULT_OUTAGES_REFRESH_INTERVAL,
            ),
        )
    )
    schedule_enabled = update_strategy == UPDATE_STRATEGY_TIME_WINDOW

    if schedule_enabled:
        active_windows = entry.options.get(
            CONF_ACTIVE_WINDOWS,
            entry.data.get(CONF_ACTIVE_WINDOWS, []),
        )
    else:
        active_windows = []

    # Create coordinator for this stop (uses the shared client)
    coordinator = TisseoStopCoordinator(
        hass=hass,
        client=hub.client,
        stop_id=stop_id,
        stop_name=stop_name,
        line_id=line_id,
        line_color=line_color,
        line_text_color=line_text_color,
        route_id=route_id,
        update_strategy=update_strategy,
        static_interval=static_interval,
        messages_refresh_interval=messages_refresh_interval,
        outages_refresh_interval=outages_refresh_interval,
        schedule_enabled=schedule_enabled,
        active_windows=active_windows,
    )

    # Fetch initial data
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        # API key is invalid — trigger reauth flow
        raise
    except ConfigEntryNotReady:
        # API unreachable — HA will retry automatically
        raise

    # Store runtime data
    entry.runtime_data = TisseoRuntimeData(
        coordinator=coordinator,
    )

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    has_dedicated_hub_entry = any(
        CONF_STOP_ID not in cfg.data for cfg in hass.config_entries.async_entries(DOMAIN)
    )
    if has_dedicated_hub_entry or hub.usage_sensor_owner_entry_id != entry.entry_id:
        _unbind_usage_device_from_entry(hass, entry.entry_id)

    # Register services (idempotent)
    await _async_register_services(hass)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    _LOGGER.debug("Successfully set up Tisseo stop entry: %s", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TisseoConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Tisseo entry: %s", entry.title)
    is_hub_entry = CONF_STOP_ID not in entry.data
    platforms = [Platform.SENSOR] if is_hub_entry else PLATFORMS

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)

    if unload_ok:
        hub: TisseoHubData | None = hass.data.get(DOMAIN)
        if hub:
            _unbind_usage_device_from_entry(hass, entry.entry_id)

            hub.entry_count -= 1

            # If this was the last entry, close the shared client and clean up
            if hub.entry_count <= 0:
                _LOGGER.debug("Last Tisseo entry unloaded, closing shared client")
                await hub.usage_tracker.async_shutdown()
                await hub.client.close()
                hass.data.pop(DOMAIN, None)

                # Remove services
                if hass.services.has_service(DOMAIN, SERVICE_NEARBY_STOPS):
                    hass.services.async_remove(DOMAIN, SERVICE_NEARBY_STOPS)
                if hass.services.has_service(DOMAIN, SERVICE_PLANNED_DEPARTURES):
                    hass.services.async_remove(DOMAIN, SERVICE_PLANNED_DEPARTURES)
            elif hub.usage_sensor_owner_entry_id == entry.entry_id:
                # Re-host the global usage sensors on another loaded entry.
                hub.usage_sensor_owner_entry_id = None
                for other_entry in hass.config_entries.async_entries(DOMAIN):
                    if (
                        other_entry.entry_id != entry.entry_id
                        and other_entry.state is ConfigEntryState.LOADED
                    ):
                        hass.async_create_task(
                            hass.config_entries.async_reload(other_entry.entry_id)
                        )
                        break

    return unload_ok


async def async_update_listener(hass: HomeAssistant, entry: TisseoConfigEntry) -> None:
    """Handle options update."""
    if entry.entry_id in SYNC_IN_PROGRESS:
        SYNC_IN_PROGRESS.discard(entry.entry_id)
        await hass.config_entries.async_reload(entry.entry_id)
        return

    source_values = {
        key: entry.options[key]
        for key in GLOBAL_OPTION_KEYS
        if key in entry.options
    }
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id == entry.entry_id:
            continue

        new_options = dict(other.options)
        changed = False
        for key, value in source_values.items():
            if new_options.get(key) != value:
                new_options[key] = value
                changed = True

        if changed:
            SYNC_IN_PROGRESS.add(other.entry_id)
            hass.config_entries.async_update_entry(other, options=new_options)

    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to new version."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version > 2:
        # Downgrade from version 3 (subentries) - cannot auto-migrate
        _LOGGER.warning(
            "Cannot migrate from version %s. Please remove and reconfigure.",
            config_entry.version
        )
        return False

    if config_entry.version == 1:
        # Version 1 to 2 - check if entry has stop data
        if CONF_STOP_ID not in config_entry.data:
            _LOGGER.warning(
                "Cannot migrate Tisseo entry without stop data. Please remove and reconfigure."
            )
            return False

        hass.config_entries.async_update_entry(config_entry, version=2)
        _LOGGER.debug("Migration to version 2 successful")

    return True
