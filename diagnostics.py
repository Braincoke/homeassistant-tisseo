"""Diagnostics support for the Tisseo integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_API_KEY,
    CONF_ACTIVE_WINDOWS,
    CONF_DEBUG,
    CONF_IMMINENT_THRESHOLD,
    CONF_INACTIVE_INTERVAL,
    CONF_LINE,
    CONF_LINE_NAME,
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
    DOMAIN,
)

# Keys to redact from diagnostics output
TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    # Redact sensitive data from config
    config_data = async_redact_data(dict(entry.data), TO_REDACT)
    coordinator = entry.runtime_data.coordinator

    if coordinator is None:
        usage_tracker = hass.data.get(DOMAIN).usage_tracker if hass.data.get(DOMAIN) else None
        return {
            "config_entry": config_data,
            "entry_type": "hub",
            "global_settings": {
                "update_strategy": entry.options.get(
                    CONF_UPDATE_STRATEGY,
                    entry.data.get(CONF_UPDATE_STRATEGY),
                ),
                "static_interval": entry.options.get(
                    CONF_STATIC_INTERVAL,
                    entry.data.get(CONF_STATIC_INTERVAL),
                ),
                "messages_refresh_interval": entry.options.get(
                    CONF_MESSAGES_REFRESH_INTERVAL,
                    entry.data.get(CONF_MESSAGES_REFRESH_INTERVAL),
                ),
                "outages_refresh_interval": entry.options.get(
                    CONF_OUTAGES_REFRESH_INTERVAL,
                    entry.data.get(CONF_OUTAGES_REFRESH_INTERVAL),
                ),
                "schedule_enabled": entry.options.get(
                    CONF_SCHEDULE_ENABLED,
                    entry.data.get(CONF_SCHEDULE_ENABLED),
                ),
                "inactive_interval": entry.options.get(
                    CONF_INACTIVE_INTERVAL,
                    entry.data.get(CONF_INACTIVE_INTERVAL),
                ),
                "active_windows": entry.options.get(
                    CONF_ACTIVE_WINDOWS,
                    entry.data.get(CONF_ACTIVE_WINDOWS),
                ),
            },
            "usage_metrics": usage_tracker.as_dict() if usage_tracker else None,
        }

    # Build departure info (safe to expose)
    departures_info = []
    if coordinator.data:
        departures = coordinator.data.get("departures", [])
        for dep in departures[:10]:
            departures_info.append({
                "line": dep.line_short_name,
                "line_name": dep.line_name,
                "line_color": dep.line_color,
                "line_text_color": dep.line_text_color,
                "destination": dep.destination,
                "departure_time": dep.departure_time.isoformat(),
                "minutes_until": dep.minutes_until,
                "waiting_time": dep.waiting_time,
                "is_realtime": dep.is_realtime,
                "transport_mode": dep.transport_mode,
            })

    # Build alerts info
    alerts_info = []
    if coordinator.data:
        alerts = coordinator.data.get("alerts", [])
        for alert in alerts:
            alerts_info.append({
                "id": alert.id,
                "title": alert.title,
                "severity": alert.severity,
                "is_active": alert.is_active,
                "start_time": alert.start_time.isoformat() if alert.start_time else None,
                "end_time": alert.end_time.isoformat() if alert.end_time else None,
                "affected_lines": alert.affected_lines,
            })

    # Build outages info
    outages_info = []
    if coordinator.data:
        outages = coordinator.data.get("outages", [])
        for outage in outages:
            outages_info.append({
                "id": outage.id,
                "equipment_type": outage.equipment_type,
                "station_name": outage.station_name,
                "description": outage.description,
                "start_time": outage.start_time.isoformat() if outage.start_time else None,
                "end_time": outage.end_time.isoformat() if outage.end_time else None,
            })

    # Stop info
    stop_info = None
    if coordinator.stop_info:
        stop_info = {
            "stop_id": coordinator.stop_info.stop_id,
            "name": coordinator.stop_info.name,
            "city": coordinator.stop_info.city,
        }

    # Coordinator state
    coordinator_state = {
        "stop_id": coordinator.stop_id,
        "stop_name": coordinator.stop_name,
        "line_id": coordinator.line_id,
        "route_id": coordinator.route_id,
        "update_strategy": coordinator._update_strategy,
        "static_interval": coordinator._static_interval,
        "messages_refresh_interval": coordinator._messages_refresh_interval,
        "outages_refresh_interval": coordinator._outages_refresh_interval,
        "last_api_fetch": coordinator._last_api_fetch.isoformat() if coordinator._last_api_fetch else None,
        "last_alert_fetch": coordinator._last_alert_fetch.isoformat() if coordinator._last_alert_fetch else None,
        "last_outage_fetch": coordinator._last_outage_fetch.isoformat() if coordinator._last_outage_fetch else None,
        "departure_count": len(coordinator.departures),
        "alert_count": len(coordinator.alerts),
        "outage_count": len(coordinator.outages),
        "has_scheduled_refresh": coordinator._scheduled_refresh is not None,
    }

    return {
        "config_entry": config_data,
        "coordinator": coordinator_state,
        "stop_info": stop_info,
        "departures": departures_info,
        "alerts": alerts_info,
        "outages": outages_info,
    }
