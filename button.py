"""Button platform for Tisseo integration."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTRIBUTION,
    CONF_LINE_NAME,
    CONF_ROUTE_DIRECTION,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_TRANSPORT_MODE,
    DEVICE_MANUFACTURER,
    DOMAIN,
)
from .coordinator import TisseoStopCoordinator
from .helpers import get_device_model, make_unique_key

if TYPE_CHECKING:
    from . import TisseoConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TisseoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tisseo button based on a config entry."""
    coordinator = entry.runtime_data.coordinator

    stop_id = entry.data[CONF_STOP_ID]
    stop_name = entry.data.get(CONF_STOP_NAME, stop_id)
    line_name = entry.data.get(CONF_LINE_NAME, "")
    route_direction = entry.data.get(CONF_ROUTE_DIRECTION, "")
    transport_mode = entry.data.get(CONF_TRANSPORT_MODE, "")

    device_name = entry.title
    unique_key = make_unique_key(transport_mode, line_name, stop_name, route_direction)

    entities: list[ButtonEntity] = [
        TisseoRefreshButton(coordinator, unique_key, device_name, transport_mode),
    ]

    async_add_entities(entities)
    _LOGGER.debug("Added refresh button for stop: %s", stop_name)


class TisseoRefreshButton(ButtonEntity):
    """Button to manually refresh departure data."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: TisseoStopCoordinator,
        unique_key: str,
        device_name: str,
        transport_mode: str,
    ) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._unique_key = unique_key
        self._device_name = device_name
        self._transport_mode = transport_mode

        self._attr_unique_id = f"{self._unique_key}_refresh"
        self._attr_name = "Refresh departures"
        self.entity_id = f"button.{self._unique_key}_refresh"

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

    async def async_press(self) -> None:
        """Handle the button press - trigger a data refresh."""
        _LOGGER.debug("Manual refresh triggered for %s", self._device_name)
        await self._coordinator.async_refresh_departures_only()
