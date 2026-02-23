"""Tests for Tisseo helper functions (sanitize, unique key generation, icons, models)."""
import pytest

from custom_components.tisseo.helpers import (
    get_device_model,
    get_transport_icon,
    make_unique_key,
    sanitize,
)


class TestSanitize:
    """Test the sanitize helper function."""

    def test_basic_ascii(self):
        assert sanitize("hello") == "hello"

    def test_uppercase_to_lower(self):
        assert sanitize("Hello World") == "hello_world"

    def test_french_accents(self):
        assert sanitize("Métro") == "metro"
        assert sanitize("Linéo") == "lineo"
        assert sanitize("François") == "francois"
        assert sanitize("Ramonville") == "ramonville"

    def test_complex_accents(self):
        assert sanitize("Castanet-Tolosan") == "castanet_tolosan"
        assert sanitize("Balma-Gramont") == "balma_gramont"
        assert sanitize("Basso Cambo") == "basso_cambo"

    def test_colons_replaced(self):
        assert sanitize("Line:A") == "line_a"

    def test_dashes_replaced(self):
        assert sanitize("Jean-Jaurès") == "jean_jaures"

    def test_multiple_spaces(self):
        assert sanitize("Jean   Jaurès") == "jean_jaures"

    def test_consecutive_underscores_collapsed(self):
        assert sanitize("a - b - c") == "a_b_c"

    def test_leading_trailing_underscores_stripped(self):
        assert sanitize(" hello ") == "hello"
        assert sanitize("-hello-") == "hello"

    def test_empty_string(self):
        assert sanitize("") == ""

    def test_real_stop_names(self):
        """Test with real Tisseo stop names."""
        assert sanitize("Université Paul Sabatier") == "universite_paul_sabatier"
        assert sanitize("Esquirol") == "esquirol"
        assert sanitize("Saint-Cyprien - République") == "saint_cyprien_republique"


class TestMakeUniqueKey:
    """Test the make_unique_key helper function."""

    def test_metro_a(self):
        key = make_unique_key("Métro", "A", "Mermoz", "Balma-Gramont")
        assert key == "tisseo_metro_a_mermoz_balma_gramont"

    def test_bus_line(self):
        key = make_unique_key("Bus", "L6", "Castanet-Tolosan", "Ramonville")
        assert key == "tisseo_bus_l6_castanet_tolosan_ramonville"

    def test_lineo(self):
        key = make_unique_key("Linéo", "L1", "Arènes", "Colomiers")
        assert key == "tisseo_lineo_l1_arenes_colomiers"

    def test_tramway(self):
        key = make_unique_key("Tramway", "T1", "Palais de Justice", "Aéroport")
        assert key == "tisseo_tramway_t1_palais_de_justice_aeroport"

    def test_starts_with_domain(self):
        key = make_unique_key("Bus", "14", "Capitole", "Rangueil")
        assert key.startswith("tisseo_")

    def test_empty_parts_skipped(self):
        key = make_unique_key("Bus", "", "Capitole", "")
        assert key == "tisseo_bus_capitole"

    def test_all_parts_present(self):
        key = make_unique_key("Métro", "B", "Jean Jaurès", "Borderouge")
        parts = key.split("_")
        assert parts[0] == "tisseo"
        assert "metro" in key
        assert "b" in parts
        assert "jean" in key
        assert "jaures" in key
        assert "borderouge" in key


class TestGetTransportIcon:
    """Test the get_transport_icon helper function."""

    def test_metro(self):
        assert get_transport_icon("Métro") == "mdi:subway-variant"
        assert get_transport_icon("Metro") == "mdi:subway-variant"

    def test_tram(self):
        assert get_transport_icon("Tramway") == "mdi:tram"
        assert get_transport_icon("Tram") == "mdi:tram"

    def test_bus(self):
        assert get_transport_icon("Bus") == "mdi:bus"

    def test_lineo(self):
        assert get_transport_icon("Linéo") == "mdi:bus-articulated-front"
        assert get_transport_icon("Lineo") == "mdi:bus-articulated-front"

    def test_unknown_returns_default(self):
        assert get_transport_icon("Unknown") == "mdi:bus"

    def test_none_returns_default(self):
        assert get_transport_icon(None) == "mdi:bus"


class TestGetDeviceModel:
    """Test the get_device_model helper function."""

    def test_metro(self):
        assert get_device_model("Métro") == "Metro Station"
        assert get_device_model("Metro") == "Metro Station"

    def test_tram(self):
        assert get_device_model("Tramway") == "Tram Stop"
        assert get_device_model("Tram") == "Tram Stop"

    def test_bus(self):
        assert get_device_model("Bus") == "Bus Stop"

    def test_lineo(self):
        assert get_device_model("Linéo") == "Linéo Stop"

    def test_unknown_returns_default(self):
        assert get_device_model("Unknown") == "Bus Stop"

    def test_none_returns_default(self):
        assert get_device_model(None) == "Bus Stop"
