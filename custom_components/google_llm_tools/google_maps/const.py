# API endpoints
GEOCODE_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"

# New Routes API endpoint (v2)
ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"

TOOL_GEOCODE = "gmaps_geocode"
TOOL_REVERSE_GEOCODE = "gmaps_reverse_geocode"
TOOL_DIRECTIONS = "gmaps_directions"

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
