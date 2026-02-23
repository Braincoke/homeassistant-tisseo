"""Tisseo API client."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import json

import aiohttp
from aiohttp import ClientTimeout

from .const import API_BASE_URL, API_TIMEOUT

# Toulouse timezone
TOULOUSE_TZ = ZoneInfo("Europe/Paris")

_LOGGER = logging.getLogger(__name__)


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
        self._usage_callback: Callable[[str, bool, int | None], None] | None = None

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
        self, callback: Callable[[str, bool, int | None], None] | None
    ) -> None:
        """Set callback invoked for each real API request."""
        self._usage_callback = callback

    def _record_usage(self, endpoint: str, success: bool, status: int | None) -> None:
        """Record one real API request via callback."""
        if self._usage_callback is None:
            return
        try:
            self._usage_callback(endpoint, success, status)
        except Exception:  # pragma: no cover - defensive safety
            _LOGGER.exception("Failed to record API usage for endpoint %s", endpoint)

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

    # ========== Transport hierarchy methods ==========

    async def get_transport_modes(self) -> list[TransportMode]:
        """Get available transport modes using rolling_stocks endpoint."""
        if self._use_mock:
            from .mock_data import get_transport_modes
            modes = get_transport_modes()
            return [TransportMode(id=m["id"], name=m["name"]) for m in modes]

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
        """Get lines, optionally filtered by transport mode.

        Uses displayTerminus=1 to include terminus stop areas for each line,
        and filters client-side by transportMode.id.
        """
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
        """Get directions for a line using terminus stop areas.

        The Tisseo API represents directions as terminus[] on each line.
        Each terminus is a stop_area that the line ends at.
        For example, Tram L6 has terminus "Ramonville" and "Castanet-Tolosan".
        """
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
        """Get stops for a specific line filtered by direction.

        Uses stop_points.json with displayDestinations=1.
        Each physicalStop has a destinations[] listing the terminus stop_areas
        reachable from that specific stop pole. We filter to keep only the
        stop points whose destinations include the selected terminus (route_id).

        This gives exactly the stops on the correct side of the road for the
        chosen direction, with no duplicates.

        route_id is a terminus stop_area ID (e.g. "stop_area:SA_206").
        """
        if self._use_mock:
            from .mock_data import get_stops_for_route
            stops = get_stops_for_route(line_id, route_id)
        else:
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

    async def get_departures(
        self,
        stop_id: str,
        line_id: str | None = None,
        route_id: str | None = None,
        number: int = 10,
        query_datetime: datetime | None = None,
        display_realtime: bool | None = None,
    ) -> list[Departure]:
        """Get upcoming departures for a stop, optionally filtered by line/route."""
        if stop_id.startswith("stop_point:"):
            params = {"stopPointId": stop_id, "number": number}
        else:
            params = {"stopAreaId": stop_id, "number": number}

        # Add line filter if specified (for real API)
        if line_id and not self._use_mock:
            params["lineId"] = line_id

        if query_datetime is not None and not self._use_mock:
            local_dt = (
                query_datetime.astimezone(TOULOUSE_TZ)
                if query_datetime.tzinfo is not None
                else query_datetime.replace(tzinfo=TOULOUSE_TZ)
            )
            params["datetime"] = local_dt.strftime("%Y-%m-%d %H:%M")

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
        """Get lines serving a specific stop (for real API)."""
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

    async def close(self) -> None:
        """Close the API client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
