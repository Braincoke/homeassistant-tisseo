"""Sensor platform for Tisseo integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Departure, Outage, ServiceAlert
from .const import (
    ATTRIBUTION,
    CONF_LINE,
    CONF_LINE_NAME,
    CONF_ROUTE,
    CONF_ROUTE_DIRECTION,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_TRANSPORT_MODE,
    DEVICE_MANUFACTURER,
    DOMAIN,
)
from .coordinator import TisseoStopCoordinator
from .helpers import get_device_model, get_transport_icon, make_unique_key
from .usage import TisseoApiUsageTracker

if TYPE_CHECKING:
    from . import TisseoConfigEntry, TisseoHubData

_LOGGER = logging.getLogger(__name__)
DEFAULT_ICON = "mdi:bus"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TisseoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tisseo sensors based on a config entry."""
    hub: TisseoHubData = hass.data[DOMAIN]
    is_hub_entry = CONF_STOP_ID not in entry.data

    if is_hub_entry:
        hub.usage_sensor_owner_entry_id = entry.entry_id
        async_add_entities(
            [
                TisseoApiCallsTotalSensor(hub.usage_tracker),
                TisseoApiCallsSuccessfulSensor(hub.usage_tracker),
                TisseoApiCallsFailedSensor(hub.usage_tracker),
                TisseoApiCallsTodaySensor(hub.usage_tracker),
                TisseoGtfsCallsTotalSensor(hub.usage_tracker),
                TisseoGtfsCallsSuccessfulSensor(hub.usage_tracker),
                TisseoGtfsCallsFailedSensor(hub.usage_tracker),
                TisseoGtfsCallsTodaySensor(hub.usage_tracker),
            ]
        )
        _LOGGER.debug("Added API usage sensors for hub entry: %s", entry.title)
        return

    coordinator = entry.runtime_data.coordinator
    if coordinator is None:
        _LOGGER.error("Missing coordinator for stop entry: %s", entry.entry_id)
        return

    # Get stop configuration from entry data
    stop_id = entry.data[CONF_STOP_ID]
    stop_name = entry.data.get(CONF_STOP_NAME, stop_id)
    line_id = entry.data.get(CONF_LINE, "")
    line_name = entry.data.get(CONF_LINE_NAME, "")
    route_id = entry.data.get(CONF_ROUTE, "")
    route_direction = entry.data.get(CONF_ROUTE_DIRECTION, "")
    transport_mode = entry.data.get(CONF_TRANSPORT_MODE, "")

    # Use entry title as device name
    device_name = entry.title

    # Create unique key for device/entities
    unique_key = make_unique_key(transport_mode, line_name, stop_name, route_direction)

    entities: list[SensorEntity] = [
        TisseoNextDepartureSensor(coordinator, unique_key, stop_name, transport_mode, device_name),
        TisseoMinutesUntilSensor(coordinator, unique_key, stop_name, transport_mode, device_name),
        TisseoNextLineSensor(coordinator, unique_key, stop_name, transport_mode, device_name),
        TisseoNextDestinationSensor(coordinator, unique_key, stop_name, transport_mode, device_name),
        TisseoDepartureListSensor(coordinator, unique_key, stop_name, transport_mode, device_name),
        TisseoPlannedDeparturesSensor(coordinator, unique_key, stop_name, transport_mode, device_name),
    ]

    has_dedicated_hub_entry = any(
        CONF_STOP_ID not in cfg.data for cfg in hass.config_entries.async_entries(DOMAIN)
    )
    if not has_dedicated_hub_entry:
        if hub.usage_sensor_owner_entry_id is None:
            hub.usage_sensor_owner_entry_id = entry.entry_id
        if hub.usage_sensor_owner_entry_id == entry.entry_id:
            entities.extend(
                [
                    TisseoApiCallsTotalSensor(hub.usage_tracker),
                    TisseoApiCallsSuccessfulSensor(hub.usage_tracker),
                    TisseoApiCallsFailedSensor(hub.usage_tracker),
                    TisseoApiCallsTodaySensor(hub.usage_tracker),
                    TisseoGtfsCallsTotalSensor(hub.usage_tracker),
                    TisseoGtfsCallsSuccessfulSensor(hub.usage_tracker),
                    TisseoGtfsCallsFailedSensor(hub.usage_tracker),
                    TisseoGtfsCallsTodaySensor(hub.usage_tracker),
                ]
            )

    async_add_entities(entities)
    _LOGGER.debug("Added %d sensors for stop: %s", len(entities), stop_name)


