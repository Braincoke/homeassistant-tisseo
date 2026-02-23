"""Shared helper functions for the Tisseo integration."""
from __future__ import annotations

import unicodedata

from .const import DOMAIN

# Transport mode to icon mapping
TRANSPORT_MODE_ICONS: dict[str, str] = {
    "Métro": "mdi:subway-variant",
    "Metro": "mdi:subway-variant",
    "Tramway": "mdi:tram",
    "Tram": "mdi:tram",
    "Bus": "mdi:bus",
    "Linéo": "mdi:bus-articulated-front",
    "Lineo": "mdi:bus-articulated-front",
}

DEFAULT_ICON = "mdi:bus"

# Transport mode to device model mapping
TRANSPORT_MODE_MODELS: dict[str, str] = {
    "Métro": "Metro Station",
    "Metro": "Metro Station",
    "Tramway": "Tram Stop",
    "Tram": "Tram Stop",
    "Linéo": "Linéo Stop",
    "Lineo": "Linéo Stop",
    "Bus": "Bus Stop",
}

DEFAULT_DEVICE_MODEL = "Bus Stop"


def get_transport_icon(transport_mode: str | None) -> str:
    """Get the appropriate icon for a transport mode."""
    if transport_mode:
        return TRANSPORT_MODE_ICONS.get(transport_mode, DEFAULT_ICON)
    return DEFAULT_ICON


def get_device_model(transport_mode: str | None) -> str:
    """Get the appropriate device model name for a transport mode."""
    if transport_mode:
        return TRANSPORT_MODE_MODELS.get(transport_mode, DEFAULT_DEVICE_MODEL)
    return DEFAULT_DEVICE_MODEL


def sanitize(text: str) -> str:
    """Sanitize text for entity ID.

    Removes accents, lowercases, replaces special chars with underscores,
    and removes consecutive underscores.
    """
    # Remove accents
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Lowercase and replace special chars
    text = text.lower()
    text = text.replace(":", "_").replace("-", "_").replace(" ", "_")
    # Remove consecutive underscores and strip
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def make_unique_key(
    transport_mode: str, line_name: str, stop_name: str, direction: str
) -> str:
    """Create a unique key from transport mode, line, stop name and direction.

    Example: tisseo_metro_a_mermoz_balma_gramont
    """
    parts = [DOMAIN, transport_mode, line_name, stop_name, direction]
    sanitized_parts = [sanitize(p) for p in parts if p]
    return "_".join(sanitized_parts)
