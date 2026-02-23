"""Tests for Tisseo API dataclasses and parsing logic."""
import pytest
from datetime import datetime, timedelta
from dataclasses import dataclass


# We test the dataclass structures and their computed properties
# by importing from the actual api module
from custom_components.tisseo.api import (
    Departure,
    Line,
    NearbyStop,
    NearbyStopLine,
    Outage,
    Route,
    ServiceAlert,
    StopInfo,
    Stop,
)


class TestDepartureDataclass:
    """Test the Departure dataclass."""

    def _make_departure(self, **kwargs) -> Departure:
        """Create a Departure with sensible defaults."""
        defaults = {
            "line_short_name": "A",
            "line_name": "Ligne A",
            "line_color": "#E3007A",
            "line_text_color": "#FFFFFF",
            "destination": "Balma-Gramont",
            "departure_time": datetime.now() + timedelta(minutes=5),
            "waiting_time": "00:05:00",
            "is_realtime": True,
            "transport_mode": "Métro",
        }
        defaults.update(kwargs)
        return Departure(**defaults)

    def test_basic_creation(self):
        dep = self._make_departure()
        assert dep.line_short_name == "A"
        assert dep.destination == "Balma-Gramont"
        assert dep.is_realtime is True

    def test_minutes_until(self):
        dep = self._make_departure(
            departure_time=datetime.now() + timedelta(minutes=5)
        )
        # minutes_until is computed from departure_time
        assert isinstance(dep.minutes_until, int)
        assert 4 <= dep.minutes_until <= 6

    def test_minutes_until_negative(self):
        dep = self._make_departure(
            departure_time=datetime.now() - timedelta(minutes=2)
        )
        assert dep.minutes_until < 0

    def test_minutes_until_zero(self):
        dep = self._make_departure(
            departure_time=datetime.now()
        )
        assert dep.minutes_until <= 0

    def test_line_color_hex(self):
        dep = self._make_departure(line_color="#e46809")
        assert dep.line_color == "#e46809"

    def test_line_text_color(self):
        dep = self._make_departure(line_text_color="#000000")
        assert dep.line_text_color == "#000000"


class TestOutageDataclass:
    """Test the Outage dataclass."""

    def test_elevator_outage(self):
        outage = Outage(
            id="out_1",
            equipment_type="elevator",
            station_name="Jean Jaurès",
            description="Ascenseur en panne sortie 3",
            start_time=datetime.now() - timedelta(hours=2),
            end_time=None,
            is_active=True,
        )
        assert outage.equipment_type == "elevator"
        assert outage.is_active is True
        assert outage.station_name == "Jean Jaurès"

    def test_escalator_outage(self):
        outage = Outage(
            id="out_2",
            equipment_type="escalator",
            station_name="Capitole",
            description="Escalator direction surface",
            start_time=datetime.now() - timedelta(days=1),
            end_time=datetime.now() + timedelta(days=3),
            is_active=True,
        )
        assert outage.equipment_type == "escalator"

    def test_inactive_outage(self):
        outage = Outage(
            id="out_3",
            equipment_type="elevator",
            station_name="Esquirol",
            description="Réparé",
            start_time=datetime.now() - timedelta(days=5),
            end_time=datetime.now() - timedelta(days=1),
            is_active=False,
        )
        assert outage.is_active is False


class TestServiceAlertDataclass:
    """Test the ServiceAlert dataclass."""

    def test_active_alert(self):
        alert = ServiceAlert(
            id="alert_1",
            title="Travaux ligne A",
            content="Interruption de service entre Basso Cambo et Mermoz",
            severity="warning",
            start_time=datetime.now() - timedelta(hours=1),
            end_time=datetime.now() + timedelta(hours=5),
            affected_lines=["line:A"],
            is_active=True,
        )
        assert alert.severity == "warning"
        assert alert.is_active is True
        assert "line:A" in alert.affected_lines

    def test_critical_alert(self):
        alert = ServiceAlert(
            id="alert_2",
            title="Service interrompu",
            content="Accident sur la voie",
            severity="critical",
            start_time=datetime.now(),
            end_time=None,
            affected_lines=["line:B"],
            is_active=True,
        )
        assert alert.severity == "critical"

    def test_info_alert(self):
        alert = ServiceAlert(
            id="alert_3",
            title="Information",
            content="Nouvelle desserte depuis le 1er janvier",
            severity="info",
            start_time=None,
            end_time=None,
            affected_lines=[],
            is_active=True,
        )
        assert alert.severity == "info"
        assert len(alert.affected_lines) == 0


class TestStopInfoDataclass:
    """Test the StopInfo dataclass."""

    def test_basic_stop_info(self):
        stop = StopInfo(
            stop_id="stop_area:SA:1234",
            name="Jean Jaurès",
            city="Toulouse",
            latitude=43.6047,
            longitude=1.4442,
        )
        assert stop.name == "Jean Jaurès"
        assert stop.city == "Toulouse"
        assert stop.latitude == pytest.approx(43.6047)


class TestNearbyStopDataclass:
    """Test the NearbyStop dataclass."""

    def test_nearby_stop_with_lines(self):
        lines = [
            NearbyStopLine(
                line_id="line:A",
                line_short_name="A",
                line_name="Ligne A",
                line_color="#E3007A",
                line_text_color="#FFFFFF",
                transport_mode="Métro",
                direction="Balma-Gramont",
            ),
            NearbyStopLine(
                line_id="line:B",
                line_short_name="B",
                line_name="Ligne B",
                line_color="#FFCD00",
                line_text_color="#000000",
                transport_mode="Métro",
                direction="Ramonville",
            ),
        ]

        stop = NearbyStop(
            name="Jean Jaurès",
            latitude=43.6046,
            longitude=1.4493,
            distance=120,
            lines=lines,
        )

        assert stop.name == "Jean Jaurès"
        assert stop.distance == 120
        assert len(stop.lines) == 2
        assert stop.lines[0].line_short_name == "A"
        assert stop.lines[1].line_color == "#FFCD00"


class TestLineAndRoute:
    """Test Line and Route dataclasses."""

    def test_line(self):
        line = Line(
            id="line:A",
            short_name="A",
            name="Ligne A",
            color="#E3007A",
            text_color="#FFFFFF",
            transport_mode="Métro",
        )
        assert line.short_name == "A"
        assert line.color == "#E3007A"

    def test_route(self):
        route = Route(
            id="route:A:1",
            name="Balma-Gramont → Basso Cambo",
            direction="Basso Cambo",
            line_id="line:A",
        )
        assert route.direction == "Basso Cambo"
        assert route.line_id == "line:A"

    def test_stop(self):
        stop = Stop(
            id="stop_point:SP:1234",
            name="Jean Jaurès",
            city="Toulouse",
        )
        assert stop.name == "Jean Jaurès"