class TisseoApiUsageBaseSensor(SensorEntity):
    """Base class for global API usage sensors."""

    _attr_icon = "mdi:api"
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, usage_tracker: TisseoApiUsageTracker) -> None:
        """Initialize the sensor."""
        self._usage_tracker = usage_tracker

    @property
    def device_info(self) -> DeviceInfo:
        """Return a dedicated global usage device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "api_usage")},
            name="Tisseo API Usage",
            manufacturer=DEVICE_MANUFACTURER,
            model="Usage Metrics",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to tracker updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._usage_tracker.async_add_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        """Usage sensor is available whenever integration is loaded."""
        return True


class TisseoApiCallsTotalSensor(TisseoApiUsageBaseSensor):
    """Total real API calls."""

    _attr_unique_id = "tisseo_api_calls_total"
    _attr_name = "API calls total"
    _attr_native_unit_of_measurement = "calls"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self) -> int:
        """Return total real API calls."""
        return self._usage_tracker.total_calls

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed usage breakdown."""
        metrics = self._usage_tracker.as_dict()
        return {
            "successful_calls": metrics["successful_calls"],
            "failed_calls": metrics["failed_calls"],
            "today_calls": metrics["today_calls"],
            "last_call": metrics["last_call_at"],
            "last_success": metrics["last_success_at"],
            "daily_calls_30d": metrics["daily_counts"],
            "endpoint_calls_top": metrics["endpoint_counts"],
            "gtfs_total_calls": metrics["gtfs_total_calls"],
            "gtfs_today_calls": metrics["gtfs_today_calls"],
        }


class TisseoApiCallsSuccessfulSensor(TisseoApiUsageBaseSensor):
    """Successful real API calls."""

    _attr_unique_id = "tisseo_api_calls_successful"
    _attr_name = "API calls successful"
    _attr_native_unit_of_measurement = "calls"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:check-circle-outline"

    @property
    def native_value(self) -> int:
        """Return successful API calls."""
        return int(self._usage_tracker.as_dict()["successful_calls"])


class TisseoApiCallsFailedSensor(TisseoApiUsageBaseSensor):
    """Failed real API calls."""

    _attr_unique_id = "tisseo_api_calls_failed"
    _attr_name = "API calls failed"
    _attr_native_unit_of_measurement = "calls"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:close-circle-outline"

    @property
    def native_value(self) -> int:
        """Return failed API calls."""
        return int(self._usage_tracker.as_dict()["failed_calls"])


class TisseoApiCallsTodaySensor(TisseoApiUsageBaseSensor):
    """Real API calls made today."""

    _attr_unique_id = "tisseo_api_calls_today"
    _attr_name = "API calls today"
    _attr_native_unit_of_measurement = "calls"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:calendar-today"

    @property
    def native_value(self) -> int:
        """Return API calls for today."""
        return int(self._usage_tracker.as_dict()["today_calls"])


