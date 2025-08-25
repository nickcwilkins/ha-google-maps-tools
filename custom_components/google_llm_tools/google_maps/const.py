"""Constants for google maps LLM API."""

# API endpoints
GEOCODE_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"

# New Routes API endpoint (v2)
ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Places API (New) endpoints
PLACES_TEXT_SEARCH_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
PLACES_NEARBY_SEARCH_ENDPOINT = "https://places.googleapis.com/v1/places:searchNearby"
PLACES_DETAILS_ENDPOINT = (
    "https://places.googleapis.com/v1/places/{}"  # format with place id
)

TOOL_GEOCODE = "gmaps_geocode"
TOOL_REVERSE_GEOCODE = "gmaps_reverse_geocode"
TOOL_DIRECTIONS = "gmaps_directions"

# Places tool names
TOOL_PLACES_SEARCH_TEXT = "gmaps_places_search_text"
TOOL_PLACES_SEARCH_NEARBY = "gmaps_places_search_nearby"
TOOL_PLACE_DETAILS = "gmaps_place_details"

DIRECTIONS_DEPARTURE_TIME_DESC = (
    "The time to depart. Accepts date time strings like '5:00pm', "
    "'3:30pm', or full date times like '2:30pm Monday, March 29th, 2025'. "
    "Mutually exclusive with arrival_time"
)

DIRECTIONS_ARRIVAL_TIME_DESC = (
    "The desired arrival time. Accepts date time strings like '5:00pm', "
    "'3:30pm tomorrow', or full date times like '2:30pm Monday, March 29th, 2025'. "
    "Mutually exclusive with departure_time"
)

# Fixed non-overridable field masks for Places tools (keep minimal / cost aware)
PLACES_FIELD_MASK_SEARCH_TEXT = (
    "places.id,places.displayName,places.formattedAddress,places.primaryType,"
    "places.rating,places.priceLevel,places.currentOpeningHours.openNow"
)
PLACES_FIELD_MASK_SEARCH_NEARBY = (
    "places.id,places.displayName,places.formattedAddress,places.primaryType,"
    "places.types,places.rating,places.priceLevel,places.currentOpeningHours.openNow"
)
PLACES_FIELD_MASK_DETAILS = (
    "id,displayName,formattedAddress,primaryType,currentOpeningHours.openNow,"
    "currentOpeningHours.weekdayDescriptions,rating,priceLevel,nationalPhoneNumber,"
    "internationalPhoneNumber,websiteUri,userRatingCount"
)

# Price level mapping normalization (enum string -> numeric level)
PRICE_LEVEL_MAP = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

# Allowed request price level enum subset (exclude FREE per initial plan)
REQUEST_PRICE_LEVEL_ENUMS = [
    "PRICE_LEVEL_INEXPENSIVE",
    "PRICE_LEVEL_MODERATE",
    "PRICE_LEVEL_EXPENSIVE",
    "PRICE_LEVEL_VERY_EXPENSIVE",
]
