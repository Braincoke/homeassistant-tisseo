"""Tests for GTFS hierarchy parsing and mode mapping."""

from __future__ import annotations

import asyncio
import csv
import io
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.tisseo.api import TisseoApiClient

TOULOUSE_TZ = ZoneInfo("Europe/Paris")


def _csv_bytes(headers: list[str], rows: list[list[str]]) -> str:
    """Build CSV content with a deterministic UTF-8 header."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()


def _build_minimal_gtfs_zip() -> bytes:
    """Create a minimal valid GTFS archive for parsing tests."""
    routes = _csv_bytes(
        [
            "route_id",
            "agency_id",
            "route_short_name",
            "route_long_name",
            "route_color",
            "route_text_color",
            "route_type",
        ],
        [
            ["line:61", "network:1", "A", "Basso Cambo / Balma-Gramont", "db001b", "ffffff", "1"],
            ["line:170", "network:1", "L6", "Ramonville / Castanet-Tolosan", "00AA33", "FFFFFF", "3"],
            ["line:25", "network:1", "25", "A / B", "123456", "ffffff", "3"],
            ["line:68", "network:1", "T1", "Palais de Justice / MEETT", "004687", "ffffff", "0"],
            ["line:204", "network:1", "TELEO", "UPS / Oncopole", "dc006b", "ffffff", "6"],
        ],
    )
    trips = _csv_bytes(
        [
            "route_id",
            "service_id",
            "trip_id",
            "direction_id",
            "trip_headsign",
            "shape_id",
        ],
        [
            ["line:61", "svc", "trip_metro_0", "0", "Balma-Gramont", "shape1"],
            ["line:61", "svc", "trip_metro_1", "1", "Basso Cambo", "shape2"],
            ["line:170", "svc", "trip_lineo_0", "0", "Castanet-Tolosan", "shape3"],
            ["line:25", "svc", "trip_bus_0", "0", "Terminus Bus", "shape4"],
            ["line:68", "svc", "trip_tram_0", "0", "MEETT", "shape5"],
            ["line:204", "svc", "trip_teleo_0", "0", "Oncopole", "shape6"],
        ],
    )
    stops = _csv_bytes(
        [
            "stop_id",
            "stop_code",
            "stop_name",
            "stop_lat",
            "stop_lon",
            "location_type",
            "parent_station",
            "wheelchair_boarding",
        ],
        [
            ["stop_area:SA_1", "", "Mermoz", "43.60", "1.43", "1", "", "1"],
            ["stop_area:SA_2", "", "Arènes", "43.59", "1.41", "1", "", "1"],
            ["stop_area:SA_3", "", "Ramonville", "43.56", "1.47", "1", "", "1"],
            ["stop_point:SP_1", "", "Mermoz quai 1", "43.60", "1.43", "0", "stop_area:SA_1", "1"],
            ["stop_point:SP_2", "", "Arènes quai 1", "43.59", "1.41", "0", "stop_area:SA_2", "1"],
            ["stop_point:SP_3", "", "Ramonville quai 1", "43.56", "1.47", "0", "stop_area:SA_3", "1"],
        ],
    )
    stop_times = _csv_bytes(
        [
            "trip_id",
            "arrival_time",
            "departure_time",
            "stop_id",
            "pickup_type",
            "drop_off_type",
            "stop_sequence",
        ],
        [
            ["trip_metro_0", "07:00:00", "07:00:00", "stop_point:SP_1", "0", "0", "1"],
            ["trip_metro_0", "07:02:00", "07:02:00", "stop_point:SP_2", "0", "0", "2"],
            ["trip_metro_1", "07:00:00", "07:00:00", "stop_point:SP_2", "0", "0", "1"],
            ["trip_metro_1", "07:02:00", "07:02:00", "stop_point:SP_1", "0", "0", "2"],
            ["trip_lineo_0", "08:00:00", "08:00:00", "stop_point:SP_1", "0", "0", "1"],
            ["trip_lineo_0", "08:05:00", "08:05:00", "stop_point:SP_3", "0", "0", "2"],
            ["trip_bus_0", "08:10:00", "08:10:00", "stop_point:SP_1", "0", "0", "1"],
            ["trip_tram_0", "09:00:00", "09:00:00", "stop_point:SP_2", "0", "0", "1"],
            ["trip_teleo_0", "10:00:00", "10:00:00", "stop_point:SP_3", "0", "0", "1"],
        ],
    )
    agency = _csv_bytes(["agency_id", "agency_name", "agency_url", "agency_timezone"], [["network:1", "Tisseo", "https://example.com", "Europe/Paris"]])
    calendar = _csv_bytes(
        ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"],
        [["svc", "1", "1", "1", "1", "1", "1", "1", "20260101", "20261231"]],
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("agency.txt", agency)
        archive.writestr("calendar.txt", calendar)
        archive.writestr("routes.txt", routes)
        archive.writestr("trips.txt", trips)
        archive.writestr("stops.txt", stops)
        archive.writestr("stop_times.txt", stop_times)
        archive.writestr("calendar_dates.txt", "service_id,date,exception_type\n")
        archive.writestr("transfers.txt", "from_stop_id,to_stop_id,transfer_type\n")
        archive.writestr("shapes.txt", "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n")
    return buffer.getvalue()


def test_parse_gtfs_hierarchy_mode_mapping_and_colors() -> None:
    """GTFS route_type + short_name must map to expected modes and colors."""
    client = TisseoApiClient(api_key=None, use_mock=False)
    parsed = client._parse_gtfs_hierarchy(_build_minimal_gtfs_zip())

    mode_ids = [mode.id for mode in parsed.modes]
    assert "gtfs:metro" in mode_ids
    assert "gtfs:lineo" in mode_ids
    assert "gtfs:bus" in mode_ids
    assert "gtfs:tramway" in mode_ids
    assert "gtfs:teleo" in mode_ids

    lineo_lines = parsed.lines_by_mode["gtfs:lineo"]
    assert any(line.short_name == "L6" for line in lineo_lines)

    metro_line = next(
        line for line in parsed.lines_by_mode["gtfs:metro"] if line.short_name == "A"
    )
    assert metro_line.color == "#DB001B"
    assert metro_line.text_color == "#FFFFFF"


def test_parse_gtfs_hierarchy_routes_and_stops() -> None:
    """Directions should be built from trips and stops from stop_times sequence."""
    client = TisseoApiClient(api_key=None, use_mock=False)
    parsed = client._parse_gtfs_hierarchy(_build_minimal_gtfs_zip())

    metro_routes = parsed.routes_by_line["line:61"]
    assert len(metro_routes) == 2
    route_names = {route.name for route in metro_routes}
    assert "Balma-Gramont" in route_names
    assert "Basso Cambo" in route_names

    balma_route = next(route for route in metro_routes if route.name == "Balma-Gramont")
    route_stops = parsed.stops_by_line_route[("line:61", balma_route.id)]
    assert [stop.id for stop in route_stops] == ["stop_point:SP_1", "stop_point:SP_2"]
    assert route_stops[0].name == "Mermoz"
    assert "Balma-Gramont" in route_stops[0].display_name

    assert parsed.stop_info_by_id["stop_point:SP_1"].name == "Mermoz"
    lines_at_area = parsed.lines_by_stop_area["stop_area:SA_1"]
    assert any(item["line_short_name"] == "A" for item in lines_at_area)


def test_planned_departures_uses_gtfs_window() -> None:
    """Planned windows should be resolvable from GTFS without realtime API."""
    client = TisseoApiClient(api_key=None, use_mock=False)
    parsed = client._parse_gtfs_hierarchy(_build_minimal_gtfs_zip())
    client._gtfs_cache = parsed

    start = datetime(2026, 2, 24, 6, 50, tzinfo=TOULOUSE_TZ)
    end = datetime(2026, 2, 24, 7, 10, tzinfo=TOULOUSE_TZ)

    departures = asyncio.run(
        client._get_departures_from_gtfs(
            stop_id="stop_area:SA_1",
            line_id="line:61",
            route_id="stop_area:SA_1",
            number=20,
            start_datetime=start,
            end_datetime=end,
        )
    )

    assert departures is not None
    assert len(departures) == 1
    assert departures[0].line_short_name == "A"
    assert departures[0].destination == "Basso Cambo"
    assert departures[0].is_realtime is False
