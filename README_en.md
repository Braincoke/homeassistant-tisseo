# Tisseo Integration for Home Assistant

A custom Home Assistant integration for [Tisseo](https://www.tisseo.fr/), the public transit network of Toulouse, France. Monitor real-time departures, service alerts, and transit information for any stop on the network (Metro, Tram, Bus, and Lineo lines).

## Legal Disclaimer

- This is an **unofficial** community Home Assistant integration.
- I have **zero affiliation** with Tisseo.
- The "Tisseo" name is used in this repository for discoverability only.
- If Tisseo decides this repository cannot use that name, they can contact me at: `braincoke+contact@protonmail.com`.

## Data License

Transit data reused by this integration comes from Tisseo/Toulouse Metropole Open Data and is subject to **ODbL 1.0**.

- ODbL full text: https://opendatacommons.org/licenses/odbl/1-0/
- Toulouse Metropole license page: https://data.toulouse-metropole.fr/page/licence

## Features

- **Guided setup wizard** - Select your transport mode, line, direction, and stop through a step-by-step config flow. No need to know stop IDs or API parameters.
- **GTFS-backed referential data** - Transport modes, lines, directions, stop lists, and line colors are loaded from the official weekly GTFS feed when available, reducing realtime API usage.
- **Three update strategies** - Choose between regular polling, smart departure-based scheduling, or time-window scheduling.
- **Time-window strategy (recommended)** - Uses realtime smart updates during your active periods (for example morning/evening commute), then switches to GTFS-based cached departures outside those windows to minimize realtime API usage.
- **Real-time departures** - Shows next departures with real-time vs scheduled indicators.
- **Service alerts** - Monitors active Tisseo service alerts for your line, with new-alert detection for notification automations.
- **Official line colors** - Reads `bgXmlColor` and `fgXmlColor` from the Tisseo API, so every line renders with its official branding colors in the companion cards.
- **Manual refresh button** - Each stop device includes a button entity to trigger an on-demand data refresh.
- **Planned departures action** - Call a built-in service to fetch departures for a future time window (for example tomorrow morning), using GTFS first (with API fallback), and optionally storing the result on a dedicated sensor per stop.
- **Debug mode** - Optional toggle to log all API calls and responses (sanitized) with the `[TISSEO]` prefix.
- **French and English translations** - Full UI translations for both languages.

## Prerequisites

You need a **Tisseo Open Data API key**. Request one for free at:
https://data.toulouse-metropole.fr/ (or via the Tisseo Open Data portal).

## Installation

### Manual

1. Copy the `tisseo` folder into your Home Assistant `custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings > Devices & Services > Add Integration** and search for **Tisseo**.

### HACS (Custom Repository)

1. In HACS, click the 3-dot menu > **Custom repositories**.
2. Add the repository URL with category **Integration**.
3. Install **Tisseo** and restart Home Assistant.

## Configuration

The integration is fully configured through the UI in two phases:

1. Add **Tisseo** once to create the global **Tisseo API Usage** entry:
1. Enter API key (or mock mode), debug mode, update strategy, and refresh intervals.
1. If strategy is time windows, configure windows.
1. Save.
1. Use **Add entry** to add stops:
1. Select transport mode, line, direction, and stop.
1. Configure the imminent departure threshold for that stop.

Stop entries represent **one stop** on **one line** in **one direction**. Add multiple stop entries as needed.

## Entities

Each configured stop creates a device with the following entities:

### Sensors

| Entity | State | Description |
|--------|-------|-------------|
| **Departures** | Count (int) | Number of upcoming departures. Attributes contain the full array of departure objects including line, line_color, line_text_color, destination, departure_time, minutes_until, waiting_time, is_realtime, transport_mode. Also includes alerts, stop_name, stop_city, and timestamps. **This is the main entity consumed by the companion Lovelace cards.** |
| **Next departure** | Timestamp | Absolute datetime of the next departure. HA renders this as relative time ("in 4 minutes") automatically. Useful for time-based automations. |
| **Minutes until departure** | Integer (min) | Minutes until the next departure. Useful for threshold-based automations and history graphs. |
| **Line** | String | Short name of the next line (e.g., "A", "L6"). Attributes include line_name, line_color, transport_mode. |
| **Destination** | String | Destination name of the next departure. |
| **Planned departures** | Count (int) | Number of departures in the last requested future window for that stop. Attributes include `window_start`, `window_end`, `summary`, and full `departures` list for notifications/dashboards. |
| **API calls total** | Count (int) | Global counter of realtime API requests (`api.tisseo.fr`) across all Tisseo entries, grouped under the dedicated **Tisseo API Usage** device. Attributes include last_call, last_success, daily_calls_30d, endpoint_calls_top, and GTFS totals. |
| **API calls successful** | Count (int) | Number of successful realtime API calls. |
| **API calls failed** | Count (int) | Number of failed realtime API calls (HTTP errors, auth errors, connection errors, timeouts). |
| **API calls today** | Count (int) | Number of realtime API calls made today (Toulouse timezone). |
| **GTFS calls total** | Count (int) | Counter for GTFS network requests (dataset metadata + GTFS ZIP download). Attributes include GTFS endpoint breakdown and GTFS daily history. |
| **GTFS calls successful** | Count (int) | Number of successful GTFS requests. |
| **GTFS calls failed** | Count (int) | Number of failed GTFS requests. |
| **GTFS calls today** | Count (int) | Number of GTFS requests made today (Toulouse timezone). |

### Binary Sensors

| Entity | State | Description |
|--------|-------|-------------|
| **Imminent departure** | on/off | Turns ON when the next departure is within the configured threshold (default: 2 minutes). Device class: `occupancy`. |
| **Service alerts** | on/off | Turns ON when there are active Tisseo service alerts for the line. Attributes include alert_count, alerts array, new_alerts for notification automations. Device class: `problem`. |

### Buttons

| Entity | Description |
|--------|-------------|
| **Refresh departures** | Press to trigger an immediate departures refresh. In time-window mode outside active windows, this uses GTFS planned data (no realtime API fallback). Otherwise it uses one realtime departures API call. Service alerts/outages keep their normal cached refresh cadence. |

## Update Strategies

### Time windows (recommended)

Best balance for most users and best way to reduce API usage.

How it works:
- During configured active windows, it uses **smart** scheduling with realtime API departures.
- Outside active windows, it keeps refreshing at the configured **off-window interval** but serves departures from **GTFS cached data**.
- Outside active windows, realtime departures API fallback is disabled for departures.
- Set off-window interval to `0` to disable updates outside windows.

Typical use case:
- Morning commute window (for example `06:30-09:00`)
- Evening window (for example `16:30-20:00`)
- Minimal or no polling outside those periods

### Smart (default if no windows are configured)

Schedules API calls based on the *next departure* instead of polling continuously:
- If no departures are known, retries in **60s**.
- If the next departure is in more than **60s**, refreshes at **T-60s**.
- If the next departure is already within **60s**, refreshes at **T+20s**.
- If the displayed departure has already passed, retries in **20s**.
- Enforces a minimum delay of **10s** between smart refreshes.
- Updates the displayed countdown every **30s** (no API call).

This minimizes API usage while ensuring data is fresh at the moments that matter.

See [SMART_DEPARTURES_STRATEGY.md](SMART_DEPARTURES_STRATEGY.md) for full behavior details and troubleshooting.

### Regular (fixed interval)

Polls the API at a fixed interval (default: 60 seconds). Configure the interval in the options flow.

Note: this strategy is called `static` internally in code/options, but represents regular polling.

## Entity ID Format

All entity IDs follow a consistent pattern:

```
sensor.tisseo_<transport>_<line>_<stop>_<direction>_<type>
```

Examples:
- `sensor.tisseo_metro_a_mermoz_balma_gramont_departures`
- `sensor.tisseo_lineo_l6_castanet_tolosan_ramonville_minutes_until`
- `binary_sensor.tisseo_tram_t1_arenes_aeroconstellation_imminent`
- `button.tisseo_bus_14_rangueil_aeroport_refresh`

## Automation Examples

### Notify when bus is arriving

```yaml
automation:
  - alias: "Bus arriving notification"
    trigger:
      - platform: state
        entity_id: binary_sensor.tisseo_lineo_l6_castanet_tolosan_ramonville_imminent
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "Bus L6 arriving!"
          message: "Your bus is arriving in {{ state_attr('sensor.tisseo_lineo_l6_castanet_tolosan_ramonville_minutes_until', 'state') }} minutes"
```

### Notify on new service alert

```yaml
automation:
  - alias: "Tisseo service alert"
    trigger:
      - platform: state
        entity_id: binary_sensor.tisseo_metro_a_mermoz_balma_gramont_alerts
        to: "on"
    condition:
      - condition: template
        value_template: "{{ state_attr('binary_sensor.tisseo_metro_a_mermoz_balma_gramont_alerts', 'new_alerts') | length > 0 }}"
    action:
      - service: notify.mobile_app
        data:
          title: "Tisseo Alert"
          message: "{{ state_attr('binary_sensor.tisseo_metro_a_mermoz_balma_gramont_alerts', 'first_new_alert_title') }}"
```

## Options Flow

After setup, use the integration's **Configure** button:

- On the **Tisseo API Usage** entry: global settings (update strategy, intervals, time windows, debug) and API key rotation.
  Use the options menu to either edit settings or change update strategy.
- On each **stop** entry: stop-specific imminent threshold.

## Services

### `tisseo.get_planned_departures`

Fetch departures for a future datetime window for one configured stop.

Inputs:
- `stop_entity_id`: any sensor entity from the target stop entry.
- `start_datetime`: start window (`YYYY-MM-DD HH:MM` or ISO datetime).
- `end_datetime`: end window (`YYYY-MM-DD HH:MM` or ISO datetime).
- `number` (optional): max departures requested before window filtering (default: `40`).
- `display_realtime` (optional): use real-time values (default: `false`).
- `store_result` (optional): write payload to the stop's **Planned departures** sensor (default: `true`).

Returns:
- `count` and `departures` for the requested window.

## Debug Mode

When enabled, the integration logs request/response details at `DEBUG` level with prefix `[TISSEO]`. API keys are redacted from logged URLs.

To see these logs in Home Assistant, enable logger debug for the integration:

```yaml
logger:
  logs:
    custom_components.tisseo: debug
```

## Tisseo API Reference

See [TISSEO_API_REFERENCE.md](TISSEO_API_REFERENCE.md) for detailed API documentation, endpoint details, and response structures.
See [GTFS_USAGE.md](GTFS_USAGE.md) for GTFS coverage, fallback rules, and what still uses realtime APIs.
For future-window planning (example: tomorrow 07:40-08:15 fetched at 20:00), see [PLANNED_WINDOW_DEPARTURES.md](PLANNED_WINDOW_DEPARTURES.md).

## Companion Cards

This integration is designed to work with the **Tisseo Departures Cards** Lovelace frontend:

- `custom:tisseo-departures-card` - Single stop departure display
- `custom:tisseo-departures-multi-card` - Multiple stops in a compact list
- `custom:tisseo-nearby-stops-card` - Nearby stops based on location

The cards automatically read `line_color` and `line_text_color` from the sensor attributes, so every line displays with its official Tisseo branding.

## Data Attribution

Data provided by [Tisseo Open Data](https://data.toulouse-metropole.fr/).

## License

- Source code: [MIT](LICENSE)
- Open Data: [ODbL 1.0](LICENSE-ODbL-1.0.md)
