"""Mock data for Tisseo API responses.

This module provides realistic mock data based on the Tisseo API v2.1 response format.
Used for development and testing when an API key is not available.
"""
from datetime import datetime, timedelta
import math
import random
from zoneinfo import ZoneInfo

# Toulouse timezone
TOULOUSE_TZ = ZoneInfo("Europe/Paris")

# Stop coordinates (latitude, longitude) - Real Toulouse coordinates
# These are approximate coordinates for major stops
STOP_COORDINATES = {
    # Metro A stops
    "Basso Cambo": (43.5690, 1.3910),
    "Bellefontaine": (43.5720, 1.3980),
    "Reynerie": (43.5750, 1.4020),
    "Mirail-Université": (43.5780, 1.4060),
    "Bagatelle": (43.5820, 1.4120),
    "Mermoz": (43.5850, 1.4180),
    "Fontaine Lestang": (43.5890, 1.4240),
    "Arènes": (43.5920, 1.4300),
    "Patte d'Oie": (43.5960, 1.4350),
    "St-Cyprien République": (43.5995, 1.4380),
    "Esquirol": (43.6010, 1.4420),
    "Capitole": (43.6045, 1.4440),
    "Jean Jaurès": (43.6065, 1.4490),
    "Marengo SNCF": (43.6110, 1.4540),
    "Jolimont": (43.6150, 1.4600),
    "Roseraie": (43.6180, 1.4660),
    "Argoulets": (43.6210, 1.4720),
    "Balma-Gramont": (43.6240, 1.4790),
    # Metro B stops
    "Borderouge": (43.6410, 1.4520),
    "Trois Cocus": (43.6370, 1.4510),
    "La Vache": (43.6330, 1.4500),
    "Barrière de Paris": (43.6290, 1.4490),
    "Minimes-Claude Nougaro": (43.6250, 1.4480),
    "Canal du Midi": (43.6200, 1.4470),
    "Compans-Caffarelli": (43.6130, 1.4460),
    "Jeanne d'Arc": (43.6100, 1.4470),
    "François Verdier": (43.6050, 1.4520),
    "Carmes": (43.6000, 1.4450),
    "Palais de Justice": (43.5970, 1.4420),
    "St-Michel Marcel Langer": (43.5920, 1.4400),
    "Empalot": (43.5850, 1.4380),
    "Saint-Agne SNCF": (43.5780, 1.4360),
    "Saouzelong": (43.5720, 1.4350),
    "Rangueil": (43.5670, 1.4550),
    "Faculté de Pharmacie": (43.5620, 1.4620),
    "Université Paul Sabatier": (43.5580, 1.4680),
    "Ramonville": (43.5520, 1.4760),
    # Tramway T1 stops
    "Zénith": (43.5940, 1.4250),
    "Ancely": (43.5980, 1.4180),
    "Cartoucherie": (43.6010, 1.4120),
    "Purpan": (43.6060, 1.4050),
    "Aéroconstellation": (43.6280, 1.3680),
    # Tramway T2 stops
    "Ponts Jumeaux": (43.6180, 1.4400),
    "Aéroport": (43.6290, 1.3680),
    # Common stops (shared between lines)
    "Colomiers Gare SNCF": (43.6130, 1.3350),
    "De Gaulle": (43.6070, 1.3580),
    "Colomiers": (43.6100, 1.3400),
    "Labège": (43.5320, 1.5120),
}


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on Earth in meters."""
    R = 6371000  # Earth's radius in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def get_stop_coordinates(stop_name: str) -> tuple[float, float] | None:
    """Get coordinates for a stop by name."""
    return STOP_COORDINATES.get(stop_name)


def find_nearby_stops(
    latitude: float,
    longitude: float,
    max_distance: int = 500,
    max_results: int = 10,
) -> list[dict]:
    """Find stops near a given location.

    Args:
        latitude: User's latitude
        longitude: User's longitude
        max_distance: Maximum distance in meters (default 500m)
        max_results: Maximum number of results to return

    Returns:
        List of nearby stops with distance, sorted by distance
    """
    nearby = []

    for stop_name, (lat, lon) in STOP_COORDINATES.items():
        distance = haversine_distance(latitude, longitude, lat, lon)
        if distance <= max_distance:
            nearby.append({
                "name": stop_name,
                "latitude": lat,
                "longitude": lon,
                "distance": round(distance),
            })

    # Sort by distance
    nearby.sort(key=lambda x: x["distance"])

    return nearby[:max_results]


def get_nearby_stops_with_lines(
    latitude: float,
    longitude: float,
    max_distance: int = 500,
    max_results: int = 10,
) -> list[dict]:
    """Find nearby stops with their associated lines and routes.

    Args:
        latitude: User's latitude
        longitude: User's longitude
        max_distance: Maximum distance in meters
        max_results: Maximum number of results

    Returns:
        List of nearby stops with lines, routes, and distance info
    """
    nearby_stops = find_nearby_stops(latitude, longitude, max_distance, max_results * 2)

    results = []

    for stop_info in nearby_stops:
        stop_name = stop_info["name"]

        # Find all lines/routes that serve this stop
        lines_at_stop = []
        for line_id, line_data in MOCK_LINES_DATA.items():
            for route_id, route_data in line_data.get("routes", {}).items():
                for stop in route_data.get("stops", []):
                    if stop["name"] == stop_name:
                        # Find the stop_id
                        stop_id = stop["id"]
                        lines_at_stop.append({
                            "line_id": line_id,
                            "line_short_name": line_data["shortName"],
                            "line_name": line_data["name"],
                            "line_color": line_data["color"],
                            "transport_mode": line_data["transportMode"]["name"],
                            "route_id": route_id,
                            "direction": route_data["direction"],
                            "stop_id": stop_id,
                        })
                        break

        if lines_at_stop:
            results.append({
                "name": stop_name,
                "latitude": stop_info["latitude"],
                "longitude": stop_info["longitude"],
                "distance": stop_info["distance"],
                "lines": lines_at_stop,
            })

            if len(results) >= max_results:
                break

    return results

# Transport modes
TRANSPORT_MODES = {
    "metro": {"id": "1", "name": "Métro", "article": "de"},
    "tram": {"id": "2", "name": "Tramway", "article": "de"},
    "bus": {"id": "3", "name": "Bus", "article": "de"},
    "lineo": {"id": "4", "name": "Linéo", "article": "de"},
}

# Complete line data with routes (directions) and stops
MOCK_LINES_DATA = {
    # Metro Lines
    "line:A": {
        "id": "line:A",
        "shortName": "A",
        "name": "Métro A",
        "network": "Tisseo",
        "color": "#E3007A",
        "bgXmlColor": "#E3007A",
        "fgXmlColor": "#FFFFFF",
        "transportMode": TRANSPORT_MODES["metro"],
        "routes": {
            "route:A:1": {
                "id": "route:A:1",
                "name": "Basso Cambo → Balma-Gramont",
                "direction": "Balma-Gramont",
                "stops": [
                    {"id": "stop_point:A1_1", "name": "Basso Cambo"},
                    {"id": "stop_point:A1_2", "name": "Bellefontaine"},
                    {"id": "stop_point:A1_3", "name": "Reynerie"},
                    {"id": "stop_point:A1_4", "name": "Mirail-Université"},
                    {"id": "stop_point:A1_5", "name": "Bagatelle"},
                    {"id": "stop_point:A1_6", "name": "Mermoz"},
                    {"id": "stop_point:A1_7", "name": "Fontaine Lestang"},
                    {"id": "stop_point:A1_8", "name": "Arènes"},
                    {"id": "stop_point:A1_9", "name": "Patte d'Oie"},
                    {"id": "stop_point:A1_10", "name": "St-Cyprien République"},
                    {"id": "stop_point:A1_11", "name": "Esquirol"},
                    {"id": "stop_point:A1_12", "name": "Capitole"},
                    {"id": "stop_point:A1_13", "name": "Jean Jaurès"},
                    {"id": "stop_point:A1_14", "name": "Marengo SNCF"},
                    {"id": "stop_point:A1_15", "name": "Jolimont"},
                    {"id": "stop_point:A1_16", "name": "Roseraie"},
                    {"id": "stop_point:A1_17", "name": "Argoulets"},
                    {"id": "stop_point:A1_18", "name": "Balma-Gramont"},
                ],
            },
            "route:A:2": {
                "id": "route:A:2",
                "name": "Balma-Gramont → Basso Cambo",
                "direction": "Basso Cambo",
                "stops": [
                    {"id": "stop_point:A2_1", "name": "Balma-Gramont"},
                    {"id": "stop_point:A2_2", "name": "Argoulets"},
                    {"id": "stop_point:A2_3", "name": "Roseraie"},
                    {"id": "stop_point:A2_4", "name": "Jolimont"},
                    {"id": "stop_point:A2_5", "name": "Marengo SNCF"},
                    {"id": "stop_point:A2_6", "name": "Jean Jaurès"},
                    {"id": "stop_point:A2_7", "name": "Capitole"},
                    {"id": "stop_point:A2_8", "name": "Esquirol"},
                    {"id": "stop_point:A2_9", "name": "St-Cyprien République"},
                    {"id": "stop_point:A2_10", "name": "Patte d'Oie"},
                    {"id": "stop_point:A2_11", "name": "Arènes"},
                    {"id": "stop_point:A2_12", "name": "Fontaine Lestang"},
                    {"id": "stop_point:A2_13", "name": "Mermoz"},
                    {"id": "stop_point:A2_14", "name": "Bagatelle"},
                    {"id": "stop_point:A2_15", "name": "Mirail-Université"},
                    {"id": "stop_point:A2_16", "name": "Reynerie"},
                    {"id": "stop_point:A2_17", "name": "Bellefontaine"},
                    {"id": "stop_point:A2_18", "name": "Basso Cambo"},
                ],
            },
        },
    },
    "line:B": {
        "id": "line:B",
        "shortName": "B",
        "name": "Métro B",
        "network": "Tisseo",
        "color": "#FFCD00",
        "bgXmlColor": "#FFCD00",
        "fgXmlColor": "#000000",
        "transportMode": TRANSPORT_MODES["metro"],
        "routes": {
            "route:B:1": {
                "id": "route:B:1",
                "name": "Borderouge → Ramonville",
                "direction": "Ramonville",
                "stops": [
                    {"id": "stop_point:B1_1", "name": "Borderouge"},
                    {"id": "stop_point:B1_2", "name": "Trois Cocus"},
                    {"id": "stop_point:B1_3", "name": "La Vache"},
                    {"id": "stop_point:B1_4", "name": "Barrière de Paris"},
                    {"id": "stop_point:B1_5", "name": "Minimes-Claude Nougaro"},
                    {"id": "stop_point:B1_6", "name": "Canal du Midi"},
                    {"id": "stop_point:B1_7", "name": "Compans-Caffarelli"},
                    {"id": "stop_point:B1_8", "name": "Jeanne d'Arc"},
                    {"id": "stop_point:B1_9", "name": "Jean Jaurès"},
                    {"id": "stop_point:B1_10", "name": "François Verdier"},
                    {"id": "stop_point:B1_11", "name": "Carmes"},
                    {"id": "stop_point:B1_12", "name": "Palais de Justice"},
                    {"id": "stop_point:B1_13", "name": "St-Michel Marcel Langer"},
                    {"id": "stop_point:B1_14", "name": "Empalot"},
                    {"id": "stop_point:B1_15", "name": "Saint-Agne SNCF"},
                    {"id": "stop_point:B1_16", "name": "Saouzelong"},
                    {"id": "stop_point:B1_17", "name": "Rangueil"},
                    {"id": "stop_point:B1_18", "name": "Faculté de Pharmacie"},
                    {"id": "stop_point:B1_19", "name": "Université Paul Sabatier"},
                    {"id": "stop_point:B1_20", "name": "Ramonville"},
                ],
            },
            "route:B:2": {
                "id": "route:B:2",
                "name": "Ramonville → Borderouge",
                "direction": "Borderouge",
                "stops": [
                    {"id": "stop_point:B2_1", "name": "Ramonville"},
                    {"id": "stop_point:B2_2", "name": "Université Paul Sabatier"},
                    {"id": "stop_point:B2_3", "name": "Faculté de Pharmacie"},
                    {"id": "stop_point:B2_4", "name": "Rangueil"},
                    {"id": "stop_point:B2_5", "name": "Saouzelong"},
                    {"id": "stop_point:B2_6", "name": "Saint-Agne SNCF"},
                    {"id": "stop_point:B2_7", "name": "Empalot"},
                    {"id": "stop_point:B2_8", "name": "St-Michel Marcel Langer"},
                    {"id": "stop_point:B2_9", "name": "Palais de Justice"},
                    {"id": "stop_point:B2_10", "name": "Carmes"},
                    {"id": "stop_point:B2_11", "name": "François Verdier"},
                    {"id": "stop_point:B2_12", "name": "Jean Jaurès"},
                    {"id": "stop_point:B2_13", "name": "Jeanne d'Arc"},
                    {"id": "stop_point:B2_14", "name": "Compans-Caffarelli"},
                    {"id": "stop_point:B2_15", "name": "Canal du Midi"},
                    {"id": "stop_point:B2_16", "name": "Minimes-Claude Nougaro"},
                    {"id": "stop_point:B2_17", "name": "Barrière de Paris"},
                    {"id": "stop_point:B2_18", "name": "La Vache"},
                    {"id": "stop_point:B2_19", "name": "Trois Cocus"},
                    {"id": "stop_point:B2_20", "name": "Borderouge"},
                ],
            },
        },
    },
    # Tramway Lines
    "line:T1": {
        "id": "line:T1",
        "shortName": "T1",
        "name": "Tramway T1",
        "network": "Tisseo",
        "color": "#006DB8",
        "bgXmlColor": "#006DB8",
        "fgXmlColor": "#FFFFFF",
        "transportMode": TRANSPORT_MODES["tram"],
        "routes": {
            "route:T1:1": {
                "id": "route:T1:1",
                "name": "Arènes → Aéroconstellation",
                "direction": "Aéroconstellation",
                "stops": [
                    {"id": "stop_point:T1_1_1", "name": "Arènes"},
                    {"id": "stop_point:T1_1_2", "name": "Zénith"},
                    {"id": "stop_point:T1_1_3", "name": "Ancely"},
                    {"id": "stop_point:T1_1_4", "name": "Cartoucherie"},
                    {"id": "stop_point:T1_1_5", "name": "Purpan"},
                    {"id": "stop_point:T1_1_6", "name": "Aéroconstellation"},
                ],
            },
            "route:T1:2": {
                "id": "route:T1:2",
                "name": "Aéroconstellation → Arènes",
                "direction": "Arènes",
                "stops": [
                    {"id": "stop_point:T1_2_1", "name": "Aéroconstellation"},
                    {"id": "stop_point:T1_2_2", "name": "Purpan"},
                    {"id": "stop_point:T1_2_3", "name": "Cartoucherie"},
                    {"id": "stop_point:T1_2_4", "name": "Ancely"},
                    {"id": "stop_point:T1_2_5", "name": "Zénith"},
                    {"id": "stop_point:T1_2_6", "name": "Arènes"},
                ],
            },
        },
    },
    "line:T2": {
        "id": "line:T2",
        "shortName": "T2",
        "name": "Tramway T2",
        "network": "Tisseo",
        "color": "#FF6600",
        "bgXmlColor": "#FF6600",
        "fgXmlColor": "#FFFFFF",
        "transportMode": TRANSPORT_MODES["tram"],
        "routes": {
            "route:T2:1": {
                "id": "route:T2:1",
                "name": "Palais de Justice → Aéroport",
                "direction": "Aéroport",
                "stops": [
                    {"id": "stop_point:T2_1_1", "name": "Palais de Justice"},
                    {"id": "stop_point:T2_1_2", "name": "Compans-Caffarelli"},
                    {"id": "stop_point:T2_1_3", "name": "Ponts Jumeaux"},
                    {"id": "stop_point:T2_1_4", "name": "Aéroport"},
                ],
            },
            "route:T2:2": {
                "id": "route:T2:2",
                "name": "Aéroport → Palais de Justice",
                "direction": "Palais de Justice",
                "stops": [
                    {"id": "stop_point:T2_2_1", "name": "Aéroport"},
                    {"id": "stop_point:T2_2_2", "name": "Ponts Jumeaux"},
                    {"id": "stop_point:T2_2_3", "name": "Compans-Caffarelli"},
                    {"id": "stop_point:T2_2_4", "name": "Palais de Justice"},
                ],
            },
        },
    },
    # Linéo Lines
    "line:L1": {
        "id": "line:L1",
        "shortName": "L1",
        "name": "Linéo 1",
        "network": "Tisseo",
        "color": "#9B2242",
        "bgXmlColor": "#9B2242",
        "fgXmlColor": "#FFFFFF",
        "transportMode": TRANSPORT_MODES["lineo"],
        "routes": {
            "route:L1:1": {
                "id": "route:L1:1",
                "name": "Colomiers Gare SNCF → Balma-Gramont",
                "direction": "Balma-Gramont",
                "stops": [
                    {"id": "stop_point:L1_1_1", "name": "Colomiers Gare SNCF"},
                    {"id": "stop_point:L1_1_2", "name": "De Gaulle"},
                    {"id": "stop_point:L1_1_3", "name": "Arènes"},
                    {"id": "stop_point:L1_1_4", "name": "Compans-Caffarelli"},
                    {"id": "stop_point:L1_1_5", "name": "Jean Jaurès"},
                    {"id": "stop_point:L1_1_6", "name": "Marengo SNCF"},
                    {"id": "stop_point:L1_1_7", "name": "Balma-Gramont"},
                ],
            },
            "route:L1:2": {
                "id": "route:L1:2",
                "name": "Balma-Gramont → Colomiers Gare SNCF",
                "direction": "Colomiers Gare SNCF",
                "stops": [
                    {"id": "stop_point:L1_2_1", "name": "Balma-Gramont"},
                    {"id": "stop_point:L1_2_2", "name": "Marengo SNCF"},
                    {"id": "stop_point:L1_2_3", "name": "Jean Jaurès"},
                    {"id": "stop_point:L1_2_4", "name": "Compans-Caffarelli"},
                    {"id": "stop_point:L1_2_5", "name": "Arènes"},
                    {"id": "stop_point:L1_2_6", "name": "De Gaulle"},
                    {"id": "stop_point:L1_2_7", "name": "Colomiers Gare SNCF"},
                ],
            },
        },
    },
    # Bus Lines
    "line:14": {
        "id": "line:14",
        "shortName": "14",
        "name": "Bus 14",
        "network": "Tisseo",
        "color": "#00A650",
        "bgXmlColor": "#00A650",
        "fgXmlColor": "#FFFFFF",
        "transportMode": TRANSPORT_MODES["bus"],
        "routes": {
            "route:14:1": {
                "id": "route:14:1",
                "name": "Rangueil → Aéroport",
                "direction": "Aéroport",
                "stops": [
                    {"id": "stop_point:14_1_1", "name": "Rangueil"},
                    {"id": "stop_point:14_1_2", "name": "Université Paul Sabatier"},
                    {"id": "stop_point:14_1_3", "name": "Jean Jaurès"},
                    {"id": "stop_point:14_1_4", "name": "Jeanne d'Arc"},
                    {"id": "stop_point:14_1_5", "name": "Compans-Caffarelli"},
                    {"id": "stop_point:14_1_6", "name": "Aéroport"},
                ],
            },
            "route:14:2": {
                "id": "route:14:2",
                "name": "Aéroport → Rangueil",
                "direction": "Rangueil",
                "stops": [
                    {"id": "stop_point:14_2_1", "name": "Aéroport"},
                    {"id": "stop_point:14_2_2", "name": "Compans-Caffarelli"},
                    {"id": "stop_point:14_2_3", "name": "Jeanne d'Arc"},
                    {"id": "stop_point:14_2_4", "name": "Jean Jaurès"},
                    {"id": "stop_point:14_2_5", "name": "Université Paul Sabatier"},
                    {"id": "stop_point:14_2_6", "name": "Rangueil"},
                ],
            },
        },
    },
    "line:22": {
        "id": "line:22",
        "shortName": "22",
        "name": "Bus 22",
        "network": "Tisseo",
        "color": "#0072BC",
        "bgXmlColor": "#0072BC",
        "fgXmlColor": "#FFFFFF",
        "transportMode": TRANSPORT_MODES["bus"],
        "routes": {
            "route:22:1": {
                "id": "route:22:1",
                "name": "Argoulets → Colomiers",
                "direction": "Colomiers",
                "stops": [
                    {"id": "stop_point:22_1_1", "name": "Argoulets"},
                    {"id": "stop_point:22_1_2", "name": "Balma-Gramont"},
                    {"id": "stop_point:22_1_3", "name": "Jean Jaurès"},
                    {"id": "stop_point:22_1_4", "name": "Capitole"},
                    {"id": "stop_point:22_1_5", "name": "Compans-Caffarelli"},
                    {"id": "stop_point:22_1_6", "name": "Arènes"},
                    {"id": "stop_point:22_1_7", "name": "Colomiers"},
                ],
            },
            "route:22:2": {
                "id": "route:22:2",
                "name": "Colomiers → Argoulets",
                "direction": "Argoulets",
                "stops": [
                    {"id": "stop_point:22_2_1", "name": "Colomiers"},
                    {"id": "stop_point:22_2_2", "name": "Arènes"},
                    {"id": "stop_point:22_2_3", "name": "Compans-Caffarelli"},
                    {"id": "stop_point:22_2_4", "name": "Capitole"},
                    {"id": "stop_point:22_2_5", "name": "Jean Jaurès"},
                    {"id": "stop_point:22_2_6", "name": "Balma-Gramont"},
                    {"id": "stop_point:22_2_7", "name": "Argoulets"},
                ],
            },
        },
    },
    "line:81": {
        "id": "line:81",
        "shortName": "81",
        "name": "Bus 81",
        "network": "Tisseo",
        "color": "#8B4513",
        "bgXmlColor": "#8B4513",
        "fgXmlColor": "#FFFFFF",
        "transportMode": TRANSPORT_MODES["bus"],
        "routes": {
            "route:81:1": {
                "id": "route:81:1",
                "name": "Toulouse → Labège",
                "direction": "Labège",
                "stops": [
                    {"id": "stop_point:81_1_1", "name": "François Verdier"},
                    {"id": "stop_point:81_1_2", "name": "Carmes"},
                    {"id": "stop_point:81_1_3", "name": "Palais de Justice"},
                    {"id": "stop_point:81_1_4", "name": "Ramonville"},
                    {"id": "stop_point:81_1_5", "name": "Labège"},
                ],
            },
            "route:81:2": {
                "id": "route:81:2",
                "name": "Labège → Toulouse",
                "direction": "Toulouse",
                "stops": [
                    {"id": "stop_point:81_2_1", "name": "Labège"},
                    {"id": "stop_point:81_2_2", "name": "Ramonville"},
                    {"id": "stop_point:81_2_3", "name": "Palais de Justice"},
                    {"id": "stop_point:81_2_4", "name": "Carmes"},
                    {"id": "stop_point:81_2_5", "name": "François Verdier"},
                ],
            },
        },
    },
}

# Build flat structures for backward compatibility
MOCK_STOPS = {}
MOCK_LINES = {}

for line_id, line_data in MOCK_LINES_DATA.items():
    # Build MOCK_LINES (without routes for simple API responses)
    MOCK_LINES[line_id] = {
        k: v for k, v in line_data.items() if k != "routes"
    }

    # Build MOCK_STOPS from all routes (with coordinates)
    for route_id, route_data in line_data.get("routes", {}).items():
        for stop in route_data.get("stops", []):
            stop_id = stop["id"]
            stop_name = stop["name"]
            if stop_id not in MOCK_STOPS:
                # Get coordinates if available
                coords = STOP_COORDINATES.get(stop_name)
                stop_entry = {
                    "id": stop_id,
                    "name": stop_name,
                    "cityName": "Toulouse",
                    "cityId": "31555",
                }
                if coords:
                    stop_entry["latitude"] = coords[0]
                    stop_entry["longitude"] = coords[1]
                MOCK_STOPS[stop_id] = stop_entry


def get_transport_modes() -> list[dict]:
    """Get list of available transport modes."""
    return [
        {"id": "metro", "name": "Métro"},
        {"id": "tram", "name": "Tramway"},
        {"id": "lineo", "name": "Linéo"},
        {"id": "bus", "name": "Bus"},
    ]


def get_lines_by_mode(mode_id: str) -> list[dict]:
    """Get lines for a specific transport mode."""
    mode_name_map = {
        "metro": "Métro",
        "tram": "Tramway",
        "bus": "Bus",
        "lineo": "Linéo",
    }
    mode_name = mode_name_map.get(mode_id, "")

    lines = []
    for line_id, line_data in MOCK_LINES_DATA.items():
        if line_data["transportMode"]["name"] == mode_name:
            lines.append({
                "id": line_id,
                "shortName": line_data["shortName"],
                "name": line_data["name"],
                "color": line_data["color"],
            })

    # Sort by shortName
    lines.sort(key=lambda x: x["shortName"])
    return lines


def get_routes_for_line(line_id: str) -> list[dict]:
    """Get routes (directions) for a specific line."""
    line_data = MOCK_LINES_DATA.get(line_id, {})
    routes = []

    for route_id, route_data in line_data.get("routes", {}).items():
        routes.append({
            "id": route_id,
            "name": route_data["name"],
            "direction": route_data["direction"],
        })

    return routes


def get_stops_for_route(line_id: str, route_id: str) -> list[dict]:
    """Get stops for a specific line and route."""
    line_data = MOCK_LINES_DATA.get(line_id, {})
    route_data = line_data.get("routes", {}).get(route_id, {})

    stops = []
    direction = route_data.get("direction", "")

    for stop in route_data.get("stops", []):
        stops.append({
            "id": stop["id"],
            "name": stop["name"],
            "display_name": f"{stop['name']} (→ {direction})",
        })

    return stops


def generate_mock_departures(
    stop_id: str | None = None,
    line_id: str | None = None,
    route_id: str | None = None,
    num_departures: int = 10,
) -> dict:
    """Generate mock departure data filtered by line and route."""
    # Find stop info
    stop = MOCK_STOPS.get(stop_id) if stop_id else None
    if not stop:
        stop = random.choice(list(MOCK_STOPS.values())) if MOCK_STOPS else {
            "id": stop_id or "stop_point:unknown",
            "name": "Unknown Stop",
            "cityName": "Toulouse",
            "cityId": "31555",
        }

    # Get line and route info for filtered departures
    if line_id and line_id in MOCK_LINES_DATA:
        # Use only the specified line
        line_data = MOCK_LINES_DATA[line_id]
        line = MOCK_LINES[line_id]

        # Get the specific route direction, or pick one if not specified
        if route_id and route_id in line_data.get("routes", {}):
            route = line_data["routes"][route_id]
            destination_name = route["direction"]
        else:
            # Pick first route if not specified
            routes = list(line_data.get("routes", {}).values())
            route = routes[0] if routes else {"direction": "Unknown"}
            destination_name = route.get("direction", "Unknown")

        destination = {"name": destination_name, "cityName": "Toulouse"}

        # Generate departures for this specific line/direction
        now = datetime.now(TOULOUSE_TZ)
        departures = []

        for i in range(num_departures):
            # Realistic intervals: 3-8 minutes apart for metro/tram, 5-15 for bus
            if line["transportMode"]["name"] in ["Métro", "Tramway"]:
                interval = random.randint(3, 8)
            else:
                interval = random.randint(5, 15)

            minutes_ahead = (i * interval) + random.randint(1, 5)
            departure_time = now + timedelta(minutes=minutes_ahead)

            is_realtime = line["transportMode"]["name"] in ["Bus", "Tramway", "Linéo"]

            departures.append({
                "dateTime": departure_time.strftime("%Y-%m-%d %H:%M:%S"),
                "realTime": "yes" if is_realtime else "no",
                "waitingTime": f"{minutes_ahead} mn" if minutes_ahead < 60 else f"{minutes_ahead // 60}h{minutes_ahead % 60:02d}",
                "line": line,
                "destination": destination,
            })
    else:
        # No line filter: generate random departures from various lines (legacy behavior)
        now = datetime.now(TOULOUSE_TZ)
        departures = []
        available_lines = list(MOCK_LINES.keys())

        for i in range(num_departures):
            random_line_id = random.choice(available_lines)
            line = MOCK_LINES[random_line_id]
            line_data = MOCK_LINES_DATA.get(random_line_id, {})

            routes = list(line_data.get("routes", {}).values())
            route = random.choice(routes) if routes else {"direction": "Unknown"}
            destination = {"name": route.get("direction", "Unknown"), "cityName": "Toulouse"}

            minutes_ahead = random.randint(1, 60) + (i * 3)
            departure_time = now + timedelta(minutes=minutes_ahead)

            is_realtime = line["transportMode"]["name"] in ["Bus", "Tramway", "Linéo"]

            departures.append({
                "dateTime": departure_time.strftime("%Y-%m-%d %H:%M:%S"),
                "realTime": "yes" if is_realtime else "no",
                "waitingTime": f"{minutes_ahead} mn" if minutes_ahead < 60 else f"{minutes_ahead // 60}h{minutes_ahead % 60:02d}",
                "line": line,
                "destination": destination,
            })

    departures.sort(key=lambda x: x["dateTime"])

    return {
        "expirationDate": (now + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "departures": {
            "stopArea": stop,
            "departure": departures,
        },
    }


def generate_mock_lines_response(mode_id: str | None = None) -> dict:
    """Generate mock response for lines list."""
    if mode_id:
        lines_list = get_lines_by_mode(mode_id)
    else:
        lines_list = list(MOCK_LINES.values())

    return {
        "expirationDate": (datetime.now(TOULOUSE_TZ) + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"),
        "lines": {
            "line": lines_list,
        },
    }


def generate_mock_stop_points_response(
    line_id: str | None = None,
    route_id: str | None = None,
) -> dict:
    """Generate mock response for stop_points."""
    if line_id and route_id:
        stops = get_stops_for_route(line_id, route_id)
    else:
        stops = [
            {"id": s["id"], "name": s["name"], "display_name": s["name"]}
            for s in MOCK_STOPS.values()
        ]

    return {
        "expirationDate": (datetime.now(TOULOUSE_TZ) + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"),
        "physicalStops": {
            "physicalStop": stops,
        },
    }


# Mock service alerts/messages
MOCK_MESSAGES = [
    {
        "id": "msg_001",
        "title": "Travaux station Mermoz",
        "content": "En raison de travaux, les ascenseurs de la station Mermoz sont hors service jusqu'au 15 mars. Veuillez emprunter les escaliers ou les escalators.",
        "type": "travaux",
        "importance": "medium",
        "lines": ["line:A"],
        "start_offset_days": -5,  # Started 5 days ago
        "end_offset_days": 30,    # Ends in 30 days
    },
    {
        "id": "msg_002",
        "title": "Perturbation Ligne B",
        "content": "Suite à un incident technique, le trafic est interrompu entre Jean Jaurès et Ramonville. Des bus relais sont mis en place.",
        "type": "perturbation",
        "importance": "high",
        "lines": ["line:B"],
        "start_offset_days": 0,   # Today
        "end_offset_days": 0,     # Today
    },
    {
        "id": "msg_003",
        "title": "Nouveau service de nuit",
        "content": "À partir du 1er février, le service de nuit est étendu les vendredis et samedis jusqu'à 2h du matin sur les lignes A et B.",
        "type": "info",
        "importance": "low",
        "lines": ["line:A", "line:B"],
        "start_offset_days": -30,
        "end_offset_days": 60,
    },
    {
        "id": "msg_004",
        "title": "Travaux Tramway T1",
        "content": "Travaux de modernisation des voies entre Arènes et Zénith du 10 au 20 février. Temps de parcours allongé de 5 minutes.",
        "type": "travaux",
        "importance": "medium",
        "lines": ["line:T1"],
        "start_offset_days": -2,
        "end_offset_days": 8,
    },
    {
        "id": "msg_005",
        "title": "Grève nationale",
        "content": "Mouvement social national le 15 février. Trafic perturbé sur l'ensemble du réseau. Consultez l'application Tisseo pour connaître les horaires.",
        "type": "perturbation",
        "importance": "high",
        "lines": ["line:A", "line:B", "line:T1", "line:T2", "line:L1", "line:14", "line:22", "line:81"],
        "start_offset_days": 5,
        "end_offset_days": 5,
    },
]


def generate_mock_messages_response(line_id: str | None = None) -> dict:
    """Generate mock response for messages/alerts."""
    now = datetime.now(TOULOUSE_TZ)
    messages = []

    for msg in MOCK_MESSAGES:
        # Check if this message applies to the requested line
        if line_id and line_id not in msg["lines"]:
            continue

        # Calculate start and end dates from offsets
        start_date = now + timedelta(days=msg["start_offset_days"])
        end_date = now + timedelta(days=msg["end_offset_days"])

        # Set time to start/end of day
        start_date = start_date.replace(hour=5, minute=0, second=0)
        end_date = end_date.replace(hour=23, minute=59, second=59)

        # Only include active messages
        if now < start_date or now > end_date:
            continue

        # Build lines list
        lines_list = [{"id": lid, "shortName": lid.split(":")[-1]} for lid in msg["lines"]]

        messages.append({
            "id": msg["id"],
            "title": msg["title"],
            "content": msg["content"],
            "type": msg["type"],
            "importance": msg["importance"],
            "startDate": start_date.strftime("%Y-%m-%d %H:%M:%S"),
            "endDate": end_date.strftime("%Y-%m-%d %H:%M:%S"),
            "lines": {
                "line": lines_list,
            },
        })

    return {
        "expirationDate": (now + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S"),
        "messages": {
            "message": messages,
        },
    }
