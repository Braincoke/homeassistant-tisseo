"""Binary sensor platform for Tisseo integration."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTRIBUTION,
    CONF_IMMINENT_THRESHOLD,
    CONF_LINE_NAME,
    CONF_ROUTE_DIRECTION,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_TRANSPORT_MODE,
    DEFAULT_IMMINENT_THRESHOLD,
    DEVICE_MANUFACTURER,
    DOMAIN,
)
from .coordinator import TisseoStopCoordinator
from .helpers import get_device_model, get_transport_icon, make_unique_key

if TYPE_CHECKING:
    from . import TisseoConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TisseoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tisseo binary sensors based on a config entry."""
    coordinator = entry.runtime_data.coordinator

    # Get stop configuration from entry data
    stop_id = entry.data[CONF_STOP_ID]
    stop_name = entry.data.get(CONF_STOP_NAME, stop_id)
    line_name = entry.data.get(CONF_LINE_NAME, "")
    route_direction = entry.data.get(CONF_ROUTE_DIRECTION, "")
    transport_mode = entry.data.get(CONF_TRANSPORT_MODE, "")
    imminent_threshold = entry.options.get(
        CONF_IMMINENT_THRESHOLD,
        entry.data.get(CONF_IMMINENT_THRESHOLD, DEFAULT_IMMINENT_THRESHOLD),
    )

    # Use entry title as device name
    device_name = entry.title

    # Create unique key for device/entities
    unique_key = make_unique_key(transport_mode, line_name, stop_name, route_direction)

    entities: list[BinarySensorEntity] = [
        TisseoImminentDepartureSensor(
            coordinator,
            unique_key,
            stop_name,
            transport_mode,
            device_name,
            imminent_threshold,
        ),
        TisseoAlertSensor(
            coordinator,
            unique_key,
            stop_name,
            transport_mode,
            device_name,
        ),
    ]

    async_add_entities(entities)
    _LOGGER.debug("Added binary sensors for stop: %s", stop_name)


class TisseoImminentDepartureSensor(
    CoordinatorEntity[TisseoStopCoordinator], BinarySensorEntity
):
    """Binary sensor that indicates if a departure is imminent."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(
        self,
        coordinator: TisseoStopCoordinator,
        unique_key: str,
        stop_name: str,
        transport_mode: str,
        device_name: str,
        threshold: int,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._stop_name = stop_name
        self._transport_mode = transport_mode
        self._device_name = device_name
        self._unique_key = unique_key
        self._threshold = threshold

        self._attr_unique_id = f"{self._unique_key}_imminent"
        self._attr_name = "Imminent departure"
        self.entity_id = f"binary_sensor.{self._unique_key}_imminent"

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
    def icon(self) -> str:
        """Return dynamic icon based on transport mode."""
        if self.coordinator.data:
            next_dep = self.coordinator.data.get("next_departure")
            if next_dep:
                return get_transport_icon(next_dep.transport_mode)
        return "mdi:bus-alert"

    @property
    def is_on(self) -> bool | None:
        """Return True if a departure is imminent."""
        if not self.coordinator.data:
            return None

        next_departure = self.coordinator.data.get("next_departure")
        if not next_departure:
            return False

        return next_departure.minutes_until <= self._threshold

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {
            "threshold_minutes": self._threshold,
        }

        if self.coordinator.data:
            next_departure = self.coordinator.data.get("next_departure")
            if next_departure:
                attrs["minutes_until"] = next_departure.minutes_until
                attrs["line"] = next_departure.line_short_name
                attrs["destination"] = next_departure.destination
                attrs["departure_time"] = next_departure.departure_time.isoformat()

        return attrs


class TisseoAlertSensor(
    CoordinatorEntity[TisseoStopCoordinator], BinarySensorEntity
):
    """Binary sensor that indicates if there are active service alerts.

    This sensor turns ON when there are active alerts for the line.
    It exposes alert details as attributes for use in automations.
    The 'new_alerts' attribute contains alerts that appeared since the last check,
    which can be used to trigger notifications only for new alerts.
    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: TisseoStopCoordinator,
        unique_key: str,
        stop_name: str,
        transport_mode: str,
        device_name: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._stop_name = stop_name
        self._transport_mode = transport_mode
        self._device_name = device_name
        self._unique_key = unique_key

        self._attr_unique_id = f"{self._unique_key}_alerts"
        self._attr_name = "Service alerts"
        self.entity_id = f"binary_sensor.{self._unique_key}_alerts"

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
    def icon(self) -> str:
        """Return dynamic icon based on alert state."""
        if self.is_on:
            return "mdi:alert"
        return "mdi:check-circle"

    @property
    def is_on(self) -> bool | None:
        """Return True if there are active alerts."""
        if not self.coordinator.data:
            return None

        alerts = self.coordinator.data.get("alerts", [])
        return len(alerts) > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes with alert details."""
        attrs: dict[str, Any] = {
            "alert_count": 0,
            "alerts": [],
            "new_alert_count": 0,
            "new_alerts": [],
            "highest_severity": None,
        }

        if not self.coordinator.data:
            return attrs

        alerts = self.coordinator.data.get("alerts", [])
        new_alerts = self.coordinator.data.get("new_alerts", [])

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

        # Format new alerts
        new_alert_list = []
        for alert in new_alerts:
            new_alert_list.append({
                "id": alert.id,
                "title": alert.title,
                "content": alert.content,
                "severity": alert.severity,
                "start_time": alert.start_time.isoformat() if alert.start_time else None,
                "end_time": alert.end_time.isoformat() if alert.end_time else None,
            })

        # Determine highest severity
        severity_order = {"critical": 3, "warning": 2, "info": 1}
        highest_severity = None
        highest_level = 0
        for alert in alerts:
            level = severity_order.get(alert.severity, 0)
            if level > highest_level:
                highest_level = level
                highest_severity = alert.severity

        attrs["alert_count"] = len(alerts)
        attrs["alerts"] = alert_list
        attrs["new_alert_count"] = len(new_alerts)
        attrs["new_alerts"] = new_alert_list
        attrs["highest_severity"] = highest_severity

        # Add first alert details for easy access in automations
        if alerts:
            first_alert = alerts[0]
            attrs["first_alert_title"] = first_alert.title
            attrs["first_alert_content"] = first_alert.content
            attrs["first_alert_severity"] = first_alert.severity

        # Add first new alert details for notification automations
        if new_alerts:
            first_new = new_alerts[0]
            attrs["first_new_alert_title"] = first_new.title
            attrs["first_new_alert_content"] = first_new.content
            attrs["first_new_alert_severity"] = first_new.severity

        return attrs