class TisseoGtfsCallsTotalSensor(TisseoApiUsageBaseSensor):
    """Total GTFS requests (metadata + archive download)."""

    _attr_unique_id = "tisseo_gtfs_calls_total"
    _attr_name = "GTFS calls total"
    _attr_native_unit_of_measurement = "calls"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:database-arrow-down"

    @property
    def native_value(self) -> int:
        """Return total GTFS calls."""
        return int(self._usage_tracker.as_dict()["gtfs_total_calls"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed GTFS usage breakdown."""
        metrics = self._usage_tracker.as_dict()
        return {
            "successful_calls": metrics["gtfs_successful_calls"],
            "failed_calls": metrics["gtfs_failed_calls"],
            "today_calls": metrics["gtfs_today_calls"],
            "last_call": metrics["gtfs_last_call_at"],
            "last_success": metrics["gtfs_last_success_at"],
            "daily_calls_30d": metrics["gtfs_daily_counts"],
            "endpoint_calls_top": metrics["gtfs_endpoint_counts"],
        }


class TisseoGtfsCallsSuccessfulSensor(TisseoApiUsageBaseSensor):
    """Successful GTFS requests."""

    _attr_unique_id = "tisseo_gtfs_calls_successful"
    _attr_name = "GTFS calls successful"
    _attr_native_unit_of_measurement = "calls"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:check-circle-outline"

    @property
    def native_value(self) -> int:
        """Return successful GTFS calls."""
        return int(self._usage_tracker.as_dict()["gtfs_successful_calls"])


class TisseoGtfsCallsFailedSensor(TisseoApiUsageBaseSensor):
    """Failed GTFS requests."""

    _attr_unique_id = "tisseo_gtfs_calls_failed"
    _attr_name = "GTFS calls failed"
    _attr_native_unit_of_measurement = "calls"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:close-circle-outline"

    @property
    def native_value(self) -> int:
        """Return failed GTFS calls."""
        return int(self._usage_tracker.as_dict()["gtfs_failed_calls"])


class TisseoGtfsCallsTodaySensor(TisseoApiUsageBaseSensor):
    """GTFS requests made today."""

    _attr_unique_id = "tisseo_gtfs_calls_today"
    _attr_name = "GTFS calls today"
    _attr_native_unit_of_measurement = "calls"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:calendar-today"

    @property
    def native_value(self) -> int:
        """Return GTFS calls for today."""
        return int(self._usage_tracker.as_dict()["gtfs_today_calls"])


class TisseoBaseSensor(CoordinatorEntity[TisseoStopCoordinator], SensorEntity):
    """Base class for Tisseo sensors."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TisseoStopCoordinator,
        unique_key: str,
        stop_name: str,
        transport_mode: str,
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._stop_name = stop_name
        self._transport_mode = transport_mode
        self._device_name = device_name
        self._unique_key = unique_key

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._unique_key)},
            name=self._device_name,
            manufacturer=DEVICE_MANUFACTURER,
            model=get_device_model(self._transport_mode),
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _next_departure(self) -> Departure | None:
        """Get the next departure from coordinator data."""
        if self.coordinator.data:
            return self.coordinator.data.get("next_departure")
        return None


