"""Tisseo API client."""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

import json

import aiohttp
from aiohttp import ClientTimeout

from .const import API_BASE_URL, API_TIMEOUT

# Toulouse timezone
TOULOUSE_TZ = ZoneInfo("Europe/Paris")

_LOGGER = logging.getLogger(__name__)

GTFS_DATASET_METADATA_URL = (
    "https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/tisseo-gtfs"
)
GTFS_DEFAULT_EXPORT_URL = (
    "https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/"
    "tisseo-gtfs/alternative_exports/utf_8tisseo_gtfs_v2_zip"
)
GTFS_CACHE_TTL_SECONDS = 12 * 60 * 60
GTFS_FAILURE_RETRY_SECONDS = 10 * 60
GTFS_DOWNLOAD_TIMEOUT_SECONDS = 45
GTFS_ROUTE_ID_PREFIX = "gtfs_dir"
GTFS_MODE_IDS_ORDER = [
    "gtfs:metro",
    "gtfs:lineo",
    "gtfs:tramway",
    "gtfs:bus",
    "gtfs:teleo",
]
GTFS_MODE_NAMES: dict[str, str] = {
    "gtfs:metro": "Métro",
    "gtfs:lineo": "Linéo",
    "gtfs:tramway": "Tramway",
    "gtfs:bus": "Bus",
    "gtfs:teleo": "Téléo",
}
GTFS_LINEO_PATTERN = re.compile(r"^L\d+$", re.IGNORECASE)


@dataclass
class Departure:
    """Represents a single bus/tram departure."""

    line_short_name: str
    line_name: str
    line_color: str  # hex background color, e.g. "#e46809"
    line_text_color: str  # hex foreground/text color, e.g. "#FFFFFF"
    destination: str
    departure_time: datetime
    waiting_time: str
    is_realtime: bool
    transport_mode: str

    @property
    def minutes_until(self) -> int:
        """Calculate minutes until departure."""
        now = datetime.now(TOULOUSE_TZ)
        delta = self.departure_time - now
        return max(0, int(delta.total_seconds() / 60))


@dataclass
class StopInfo:
    """Information about a stop."""

    stop_id: str
    name: str
    city: str


@dataclass
class TransportMode:
    """Transport mode (Metro, Tram, Bus, Linéo)."""

    id: str
    name: str


@dataclass
class Terminus:
    """A terminus (direction endpoint) on a line."""

    id: str  # stop_area ID, e.g. "stop_area:SA_206"
    name: str
    city_name: str


@dataclass
class Line:
    """A transit line."""

    id: str
    short_name: str
    name: str
    color: str  # hex background color, e.g. "#e46809"
    text_color: str = "#FFFFFF"  # hex foreground/text color
    transport_mode: str = ""
    terminus: list[Terminus] | None = None


@dataclass
class Route:
    """A route (direction) on a line — mapped from a terminus stop area."""

    id: str  # terminus stop_area ID
    name: str  # terminus name (e.g. "Ramonville")
    direction: str  # same as name, kept for backwards compat


@dataclass
class Stop:
    """A stop on a route."""

    id: str
    name: str
    display_name: str  # Name with direction context


@dataclass
class ServiceAlert:
    """A service alert/message for a line or the network."""

    id: str
    title: str
    content: str
    severity: str  # "info", "warning", "critical"
    start_time: datetime | None
    end_time: datetime | None
    affected_lines: list[str]  # Line IDs affected
    is_active: bool


@dataclass
class Outage:
    """An elevator/escalator outage on a line."""

    id: str
    equipment_type: str  # "elevator" or "escalator"
    station_name: str
    description: str
    start_time: datetime | None
    end_time: datetime | None
    is_active: bool


@dataclass
class NearbyStopLine:
    """Information about a line serving a nearby stop."""

    line_id: str
    line_short_name: str
    line_name: str
    line_color: str  # hex background color
    line_text_color: str  # hex foreground/text color
    transport_mode: str
    route_id: str
    direction: str
    stop_id: str


@dataclass
class NearbyStop:
    """A stop near the user's location."""

    name: str
    latitude: float
    longitude: float
    distance: int  # Distance in meters
    lines: list[NearbyStopLine]


class TisseoApiError(Exception):
    """Base exception for Tisseo API errors."""


class TisseoAuthError(TisseoApiError):
    """Authentication error."""


class TisseoConnectionError(TisseoApiError):
    """Connection error."""


@dataclass
class _GtfsHierarchyCache:
    """Cached GTFS hierarchy for selector steps (modes/lines/routes/stops)."""

    fetched_at: datetime
    archive_bytes: bytes
    modes: list[TransportMode]
    lines_by_mode: dict[str, list[Line]]
    line_by_id: dict[str, Line]
    routes_by_line: dict[str, list[Route]]
    stops_by_line_route: dict[tuple[str, str], list[Stop]]
    stop_info_by_id: dict[str, StopInfo]
    lines_by_stop_area: dict[str, list[dict[str, str]]]
    direction_id_by_line_route: dict[tuple[str, str], str]
    stop_points_by_area: dict[str, set[str]]


