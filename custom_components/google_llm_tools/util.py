"""Utility functions for Google Maps Tools integration."""

from homeassistant.core import HomeAssistant


def get_location_bias(hass: HomeAssistant) -> str | None:
    """
    Return a small bounding box around zone.home for geocode bias.

    Google Geocoding API supports a 'bounds' parameter formatted as
    southwest_lat,southwest_lng|northeast_lat,northeast_lng which *biases* (not
    restricts) results toward that box. We create a ~0.02 degree box (~2 km)
    around the home location. If home location not available, return None.
    """
    # zone.home entity stores coordinates; fallback to config latitude/longitude.
    latitude = getattr(hass.config, "latitude", None)
    longitude = getattr(hass.config, "longitude", None)
    if latitude is None or longitude is None:
        return None
    delta = 0.01  # ~1.1 km latitude; acceptable small bias
    south = latitude - delta
    north = latitude + delta
    west = longitude - delta
    east = longitude + delta
    return f"{south},{west}|{north},{east}"