class TisseoNextDepartureSensor(TisseoBaseSensor):
    """Sensor for the next departure time."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: TisseoStopCoordinator,
        unique_key: str,
        stop_name: str,
        transport_mode: str,
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, unique_key, stop_name, transport_mode, device_name)
        self._attr_unique_id = f"{self._unique_key}_next_departure"
        self._attr_name = "Next departure"
        self.entity_id = f"sensor.{self._unique_key}_next_departure"

    @property
    def icon(self) -> str:
        """Return dynamic icon based on transport mode."""
        departure = self._next_departure
        if departure:
            return get_transport_icon(departure.transport_mode)
        return "mdi:clock-outline"

    @property
    def native_value(self) -> datetime | None:
        """Return the next departure time."""
        departure = self._next_departure
        if departure:
            return departure.departure_time
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        departure = self._next_departure
        if departure:
            return {
                "line": departure.line_short_name,
                "destination": departure.destination,
                "is_realtime": departure.is_realtime,
                "transport_mode": departure.transport_mode,
            }
        return {}


class TisseoMinutesUntilSensor(TisseoBaseSensor):
    """Sensor for minutes until next departure."""

    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = "min"

    def __init__(
        self,
        coordinator: TisseoStopCoordinator,
        unique_key: str,
        stop_name: str,
        transport_mode: str,
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, unique_key, stop_name, transport_mode, device_name)
        self._attr_unique_id = f"{self._unique_key}_minutes_until"
        self._attr_name = "Minutes until departure"
        self.entity_id = f"sensor.{self._unique_key}_minutes_until"

    @property
    def native_value(self) -> int | None:
        """Return minutes until next departure."""
        departure = self._next_departure
        if departure:
            return departure.minutes_until
        return None


class TisseoNextLineSensor(TisseoBaseSensor):
    """Sensor for the next line."""

    def __init__(
        self,
        coordinator: TisseoStopCoordinator,
        unique_key: str,
        stop_name: str,
        transport_mode: str,
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, unique_key, stop_name, transport_mode, device_name)
        self._attr_unique_id = f"{self._unique_key}_line"
        self._attr_name = "Line"
        self.entity_id = f"sensor.{self._unique_key}_line"

    @property
    def icon(self) -> str:
        """Return dynamic icon based on transport mode."""
        departure = self._next_departure
        if departure:
            return get_transport_icon(departure.transport_mode)
        return DEFAULT_ICON

    @property
    def native_value(self) -> str | None:
        """Return the next line."""
        departure = self._next_departure
        if departure:
            return departure.line_short_name
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        departure = self._next_departure
        if departure:
            return {
                "line_name": departure.line_name,
                "line_color": departure.line_color,
                "transport_mode": departure.transport_mode,
            }
        return {}


class TisseoNextDestinationSensor(TisseoBaseSensor):
    """Sensor for the next destination."""

    def __init__(
        self,
        coordinator: TisseoStopCoordinator,
        unique_key: str,
        stop_name: str,
        transport_mode: str,
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, unique_key, stop_name, transport_mode, device_name)
        self._attr_unique_id = f"{self._unique_key}_destination"
        self._attr_name = "Destination"
        self.entity_id = f"sensor.{self._unique_key}_destination"

    @property
    def icon(self) -> str:
        """Return dynamic icon based on transport mode."""
        departure = self._next_departure
        if departure:
            return get_transport_icon(departure.transport_mode)
        return "mdi:map-marker"

    @property
    def native_value(self) -> str | None:
        """Return the next destination."""
        departure = self._next_departure
        if departure:
            return departure.destination
        return None


class TisseoDepartureListSensor(TisseoBaseSensor):
    """Sensor that shows all upcoming departures as attributes."""

    def __init__(
        self,
        coordinator: TisseoStopCoordinator,
        unique_key: str,
        stop_name: str,
        transport_mode: str,
        device_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, unique_key, stop_name, transport_mode, device_name)
        self._attr_unique_id = f"{self._unique_key}_departures"
        self._attr_name = "Departures"
        self.entity_id = f"sensor.{self._unique_key}_departures"

    @property
    def icon(self) -> str:
        """Return dynamic icon based on transport mode."""
        departure = self._next_departure
        if departure:
            return get_transport_icon(departure.transport_mode)
        return "mdi:format-list-bulleted"

    @property
    def native_value(self) -> int:
        """Return the number of upcoming departures."""
        if self.coordinator.data:
            departures = self.coordinator.data.get("departures", [])
            return len(departures)
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all departures as attributes."""
        if not self.coordinator.data:
            return {}

        departures: list[Departure] = self.coordinator.data.get("departures", [])
        alerts: list[ServiceAlert] = self.coordinator.data.get("alerts", [])
        outages: list[Outage] = self.coordinator.data.get("outages", [])
        stop_info = self.coordinator.data.get("stop_info")
        last_api_fetch = self.coordinator.data.get("last_api_fetch")
        last_alert_fetch = self.coordinator.data.get("last_alert_fetch")
        last_outage_fetch = self.coordinator.data.get("last_outage_fetch")

        # Format departures for attributes
        departure_list = []
        for dep in departures[:10]:  # Limit to 10 departures
            departure_list.append({
                "line": dep.line_short_name,
                "line_color": dep.line_color,
                "line_text_color": dep.line_text_color,
                "destination": dep.destination,
                "departure_time": dep.departure_time.isoformat(),
                "minutes_until": dep.minutes_until,
                "waiting_time": dep.waiting_time,
                "is_realtime": dep.is_realtime,
                "transport_mode": dep.transport_mode,
            })

        # Format alerts for attributes
        alert_list = []
        for alert in alerts:
            alert_list.append({
                "id": alert.id,
                "title": alert.title,
                "content": alert.content,
                "severity": alert.severity,
                "start_time": alert.start_time.isoformat() if alert.start_time else None,
                "end_time": alert.end_time.isoformat() if alert.end_time else None,
            })

        # Format outages for attributes
        outage_list = []
        for outage in outages:
            outage_list.append({
                "id": outage.id,
                "equipment_type": outage.equipment_type,
                "station_name": outage.station_name,
                "description": outage.description,
                "start_time": outage.start_time.isoformat() if outage.start_time else None,
                "end_time": outage.end_time.isoformat() if outage.end_time else None,
            })

        attrs = {
            "departures": departure_list,
            "alerts": alert_list,
            "has_alerts": len(alert_list) > 0,
            "outages": outage_list,
            "has_outages": len(outage_list) > 0,
            "last_updated": last_api_fetch.isoformat() if last_api_fetch else None,
            "last_alert_check": last_alert_fetch.isoformat() if last_alert_fetch else None,
            "last_outage_check": last_outage_fetch.isoformat() if last_outage_fetch else None,
        }

        if stop_info:
            attrs["stop_name"] = stop_info.name
            attrs["stop_city"] = stop_info.city

        return attrs