class TisseoApiClient:
    """Client for the Tisseo API."""

    def __init__(
        self,
        api_key: str | None = None,
        use_mock: bool = False,
        session: aiohttp.ClientSession | None = None,
        debug: bool = False,
    ) -> None:
        """Initialize the API client."""
        self._api_key = api_key
        self._use_mock = use_mock
        self._session = session
        self._timeout = ClientTimeout(total=API_TIMEOUT)
        self._debug = debug
        self._usage_callback: Callable[[str, bool, int | None, str], None] | None = None
        self._gtfs_cache: _GtfsHierarchyCache | None = None
        self._gtfs_export_url: str = GTFS_DEFAULT_EXPORT_URL
        self._gtfs_last_failure_at: datetime | None = None
        self._gtfs_lock = asyncio.Lock()

    @property
    def api_key(self) -> str | None:
        """Return API key used for realtime endpoints."""
        return self._api_key

    @api_key.setter
    def api_key(self, value: str | None) -> None:
        """Update API key used for realtime endpoints."""
        self._api_key = value

    @property
    def debug(self) -> bool:
        """Return whether debug mode is enabled."""
        return self._debug

    @debug.setter
    def debug(self, value: bool) -> None:
        """Set debug mode."""
        self._debug = value

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    def _log_debug(self, msg: str, *args: Any) -> None:
        """Log a debug message when debug mode is on."""
        if self._debug:
            _LOGGER.debug("[TISSEO] " + msg, *args)

    def set_usage_callback(
        self, callback: Callable[[str, bool, int | None, str], None] | None
    ) -> None:
        """Set callback invoked for each real API request."""
        self._usage_callback = callback

    def _record_usage(
        self,
        endpoint: str,
        success: bool,
        status: int | None,
        source: str = "api",
    ) -> None:
        """Record one real request via callback."""
        if self._usage_callback is None:
            return
        try:
            self._usage_callback(endpoint, success, status, source)
        except Exception:  # pragma: no cover - defensive safety
            _LOGGER.exception(
                "Failed to record %s usage for endpoint %s",
                source,
                endpoint,
            )

    async def _api_request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        line_id: str | None = None,
        route_id: str | None = None,
    ) -> dict[str, Any]:
        """Make an API request."""
        if self._use_mock:
            _LOGGER.debug("Using mock data for endpoint: %s", endpoint)
            return self._get_mock_response(endpoint, params, line_id=line_id, route_id=route_id)

        if not self._api_key:
            raise TisseoAuthError("API key is required for real API calls")

        url = f"{API_BASE_URL}/{endpoint}"
        params = params or {}
        params["key"] = self._api_key

        # Build a sanitized copy of params for logging (hide API key)
        log_params = {k: v for k, v in params.items() if k != "key"}

        self._log_debug(
            "API REQUEST: GET %s params=%s",
            url,
            json.dumps(log_params, ensure_ascii=False),
        )

        session = await self._get_session()

        try:
            _LOGGER.debug("Making API request to %s", url)
            async with session.get(url, params=params) as response:
                self._log_debug(
                    "API RESPONSE status=%s for %s",
                    response.status,
                    endpoint,
                )

                if response.status == 401:
                    self._record_usage(endpoint, success=False, status=response.status)
                    raise TisseoAuthError("Invalid API key")
                if response.status != 200:
                    self._record_usage(endpoint, success=False, status=response.status)
                    raise TisseoApiError(f"API request failed with status {response.status}")

                try:
                    data = await response.json()
                except Exception:
                    self._record_usage(endpoint, success=False, status=response.status)
                    raise

                self._record_usage(endpoint, success=True, status=response.status)

                self._log_debug(
                    "API RESPONSE BODY for %s:\n%s",
                    endpoint,
                    json.dumps(data, indent=2, ensure_ascii=False),
                )

                return data

        except (aiohttp.ClientError, TimeoutError) as err:
            self._record_usage(endpoint, success=False, status=None)
            self._log_debug("API CONNECTION ERROR for %s: %s", endpoint, err)
            raise TisseoConnectionError(f"Connection error: {err}") from err

    def _get_mock_response(
        self,
        endpoint: str,
        params: dict[str, Any] | None,
        line_id: str | None = None,
        route_id: str | None = None,
    ) -> dict[str, Any]:
        """Get mock response for an endpoint."""
        # Import mock data functions here to avoid circular imports
        from .mock_data import (
            generate_mock_departures,
            generate_mock_lines_response,
            generate_mock_messages_response,
            generate_mock_stop_points_response,
            get_lines_by_mode,
            get_routes_for_line,
            get_stops_for_route,
            get_transport_modes,
        )

        params = params or {}

        if "messages" in endpoint:
            line_id = params.get("lineId")
            return generate_mock_messages_response(line_id=line_id)

        if "stops_schedules" in endpoint:
            stop_id = params.get("stopAreaId") or params.get("stopPointId")
            return generate_mock_departures(
                stop_id=stop_id,
                line_id=line_id,
                route_id=route_id,
            )

        if "stop_points" in endpoint:
            line_id = params.get("lineId")
            route_id = params.get("routeId")
            return generate_mock_stop_points_response(line_id=line_id, route_id=route_id)

        if "lines" in endpoint:
            mode_id = params.get("transportModeId")
            return generate_mock_lines_response(mode_id=mode_id)

        # Default empty response
        return {}

    # ========== GTFS helpers ==========

    async def _resolve_gtfs_export_url(self) -> str:
        """Resolve the current GTFS export URL from dataset metadata."""
        session = await self._get_session()
        try:
            async with session.get(GTFS_DATASET_METADATA_URL) as response:
                if response.status != 200:
                    self._record_usage(
                        "gtfs_dataset_metadata",
                        success=False,
                        status=response.status,
                        source="gtfs",
                    )
                    raise TisseoApiError(
                        f"GTFS metadata request failed with status {response.status}"
                    )
                payload = await response.json()
                self._record_usage(
                    "gtfs_dataset_metadata",
                    success=True,
                    status=response.status,
                    source="gtfs",
                )
        except (aiohttp.ClientError, TimeoutError) as err:
            self._record_usage(
                "gtfs_dataset_metadata",
                success=False,
                status=None,
                source="gtfs",
            )
            raise TisseoConnectionError(f"Connection error: {err}") from err

        exports = payload.get("alternative_exports", [])
        if isinstance(exports, dict):
            exports = [exports]

        for export in exports:
            if not isinstance(export, dict):
                continue
            title = str(export.get("title", "")).lower()
            export_id = str(export.get("id", "")).lower()
            mimetype = str(
                export.get("mimetype", export.get("mime_type", ""))
            ).lower()
            if "zip" not in mimetype:
                continue
            if "gtfs" not in title and "gtfs" not in export_id:
                continue
            if (
                "gtfsrt" in title
                or "gtfs-rt" in title
                or "gtfsrt" in export_id
                or "gtfs-rt" in export_id
            ):
                continue

            url = export.get("url")
            if isinstance(url, str) and url:
                return url

        return GTFS_DEFAULT_EXPORT_URL

    async def _download_gtfs_archive(self) -> bytes:
        """Download the GTFS archive bytes."""
        session = await self._get_session()
        export_url = self._gtfs_export_url

        try:
            export_url = await self._resolve_gtfs_export_url()
            self._gtfs_export_url = export_url
        except Exception as err:  # pragma: no cover - network fallback path
            _LOGGER.debug(
                "Failed to resolve GTFS export URL dynamically, using fallback: %s",
                err,
            )

        try:
            async with session.get(
                export_url,
                allow_redirects=True,
                timeout=ClientTimeout(total=GTFS_DOWNLOAD_TIMEOUT_SECONDS),
            ) as response:
                if response.status != 200:
                    self._record_usage(
                        "gtfs_download",
                        success=False,
                        status=response.status,
                        source="gtfs",
                    )
                    raise TisseoApiError(
                        f"GTFS download request failed with status {response.status}"
                    )
                content = await response.read()
                response_status = response.status
        except (aiohttp.ClientError, TimeoutError) as err:
            self._record_usage(
                "gtfs_download",
                success=False,
                status=None,
                source="gtfs",
            )
            raise TisseoConnectionError(f"Connection error: {err}") from err

        if not content:
            self._record_usage(
                "gtfs_download",
                success=False,
                status=None,
                source="gtfs",
            )
            raise TisseoApiError("GTFS download returned an empty body")

        self._record_usage(
            "gtfs_download",
            success=True,
            status=response_status,
            source="gtfs",
        )

        return content

    @staticmethod
    def _normalize_color(value: str | None, default: str) -> str:
        """Normalize GTFS color fields to #RRGGBB."""
        raw = (value or "").strip().lstrip("#")
        if len(raw) != 6:
            return default
        if not all(c in "0123456789abcdefABCDEF" for c in raw):
            return default
        return f"#{raw.upper()}"

    @staticmethod
    def _map_gtfs_mode(route_type: str, short_name: str) -> str:
        """Map GTFS route_type + line short name to Tisseo mode buckets."""
        if route_type == "1":
            return "gtfs:metro"
        if route_type == "0":
            return "gtfs:tramway"
        if route_type == "6":
            return "gtfs:teleo"
        if route_type == "3" and GTFS_LINEO_PATTERN.match(short_name):
            return "gtfs:lineo"
        return "gtfs:bus"

    @staticmethod
    def _make_gtfs_route_id(line_id: str, direction_id: str) -> str:
        """Build a stable route id for GTFS-derived directions."""
        return f"{GTFS_ROUTE_ID_PREFIX}:{line_id}:{direction_id}"

    @staticmethod
    def _read_gtfs_csv(
        archive: zipfile.ZipFile, filename: str
    ) -> list[dict[str, str]]:
        """Read a GTFS CSV file from an archive."""
        with archive.open(filename) as raw_file:
            reader = csv.DictReader(io.TextIOWrapper(raw_file, encoding="utf-8-sig"))
            return [
                {
                    str(k): (v if isinstance(v, str) else "")
                    for k, v in row.items()
                    if k is not None
                }
                for row in reader
            ]

    def _parse_gtfs_hierarchy(self, archive_bytes: bytes) -> _GtfsHierarchyCache:
        """Parse GTFS static data into selectors hierarchy."""
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            routes_rows = self._read_gtfs_csv(archive, "routes.txt")
            trips_rows = self._read_gtfs_csv(archive, "trips.txt")
            stops_rows = self._read_gtfs_csv(archive, "stops.txt")

            selected_trip_by_direction: dict[tuple[str, str], str] = {}
            headsign_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
            for trip in trips_rows:
                line_id = trip.get("route_id", "").strip()
                trip_id = trip.get("trip_id", "").strip()
                if not line_id or not trip_id:
                    continue

                direction_id = trip.get("direction_id", "").strip() or "0"
                key = (line_id, direction_id)

                if key not in selected_trip_by_direction:
                    selected_trip_by_direction[key] = trip_id

                headsign = trip.get("trip_headsign", "").strip()
                if headsign:
                    headsign_counts[key][headsign] += 1

            selected_trip_ids = set(selected_trip_by_direction.values())
            stop_times_by_trip: dict[str, list[tuple[int, str]]] = defaultdict(list)
            with archive.open("stop_times.txt") as raw_file:
                reader = csv.DictReader(io.TextIOWrapper(raw_file, encoding="utf-8-sig"))
                for row in reader:
                    trip_id = str(row.get("trip_id", "")).strip()
                    if trip_id not in selected_trip_ids:
                        continue

                    stop_id = str(row.get("stop_id", "")).strip()
                    if not stop_id:
                        continue

                    try:
                        stop_sequence = int(str(row.get("stop_sequence", "")).strip())
                    except ValueError:
                        continue

                    stop_times_by_trip[trip_id].append((stop_sequence, stop_id))

        stops_by_id: dict[str, dict[str, str]] = {}
        for stop in stops_rows:
            stop_id = stop.get("stop_id", "").strip()
            if not stop_id:
                continue
            stops_by_id[stop_id] = {
                "name": stop.get("stop_name", "").strip() or stop_id,
                "parent_station": stop.get("parent_station", "").strip(),
                "location_type": stop.get("location_type", "").strip() or "0",
            }

        stop_points_by_area: dict[str, set[str]] = defaultdict(set)
        for stop_id, stop_meta in stops_by_id.items():
            parent_station = stop_meta.get("parent_station", "")
            location_type = stop_meta.get("location_type", "0")
            if location_type == "0" and parent_station:
                stop_points_by_area[parent_station].add(stop_id)
            elif location_type == "1":
                stop_points_by_area.setdefault(stop_id, set())

        lines_by_mode: dict[str, list[Line]] = defaultdict(list)
        line_by_id: dict[str, Line] = {}
        for route in routes_rows:
            line_id = route.get("route_id", "").strip()
            if not line_id:
                continue

            short_name = route.get("route_short_name", "").strip() or line_id
            mode_id = self._map_gtfs_mode(
                route.get("route_type", "").strip(),
                short_name,
            )
            mode_name = GTFS_MODE_NAMES.get(mode_id, GTFS_MODE_NAMES["gtfs:bus"])

            line = Line(
                id=line_id,
                short_name=short_name,
                name=route.get("route_long_name", "").strip() or short_name,
                color=self._normalize_color(route.get("route_color"), "#808080"),
                text_color=self._normalize_color(
                    route.get("route_text_color"), "#FFFFFF"
                ),
                transport_mode=mode_name,
            )
            line_by_id[line_id] = line
            lines_by_mode[mode_id].append(line)

        for lines in lines_by_mode.values():
            lines.sort(key=lambda line: (line.short_name, line.name, line.id))

        modes = [
            TransportMode(id=mode_id, name=GTFS_MODE_NAMES[mode_id])
            for mode_id in GTFS_MODE_IDS_ORDER
            if lines_by_mode.get(mode_id)
        ]

        routes_by_line: dict[str, list[Route]] = defaultdict(list)
        stops_by_line_route: dict[tuple[str, str], list[Stop]] = {}
        direction_id_by_line_route: dict[tuple[str, str], str] = {}

        used_route_ids_by_line: dict[str, set[str]] = defaultdict(set)
        for (line_id, direction_id), trip_id in selected_trip_by_direction.items():
            if line_id not in line_by_id:
                continue

            counter = headsign_counts[(line_id, direction_id)]
            headsign = counter.most_common(1)[0][0] if counter else f"Direction {direction_id}"
            stop_rows = stop_times_by_trip.get(trip_id, [])
            ordered_stops = sorted(stop_rows, key=lambda item: item[0])

            route_id = self._make_gtfs_route_id(line_id, direction_id)
            if ordered_stops:
                terminus_stop_id = ordered_stops[-1][1]
                terminus_meta = stops_by_id.get(terminus_stop_id, {})
                terminus_parent = terminus_meta.get("parent_station", "")
                candidate_route_id = terminus_parent or terminus_stop_id
                if candidate_route_id and candidate_route_id not in used_route_ids_by_line[line_id]:
                    route_id = candidate_route_id

            used_route_ids_by_line[line_id].add(route_id)
            route = Route(
                id=route_id,
                name=headsign,
                direction=headsign,
            )
            routes_by_line[line_id].append(route)
            direction_id_by_line_route[(line_id, route_id)] = direction_id

            seen_names: set[str] = set()
            route_stops: list[Stop] = []
            for _, stop_id in ordered_stops:
                stop_meta = stops_by_id.get(stop_id)
                if not stop_meta:
                    continue

                stop_name = stop_meta["name"]
                parent_station = stop_meta["parent_station"]
                if parent_station and parent_station in stops_by_id:
                    parent_name = stops_by_id[parent_station]["name"]
                    if parent_name:
                        stop_name = parent_name

                if stop_name in seen_names:
                    continue
                seen_names.add(stop_name)

                route_stops.append(
                    Stop(
                        id=stop_id,
                        name=stop_name,
                        display_name=f"{stop_name} (→ {headsign})",
                    )
                )

            if route_stops:
                stops_by_line_route[(line_id, route_id)] = route_stops

        for line_id in routes_by_line:
            routes_by_line[line_id].sort(key=lambda route: route.name)

        stop_info_by_id: dict[str, StopInfo] = {}
        for stop_id, stop_meta in stops_by_id.items():
            stop_name = stop_meta["name"]
            parent_station = stop_meta["parent_station"]
            if parent_station and parent_station in stops_by_id:
                parent_name = stops_by_id[parent_station]["name"]
                if parent_name:
                    stop_name = parent_name
            stop_info_by_id[stop_id] = StopInfo(
                stop_id=stop_id,
                name=stop_name,
                city="",
            )

        lines_by_stop_area_dedup: dict[str, dict[tuple[str, str], dict[str, str]]] = defaultdict(dict)
        for (line_id, route_id), route_stops in stops_by_line_route.items():
            line = line_by_id.get(line_id)
            if line is None:
                continue

            route_direction = route_id
            for route in routes_by_line.get(line_id, []):
                if route.id == route_id:
                    route_direction = route.direction
                    break

            for stop in route_stops:
                stop_meta = stops_by_id.get(stop.id, {})
                parent_station = stop_meta.get("parent_station", "")
                stop_area_id = parent_station or stop.id

                dedupe_key = (line_id, route_id)
                lines_by_stop_area_dedup[stop_area_id][dedupe_key] = {
                    "line_id": line.id,
                    "line_short_name": line.short_name,
                    "line_name": line.name,
                    "line_color": line.color,
                    "line_text_color": line.text_color,
                    "transport_mode": line.transport_mode,
                    "route_id": route_id,
                    "direction": route_direction,
                    "stop_id": stop_area_id,
                }

        lines_by_stop_area: dict[str, list[dict[str, str]]] = {}
        for stop_area_id, values in lines_by_stop_area_dedup.items():
            entries = list(values.values())
            entries.sort(
                key=lambda item: (
                    item["line_short_name"],
                    item["direction"],
                    item["line_id"],
                )
            )
            lines_by_stop_area[stop_area_id] = entries

        return _GtfsHierarchyCache(
            fetched_at=datetime.now(UTC),
            archive_bytes=archive_bytes,
            modes=modes,
            lines_by_mode=dict(lines_by_mode),
            line_by_id=line_by_id,
            routes_by_line=dict(routes_by_line),
            stops_by_line_route=stops_by_line_route,
            stop_info_by_id=stop_info_by_id,
            lines_by_stop_area=lines_by_stop_area,
            direction_id_by_line_route=direction_id_by_line_route,
            stop_points_by_area=dict(stop_points_by_area),
        )

    async def _get_gtfs_hierarchy(self) -> _GtfsHierarchyCache | None:
        """Return cached GTFS hierarchy, refreshing it when cache is stale."""
        if self._use_mock:
            return None

        now = datetime.now(UTC)
        cache = self._gtfs_cache
        if cache and (now - cache.fetched_at).total_seconds() < GTFS_CACHE_TTL_SECONDS:
            return cache
        if (
            cache is None
            and self._gtfs_last_failure_at is not None
            and (now - self._gtfs_last_failure_at).total_seconds()
            < GTFS_FAILURE_RETRY_SECONDS
        ):
            return None

        async with self._gtfs_lock:
            now = datetime.now(UTC)
            cache = self._gtfs_cache
            if cache and (now - cache.fetched_at).total_seconds() < GTFS_CACHE_TTL_SECONDS:
                return cache
            if (
                cache is None
                and self._gtfs_last_failure_at is not None
                and (now - self._gtfs_last_failure_at).total_seconds()
                < GTFS_FAILURE_RETRY_SECONDS
            ):
                return None

            try:
                archive_bytes = await self._download_gtfs_archive()
                parsed = await asyncio.to_thread(self._parse_gtfs_hierarchy, archive_bytes)
                self._gtfs_cache = parsed
                self._gtfs_last_failure_at = None
                self._log_debug(
                    "Loaded GTFS hierarchy: modes=%d lines=%d routes=%d",
                    len(parsed.modes),
                    sum(len(lines) for lines in parsed.lines_by_mode.values()),
                    sum(len(routes) for routes in parsed.routes_by_line.values()),
                )
                return parsed
            except Exception as err:
                _LOGGER.warning(
                    "Failed to load GTFS hierarchy; falling back to API endpoints: %s",
                    err,
                )
                self._gtfs_last_failure_at = datetime.now(UTC)
                if self._gtfs_cache is not None:
                    _LOGGER.debug("Using stale GTFS cache after refresh failure")
                    return self._gtfs_cache
                return None

    # ========== Transport hierarchy methods ==========

    async def get_transport_modes(self) -> list[TransportMode]:
        """Get available transport modes, preferring GTFS static data."""
        if self._use_mock:
            from .mock_data import get_transport_modes
            modes = get_transport_modes()
            return [TransportMode(id=m["id"], name=m["name"]) for m in modes]

        gtfs = await self._get_gtfs_hierarchy()
        if gtfs and gtfs.modes:
            return gtfs.modes

        data = await self._api_request("rolling_stocks.json")
        stocks = data.get("rollingStocks", [])
        if isinstance(stocks, dict):
            stocks = [stocks]

        self._log_debug(
            "Parsed %d transport modes from rolling_stocks", len(stocks)
        )

        return [
            TransportMode(
                id=s.get("id", ""),
                name=s.get("name", ""),
            )
            for s in stocks
            if s.get("id") and s.get("name")
        ]

    async def get_lines(self, mode_id: str | None = None) -> list[Line]:
        """Get lines, optionally filtered by transport mode (GTFS first)."""
        if self._use_mock:
            from .mock_data import get_lines_by_mode, MOCK_LINES
            if mode_id:
                lines_raw = get_lines_by_mode(mode_id)
            else:
                lines_raw = list(MOCK_LINES.values())
            return [
                Line(
                    id=line.get("id", ""),
                    short_name=line.get("shortName", ""),
                    name=line.get("name", ""),
                    color=line.get("bgXmlColor", "#808080"),
                    text_color=line.get("fgXmlColor", "#FFFFFF"),
                    transport_mode=line.get("transportMode", {}).get("name", ""),
                )
                for line in lines_raw
            ]

        gtfs = await self._get_gtfs_hierarchy()
        if gtfs:
            if mode_id:
                gtfs_lines = gtfs.lines_by_mode.get(mode_id, [])
            else:
                gtfs_lines = [
                    line
                    for lines in gtfs.lines_by_mode.values()
                    for line in lines
                ]
            if gtfs_lines:
                return gtfs_lines

        # Real API: fetch all lines with terminus info
        params = {"displayTerminus": "1"}
        data = await self._api_request("lines.json", params)
        all_lines = data.get("lines", {}).get("line", [])
        if isinstance(all_lines, dict):
            all_lines = [all_lines]

        self._log_debug(
            "Fetched %d total lines from API, filtering by mode_id=%s",
            len(all_lines),
            mode_id,
        )

        # Filter client-side by transport mode
        if mode_id:
            all_lines = [
                l for l in all_lines
                if l.get("transportMode", {}).get("id") == mode_id
            ]
            self._log_debug(
                "After filtering by mode: %d lines", len(all_lines)
            )

        result = []
        for line in all_lines:
            # Parse terminus list
            terminus_raw = line.get("terminus", [])
            if isinstance(terminus_raw, dict):
                terminus_raw = [terminus_raw]

            terminus_list = [
                Terminus(
                    id=t.get("id", ""),
                    name=t.get("name", ""),
                    city_name=t.get("cityName", ""),
                )
                for t in terminus_raw
                if t.get("id")
            ]

            result.append(Line(
                id=line.get("id", ""),
                short_name=line.get("shortName", ""),
                name=line.get("name", ""),
                color=line.get("bgXmlColor", "#808080"),
                text_color=line.get("fgXmlColor", "#FFFFFF"),
                transport_mode=line.get("transportMode", {}).get("name", ""),
                terminus=terminus_list,
            ))

        return result

    async def get_routes(self, line_id: str) -> list[Route]:
        """Get directions for a line, preferring GTFS trip headsigns."""
        if self._use_mock:
            from .mock_data import get_routes_for_line
            routes = get_routes_for_line(line_id)
            return [
                Route(
                    id=r.get("id", ""),
                    name=r.get("name", ""),
                    direction=r.get("direction", r.get("name", "")),
                )
                for r in routes
            ]

        gtfs = await self._get_gtfs_hierarchy()
        if gtfs:
            gtfs_routes = gtfs.routes_by_line.get(line_id, [])
            if gtfs_routes:
                return gtfs_routes

        # Real API: fetch line with terminus info
        params = {"lineId": line_id, "displayTerminus": "1"}
        data = await self._api_request("lines.json", params)
        lines = data.get("lines", {}).get("line", [])
        if isinstance(lines, dict):
            lines = [lines]

        routes = []
        if lines:
            line = lines[0]
            terminus_list = line.get("terminus", [])
            if isinstance(terminus_list, dict):
                terminus_list = [terminus_list]

            self._log_debug(
                "Line %s has %d terminus entries: %s",
                line_id,
                len(terminus_list),
                [t.get("name", "?") for t in terminus_list],
            )

            for terminus in terminus_list:
                tid = terminus.get("id", "")
                tname = terminus.get("name", "")
                city = terminus.get("cityName", "")
                label = f"{tname} ({city})" if city else tname
                if tid:
                    routes.append(Route(
                        id=tid,
                        name=label,
                        direction=tname,
                    ))
        else:
            self._log_debug("No line data returned for lineId=%s", line_id)

        return routes

    async def get_stops(self, line_id: str, route_id: str) -> list[Stop]:
        """Get stops for a specific line and direction, preferring GTFS."""
        if self._use_mock:
            from .mock_data import get_stops_for_route
            stops = get_stops_for_route(line_id, route_id)
        else:
            gtfs = await self._get_gtfs_hierarchy()
            if gtfs:
                gtfs_stops = gtfs.stops_by_line_route.get((line_id, route_id), [])
                if gtfs_stops:
                    return gtfs_stops

            # Real API: fetch physical stops with destination info
            params = {"lineId": line_id, "displayDestinations": "1"}
            data = await self._api_request("stop_points.json", params)
            stop_points = data.get("physicalStops", {}).get("physicalStop", [])
            if isinstance(stop_points, dict):
                stop_points = [stop_points]

            self._log_debug(
                "Fetched %d stop_points for line %s (before direction filter)",
                len(stop_points),
                line_id,
            )

            # Get direction name from the selected terminus
            routes = await self.get_routes(line_id)
            direction = ""
            for r in routes:
                if r.id == route_id:
                    direction = r.direction
                    break

            # Filter: keep only stop points that serve the selected direction.
            # Each physicalStop has destinations[] — an array of stop_area objects.
            # We match on the terminus stop_area ID (route_id).
            stops = []
            seen_names: set[str] = set()
            for sp in stop_points:
                destinations = sp.get("destinations", [])
                if isinstance(destinations, dict):
                    destinations = [destinations]

                # Check if any destination matches the selected terminus
                serves_direction = any(
                    dest.get("id") == route_id
                    for dest in destinations
                )

                if not serves_direction:
                    continue

                # Use the stop point ID (exact physical stop on the right side)
                sp_id = sp.get("id", "")
                name = sp.get("name", "")

                # Avoid duplicates by name (some stops may have multiple
                # stop points in the same direction, e.g. at interchanges)
                if name in seen_names:
                    continue
                seen_names.add(name)

                display = f"{name} (→ {direction})" if direction else name
                stops.append({
                    "id": sp_id,
                    "name": name,
                    "display_name": display,
                })

            self._log_debug(
                "After direction filter (terminus=%s): %d stops",
                route_id,
                len(stops),
            )

        return [
            Stop(
                id=s.get("id", ""),
                name=s.get("name", ""),
                display_name=s.get("display_name", s.get("name", "")),
            )
            for s in stops
        ]

    # ========== Departure methods ==========

    @staticmethod
    def _parse_gtfs_time_to_seconds(value: str) -> int | None:
        """Parse GTFS HH:MM[:SS] into seconds (supports hours >= 24)."""
        parts = value.strip().split(":")
        if len(parts) < 2:
            return None
        try:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2]) if len(parts) > 2 else 0
        except ValueError:
            return None
        if minutes < 0 or minutes > 59 or seconds < 0 or seconds > 59 or hours < 0:
            return None
        return hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _iter_dates(start_date: date, end_date: date) -> list[date]:
        """Build an inclusive date range list."""
        if end_date < start_date:
            return []
        days: list[date] = []
        current = start_date
        while current <= end_date:
            days.append(current)
            current += timedelta(days=1)
        return days

    @staticmethod
    def _parse_yyyymmdd(value: str) -> date | None:
        """Parse YYYYMMDD into date."""
        if len(value) != 8 or not value.isdigit():
            return None
        try:
            return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
        except ValueError:
            return None

    def _is_service_active_on(
        self,
        service_id: str,
        service_date: date,
        calendar_by_service: dict[str, dict[str, str]],
        added_dates: dict[str, set[date]],
        removed_dates: dict[str, set[date]],
    ) -> bool:
        """Check whether a GTFS service_id is active on a given date."""
        if service_date in added_dates.get(service_id, set()):
            return True
        if service_date in removed_dates.get(service_id, set()):
            return False

        calendar_row = calendar_by_service.get(service_id)
        if calendar_row is None:
            return False

        start_date = self._parse_yyyymmdd(calendar_row.get("start_date", ""))
        end_date = self._parse_yyyymmdd(calendar_row.get("end_date", ""))
        if start_date is None or end_date is None:
            return False
        if not (start_date <= service_date <= end_date):
            return False

        weekday_keys = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        weekday_key = weekday_keys[service_date.weekday()]
        return calendar_row.get(weekday_key, "0") == "1"

    def _get_gtfs_direction_id(
        self,
        cache: _GtfsHierarchyCache,
        line_id: str | None,
        route_id: str | None,
    ) -> str | None:
        """Resolve a GTFS direction_id for line+route, if available."""
        if not line_id or not route_id:
            return None

        direction_id = cache.direction_id_by_line_route.get((line_id, route_id))
        if direction_id:
            return direction_id

        if route_id.startswith(f"{GTFS_ROUTE_ID_PREFIX}:{line_id}:"):
            return route_id.rsplit(":", 1)[-1]

        return None

    def _get_gtfs_stop_ids(
        self,
        cache: _GtfsHierarchyCache,
        stop_id: str,
    ) -> set[str]:
        """Resolve stop_point IDs to query in stop_times for a selected stop."""
        if stop_id.startswith("stop_area:"):
            stop_ids = set(cache.stop_points_by_area.get(stop_id, set()))
            if not stop_ids:
                stop_ids.add(stop_id)
            return stop_ids
        return {stop_id}

    async def _get_departures_from_gtfs(
        self,
        stop_id: str,
        line_id: str | None,
        route_id: str | None,
        number: int,
        start_datetime: datetime,
        end_datetime: datetime,
    ) -> list[Departure] | None:
        """Get planned departures from GTFS static feed for a future window."""
        cache = await self._get_gtfs_hierarchy()
        if cache is None:
            return None
        if line_id is None:
            return None

        line = cache.line_by_id.get(line_id)
        if line is None:
            return None

        direction_id: str | None = None
        if route_id:
            direction_id = self._get_gtfs_direction_id(cache, line_id, route_id)
            if direction_id is None:
                # Route mismatch between legacy API IDs and GTFS mapping: fallback to API.
                return None

        query_stop_ids = self._get_gtfs_stop_ids(cache, stop_id)

        try:
            with zipfile.ZipFile(io.BytesIO(cache.archive_bytes)) as archive:
                trips_rows = self._read_gtfs_csv(archive, "trips.txt")
                calendar_rows = self._read_gtfs_csv(archive, "calendar.txt")
                calendar_dates_rows = self._read_gtfs_csv(archive, "calendar_dates.txt")
        except Exception as err:
            _LOGGER.warning("Failed to parse GTFS archive for planned departures: %s", err)
            return None

        service_dates = self._iter_dates(
            start_datetime.date() - timedelta(days=1),
            end_datetime.date(),
        )

        calendar_by_service = {
            row.get("service_id", "").strip(): row
            for row in calendar_rows
            if row.get("service_id", "").strip()
        }
        added_dates: dict[str, set[date]] = defaultdict(set)
        removed_dates: dict[str, set[date]] = defaultdict(set)
        for row in calendar_dates_rows:
            service_id = row.get("service_id", "").strip()
            exception_date = self._parse_yyyymmdd(row.get("date", "").strip())
            if not service_id or exception_date is None:
                continue
            exception_type = row.get("exception_type", "").strip()
            if exception_type == "1":
                added_dates[service_id].add(exception_date)
            elif exception_type == "2":
                removed_dates[service_id].add(exception_date)

        trip_meta: dict[str, tuple[str, list[date]]] = {}
        for trip in trips_rows:
            trip_line_id = trip.get("route_id", "").strip()
            trip_id = trip.get("trip_id", "").strip()
            service_id = trip.get("service_id", "").strip()
            if not trip_id or not service_id:
                continue
            if trip_line_id != line_id:
                continue

            trip_direction = trip.get("direction_id", "").strip() or "0"
            if direction_id is not None and trip_direction != direction_id:
                continue

            active_dates = [
                service_date
                for service_date in service_dates
                if self._is_service_active_on(
                    service_id,
                    service_date,
                    calendar_by_service,
                    added_dates,
                    removed_dates,
                )
            ]
            if not active_dates:
                continue

            headsign = trip.get("trip_headsign", "").strip() or line.name
            trip_meta[trip_id] = (headsign, active_dates)

        if not trip_meta:
            return []

        planned_departures: list[Departure] = []
        try:
            with zipfile.ZipFile(io.BytesIO(cache.archive_bytes)) as archive:
                with archive.open("stop_times.txt") as raw_file:
                    reader = csv.DictReader(
                        io.TextIOWrapper(raw_file, encoding="utf-8-sig")
                    )
                    for row in reader:
                        trip_id = str(row.get("trip_id", "")).strip()
                        if trip_id not in trip_meta:
                            continue

                        stop_time_stop_id = str(row.get("stop_id", "")).strip()
                        if stop_time_stop_id not in query_stop_ids:
                            continue

                        dep_time_str = str(row.get("departure_time", "")).strip() or str(
                            row.get("arrival_time", "")
                        ).strip()
                        dep_seconds = self._parse_gtfs_time_to_seconds(dep_time_str)
                        if dep_seconds is None:
                            continue

                        destination, active_dates = trip_meta[trip_id]
                        for service_date in active_dates:
                            dep_dt = datetime.combine(
                                service_date,
                                datetime.min.time(),
                                TOULOUSE_TZ,
                            )
                            dep_dt += timedelta(seconds=dep_seconds)
                            if dep_dt < start_datetime or dep_dt > end_datetime:
                                continue

                            planned_departures.append(
                                Departure(
                                    line_short_name=line.short_name,
                                    line_name=line.name,
                                    line_color=line.color,
                                    line_text_color=line.text_color,
                                    destination=destination,
                                    departure_time=dep_dt,
                                    waiting_time="?",
                                    is_realtime=False,
                                    transport_mode=line.transport_mode or "Bus",
                                )
                            )
        except Exception as err:
            _LOGGER.warning(
                "Failed to iterate GTFS stop_times for planned departures: %s",
                err,
            )
            return None

        planned_departures.sort(key=lambda dep: dep.departure_time)
        return planned_departures[:number]

    async def get_departures(
        self,
        stop_id: str,
        line_id: str | None = None,
        route_id: str | None = None,
        number: int = 10,
        query_datetime: datetime | None = None,
        query_end_datetime: datetime | None = None,
        display_realtime: bool | None = None,
    ) -> list[Departure]:
        """Get upcoming departures for a stop, optionally filtered by line/route."""
        if query_datetime is not None and not self._use_mock:
            query_datetime = (
                query_datetime.astimezone(TOULOUSE_TZ)
                if query_datetime.tzinfo is not None
                else query_datetime.replace(tzinfo=TOULOUSE_TZ)
            )
        if query_end_datetime is not None and not self._use_mock:
            query_end_datetime = (
                query_end_datetime.astimezone(TOULOUSE_TZ)
                if query_end_datetime.tzinfo is not None
                else query_end_datetime.replace(tzinfo=TOULOUSE_TZ)
            )

        if (
            not self._use_mock
            and query_datetime is not None
            and query_end_datetime is not None
            and display_realtime is False
        ):
            gtfs_departures = await self._get_departures_from_gtfs(
                stop_id=stop_id,
                line_id=line_id,
                route_id=route_id,
                number=number,
                start_datetime=query_datetime,
                end_datetime=query_end_datetime,
            )
            if gtfs_departures is not None:
                _LOGGER.debug(
                    "Using GTFS planned departures for stop=%s line=%s route=%s window=%s..%s count=%d",
                    stop_id,
                    line_id,
                    route_id,
                    query_datetime.isoformat(),
                    query_end_datetime.isoformat(),
                    len(gtfs_departures),
                )
                return gtfs_departures
            _LOGGER.debug(
                "GTFS planned departures unavailable for stop=%s line=%s route=%s; falling back to realtime API",
                stop_id,
                line_id,
                route_id,
            )

        if stop_id.startswith("stop_point:"):
            params = {"stopPointId": stop_id, "number": number}
        else:
            params = {"stopAreaId": stop_id, "number": number}

        # Add line filter if specified (for real API)
        if line_id and not self._use_mock:
            params["lineId"] = line_id

        if query_datetime is not None and not self._use_mock:
            params["datetime"] = query_datetime.strftime("%Y-%m-%d %H:%M")

        if display_realtime is not None and not self._use_mock:
            params["displayRealTime"] = "1" if display_realtime else "0"

        data = await self._api_request(
            "stops_schedules.json",
            params,
            line_id=line_id,
            route_id=route_id,
        )

        departures = []

        # Parse departures — the response structure can vary:
        # Standard: {"departures": {"departure": [...]}}
        # But "departures" may be a list directly, or structured differently
        departures_obj = data.get("departures", {})
        if isinstance(departures_obj, list):
            # "departures" is already a list of departure objects
            departure_data = departures_obj
            self._log_debug(
                "get_departures: 'departures' is a list with %d items",
                len(departure_data),
            )
        elif isinstance(departures_obj, dict):
            departure_data = departures_obj.get("departure", [])
        else:
            departure_data = []

        if isinstance(departure_data, dict):
            departure_data = [departure_data]

        self._log_debug(
            "get_departures: parsing %d departure entries for stop %s",
            len(departure_data),
            stop_id,
        )

        for dep in departure_data:
            try:
                dt_str = dep.get("dateTime", "")
                try:
                    # Parse the datetime and add Toulouse timezone
                    departure_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    departure_time = departure_time.replace(tzinfo=TOULOUSE_TZ)
                except ValueError:
                    _LOGGER.warning("Could not parse departure time: %s", dt_str)
                    continue

                line = dep.get("line", {})
                transport_mode = line.get("transportMode", {})

                # destination can be a dict OR a list of dicts
                dest_raw = dep.get("destination", {})
                if isinstance(dest_raw, list):
                    destination = dest_raw[0] if dest_raw else {}
                else:
                    destination = dest_raw

                realtime_raw = str(dep.get("realTime", "no")).strip().lower()
                is_realtime = realtime_raw in {"1", "yes", "true"}

                departures.append(Departure(
                    line_short_name=line.get("shortName", "?"),
                    line_name=line.get("name", "Unknown Line"),
                    line_color=line.get("bgXmlColor", line.get("color", "#808080")),
                    line_text_color=line.get("fgXmlColor", "#FFFFFF"),
                    destination=destination.get("name", "Unknown"),
                    departure_time=departure_time,
                    waiting_time=dep.get("waitingTime", "?"),
                    is_realtime=is_realtime,
                    transport_mode=transport_mode.get("name", "Bus"),
                ))
            except (KeyError, TypeError) as err:
                _LOGGER.warning("Error parsing departure: %s", err)
                continue

        return departures

    async def get_stop_info(self, stop_id: str) -> StopInfo | None:
        """Get information about a stop."""
        if not self._use_mock:
            gtfs = await self._get_gtfs_hierarchy()
            if gtfs:
                info = gtfs.stop_info_by_id.get(stop_id)
                if info is not None:
                    return info

        if stop_id.startswith("stop_point:"):
            params = {"stopPointId": stop_id, "number": 1}
        else:
            params = {"stopAreaId": stop_id, "number": 1}

        try:
            data = await self._api_request("stops_schedules.json", params)

            # The response structure varies:
            # - Without timetableByArea: {"departures": {"stopArea": {...}, "departure": [...]}}
            # - With timetableByArea=1: {"stopAreas": [...]}
            # Handle both, plus the case where departures is a list
            departures_obj = data.get("departures", {})
            if isinstance(departures_obj, list):
                # departures is a list — no stopArea at this level
                self._log_debug("get_stop_info: 'departures' is a list, not a dict")
                return None

            stop_area = departures_obj.get("stopArea", {})
            if isinstance(stop_area, list) and stop_area:
                stop_area = stop_area[0]

            if stop_area and isinstance(stop_area, dict):
                return StopInfo(
                    stop_id=stop_area.get("id", stop_id),
                    name=stop_area.get("name", "Unknown Stop"),
                    city=stop_area.get("cityName", ""),
                )
        except TisseoApiError as err:
            _LOGGER.warning("Could not get stop info: %s", err)

        return None

    async def search_stops(self, query: str) -> list[dict[str, Any]]:
        """Search for stops by name."""
        params = {"term": query, "number": 10}
        data = await self._api_request("places.json", params)

        places = data.get("placesList", {}).get("place", [])
        if isinstance(places, dict):
            places = [places]

        return [
            {
                "id": place.get("id", ""),
                "name": place.get("label", ""),
                "type": place.get("type", ""),
            }
            for place in places
            if place.get("type") in ("stop_area", "stop_point")
        ]

    async def get_messages(
        self,
        line_id: str | None = None,
    ) -> list[ServiceAlert]:
        """Get service alerts/messages, optionally filtered by line."""
        params = {}
        if line_id:
            params["lineId"] = line_id

        data = await self._api_request("messages.json", params)

        alerts = []
        messages_obj = data.get("messages", {})
        if isinstance(messages_obj, dict):
            messages = messages_obj.get("message", [])
        elif isinstance(messages_obj, list):
            messages = messages_obj
        else:
            messages = []

        if isinstance(messages, dict):
            messages = [messages]

        for msg in messages:
            try:
                # Parse dates
                start_str = msg.get("startDate", "")
                end_str = msg.get("endDate", "")
                start_time = None
                end_time = None

                if start_str:
                    try:
                        start_time = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        pass

                if end_str:
                    try:
                        end_time = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        pass

                # Determine severity from importance or type
                importance = msg.get("importance", "").lower()
                msg_type = msg.get("type", "").lower()

                if importance == "high" or "perturbation" in msg_type:
                    severity = "critical"
                elif importance == "medium" or "travaux" in msg_type:
                    severity = "warning"
                else:
                    severity = "info"

                # Check if alert is currently active
                now = datetime.now(TOULOUSE_TZ)
                is_active = True
                if start_time and now < start_time.replace(tzinfo=TOULOUSE_TZ):
                    is_active = False
                if end_time and now > end_time.replace(tzinfo=TOULOUSE_TZ):
                    is_active = False

                # Extract affected lines
                affected_lines = []
                lines_data = msg.get("lines", {}).get("line", [])
                if isinstance(lines_data, dict):
                    lines_data = [lines_data]
                for line in lines_data:
                    line_id_val = line.get("id", "")
                    if line_id_val:
                        affected_lines.append(line_id_val)

                alerts.append(ServiceAlert(
                    id=msg.get("id", ""),
                    title=msg.get("title", ""),
                    content=msg.get("content", msg.get("text", "")),
                    severity=severity,
                    start_time=start_time,
                    end_time=end_time,
                    affected_lines=affected_lines,
                    is_active=is_active,
                ))
            except (KeyError, TypeError) as err:
                _LOGGER.warning("Error parsing message: %s", err)
                continue

        # Return only active alerts
        return [a for a in alerts if a.is_active]

    async def get_outages(
        self,
        line_id: str | None = None,
    ) -> list[Outage]:
        """Get elevator/escalator outages, optionally filtered by line.

        Uses lines.json with displayOutages=1 to get outage information.
        """
        params: dict[str, Any] = {"displayOutages": "1"}
        if line_id:
            params["lineId"] = line_id

        try:
            data = await self._api_request("lines.json", params)

            outages = []
            lines = data.get("lines", {}).get("line", [])
            if isinstance(lines, dict):
                lines = [lines]

            for line in lines:
                line_outages = line.get("outages", line.get("outage", []))
                if isinstance(line_outages, dict):
                    line_outages = [line_outages]

                station_name = line.get("shortName", "")

                for outage in line_outages:
                    try:
                        outage_id = outage.get("id", "")
                        equipment = outage.get("type", outage.get("equipmentType", ""))
                        eq_type = "elevator" if "ascen" in equipment.lower() or "elev" in equipment.lower() else "escalator"

                        description = outage.get("cause", outage.get("description", outage.get("text", "")))
                        location = outage.get("location", outage.get("stopName", ""))
                        if location:
                            full_desc = f"{location}: {description}" if description else location
                        else:
                            full_desc = description

                        # Parse dates
                        start_str = outage.get("startDate", "")
                        end_str = outage.get("endDate", "")
                        start_time = None
                        end_time = None

                        if start_str:
                            try:
                                start_time = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                pass

                        if end_str:
                            try:
                                end_time = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                pass

                        # Check if active
                        now = datetime.now(TOULOUSE_TZ)
                        is_active = True
                        if start_time and now < start_time.replace(tzinfo=TOULOUSE_TZ):
                            is_active = False
                        if end_time and now > end_time.replace(tzinfo=TOULOUSE_TZ):
                            is_active = False

                        outages.append(Outage(
                            id=outage_id or f"outage_{len(outages)}",
                            equipment_type=eq_type,
                            station_name=location or station_name,
                            description=full_desc,
                            start_time=start_time,
                            end_time=end_time,
                            is_active=is_active,
                        ))
                    except (KeyError, TypeError) as err:
                        _LOGGER.warning("Error parsing outage: %s", err)
                        continue

            # Return only active outages
            return [o for o in outages if o.is_active]

        except TisseoApiError as err:
            _LOGGER.warning("Could not fetch outages: %s", err)
            return []

    async def get_nearby_stops(
        self,
        latitude: float,
        longitude: float,
        max_distance: int = 500,
        max_results: int = 10,
    ) -> list[NearbyStop]:
        """Find stops near a given location.

        Args:
            latitude: User's latitude
            longitude: User's longitude
            max_distance: Maximum distance in meters (default 500m)
            max_results: Maximum number of results

        Returns:
            List of nearby stops with their lines, sorted by distance
        """
        if self._use_mock:
            from .mock_data import get_nearby_stops_with_lines

            nearby = get_nearby_stops_with_lines(
                latitude, longitude, max_distance, max_results
            )
        else:
            # Real API: use places.json with coordinates
            params = {
                "x": str(longitude),
                "y": str(latitude),
                "srid": "4326",
                "number": max_results,
                "displayOnlyStopAreas": "1",
            }
            data = await self._api_request("places.json", params)

            places = data.get("placesList", {}).get("place", [])
            if isinstance(places, dict):
                places = [places]

            nearby = []
            for place in places:
                if place.get("type") != "stop_area":
                    continue

                # Calculate distance if not provided
                place_lat = float(place.get("y", 0))
                place_lon = float(place.get("x", 0))
                distance = self._haversine_distance(
                    latitude, longitude, place_lat, place_lon
                )

                if distance > max_distance:
                    continue

                # Get lines for this stop
                stop_id = place.get("id", "")
                lines_data = await self._get_lines_for_stop(stop_id)

                nearby.append({
                    "name": place.get("label", ""),
                    "latitude": place_lat,
                    "longitude": place_lon,
                    "distance": round(distance),
                    "lines": lines_data,
                })

        # Convert to dataclass objects
        results = []
        for stop in nearby:
            lines = [
                NearbyStopLine(
                    line_id=line.get("line_id", ""),
                    line_short_name=line.get("line_short_name", ""),
                    line_name=line.get("line_name", ""),
                    line_color=line.get("line_color", "#808080"),
                    line_text_color=line.get("line_text_color", "#FFFFFF"),
                    transport_mode=line.get("transport_mode", "Bus"),
                    route_id=line.get("route_id", ""),
                    direction=line.get("direction", ""),
                    stop_id=line.get("stop_id", ""),
                )
                for line in stop.get("lines", [])
            ]

            results.append(NearbyStop(
                name=stop.get("name", ""),
                latitude=stop.get("latitude", 0),
                longitude=stop.get("longitude", 0),
                distance=stop.get("distance", 0),
                lines=lines,
            ))

        return results

    async def _get_lines_for_stop(self, stop_id: str) -> list[dict]:
        """Get lines serving a specific stop (GTFS first, API fallback)."""
        gtfs = await self._get_gtfs_hierarchy()
        if gtfs:
            gtfs_lines = gtfs.lines_by_stop_area.get(stop_id, [])
            if gtfs_lines:
                return gtfs_lines

        try:
            params = {"stopAreaId": stop_id}
            data = await self._api_request("lines.json", params)

            lines = data.get("lines", {}).get("line", [])
            if isinstance(lines, dict):
                lines = [lines]

            result = []
            for line in lines:
                # Get routes for direction info
                routes = line.get("routes", {}).get("route", [])
                if isinstance(routes, dict):
                    routes = [routes]

                for route in routes:
                    result.append({
                        "line_id": line.get("id", ""),
                        "line_short_name": line.get("shortName", ""),
                        "line_name": line.get("name", ""),
                        "line_color": line.get("bgXmlColor", line.get("color", "#808080")),
                        "line_text_color": line.get("fgXmlColor", "#FFFFFF"),
                        "transport_mode": line.get("transportMode", {}).get("name", "Bus"),
                        "route_id": route.get("id", ""),
                        "direction": route.get("direction", {}).get("name", ""),
                        "stop_id": stop_id,
                    })

            return result
        except TisseoApiError:
            return []

    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate the great-circle distance between two points in meters."""
        import math

        R = 6371000  # Earth's radius in meters

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def get_gtfs_diagnostics(self) -> dict[str, Any]:
        """Return GTFS cache/network diagnostics."""
        now = datetime.now(UTC)
        cache = self._gtfs_cache

        cache_fetched_at = cache.fetched_at.isoformat() if cache else None
        cache_age_seconds = (
            int((now - cache.fetched_at).total_seconds()) if cache else None
        )

        mode_count = len(cache.modes) if cache else 0
        line_count = (
            sum(len(lines) for lines in cache.lines_by_mode.values()) if cache else 0
        )
        route_count = (
            sum(len(routes) for routes in cache.routes_by_line.values()) if cache else 0
        )
        stop_mapping_count = len(cache.stops_by_line_route) if cache else 0

        return {
            "enabled": not self._use_mock,
            "cache_loaded": cache is not None,
            "cache_fetched_at": cache_fetched_at,
            "cache_age_seconds": cache_age_seconds,
            "cache_ttl_seconds": GTFS_CACHE_TTL_SECONDS,
            "failure_retry_seconds": GTFS_FAILURE_RETRY_SECONDS,
            "last_failure_at": (
                self._gtfs_last_failure_at.isoformat()
                if self._gtfs_last_failure_at
                else None
            ),
            "current_export_url": self._gtfs_export_url,
            "mode_count": mode_count,
            "line_count": line_count,
            "route_count": route_count,
            "stop_mapping_count": stop_mapping_count,
        }

    async def close(self) -> None:
        """Close the API client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
