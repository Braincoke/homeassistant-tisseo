# GTFS Usage in the Integration

This document explains what is now sourced from GTFS, what still uses the realtime API, and the fallback behavior.

Checked against the live Toulouse Metropole feed on **February 24, 2026**.

## GTFS source

- Dataset metadata:
  - `https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/tisseo-gtfs`
- Download endpoint (resolved dynamically from `alternative_exports`):
  - `.../alternative_exports/utf_8tisseo_gtfs_v2_zip`

The integration resolves this URL dynamically and then downloads the GTFS ZIP.

## Coverage validation

From the live GTFS archive:

- Files present: `agency.txt`, `calendar.txt`, `calendar_dates.txt`, `routes.txt`, `shapes.txt`, `stop_times.txt`, `stops.txt`, `transfers.txt`, `trips.txt`
- `routes.txt` rows: `124`
- `route_color` populated: `124/124`
- `route_text_color` populated: `124/124`

So line colors are fully available in GTFS for current data.

## What now uses GTFS first

These methods now load from GTFS cache first and fall back to API only if GTFS is unavailable:

- `get_transport_modes()`
- `get_lines()`
- `get_routes()`
- `get_stops()`
- `get_stop_info()`
- `_get_lines_for_stop()` (used by nearby stops enrichment)

Code: `api.py`

## What still uses the realtime API

These remain API-based by design:

- `get_departures()` -> `stops_schedules.json` (realtime/theoretical departures)
- `get_messages()` -> `messages.json` (service messages)
- `get_outages()` -> `lines.json?displayOutages=1` (equipment outages)
- `get_nearby_stops()` -> `places.json` for geospatial search (line enrichment now uses GTFS when possible)

## Discrepancies and fallback strategy

### Directions model mismatch

- GTFS directions come from `trips.direction_id` + `trip_headsign`.
- Realtime API directions come from `lines.terminus[]`.

To preserve compatibility with existing entries, route IDs are derived from the GTFS direction terminus stop area when possible.
If no unambiguous terminus can be derived, a fallback synthetic ID is used:

- `gtfs_dir:<line_id>:<direction_id>`

### Color mismatch handling

- Primary color source for referential steps: GTFS (`route_color`, `route_text_color`)
- Runtime departure colors still come from realtime payload when present.
- Existing fallback remains in coordinator/sensors (`line_color` from config entry or default).

### Availability fallback

If GTFS download/parse fails:

1. Use stale cached GTFS if available.
2. Otherwise fall back to current API endpoints (`rolling_stocks`, `lines`, `stop_points`).

This keeps setup resilient while still minimizing API usage when GTFS is healthy.