class TisseoPlannedDeparturesSensor(TisseoBaseSensor):
    """Sensor that exposes the last planned-departures window result."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self,
        coordinator: TisseoStopCoordinator,
        unique_key: str,
        stop_name: str,
        transport_mode: str,
        device_name: str,
    ) -> None:
        """Initialize the planned departures sensor."""
        super().__init__(coordinator, unique_key, stop_name, transport_mode, device_name)
        self._attr_unique_id = f"{self._unique_key}_planned_departures"
        self._attr_name = "Planned departures"
        self.entity_id = f"sensor.{self._unique_key}_planned_departures"

    @property
    def _planned_window(self) -> dict[str, Any] | None:
        """Return cached planned window payload from coordinator data."""
        if not self.coordinator.data:
            return None
        payload = self.coordinator.data.get("planned_window")
        if isinstance(payload, dict):
            return payload
        return None

    @property
    def native_value(self) -> int | None:
        """Return number of departures in the last requested planning window."""
        planned_window = self._planned_window
        if planned_window is None:
            return None
        return int(planned_window.get("count", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return metadata and departures for the last planned window request."""
        planned_window = self._planned_window
        if planned_window is None:
            return {}

        departures: list[dict[str, Any]] = planned_window.get("departures", [])
        summary = ", ".join(
            f"{dep.get('departure_time', '')[11:16]} -> {dep.get('destination', '')}"
            for dep in departures
        )

        return {
            "stop_id": planned_window.get("stop_id"),
            "stop_name": planned_window.get("stop_name"),
            "line_id": planned_window.get("line_id"),
            "route_id": planned_window.get("route_id"),
            "window_start": planned_window.get("window_start"),
            "window_end": planned_window.get("window_end"),
            "fetched_at": planned_window.get("fetched_at"),
            "display_realtime": planned_window.get("display_realtime"),
            "count": planned_window.get("count"),
            "total_candidates": planned_window.get("total_candidates"),
            "summary": summary if summary else "No departures in window",
            "departures": departures,
        }
