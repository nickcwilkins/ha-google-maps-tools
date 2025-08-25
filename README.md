# Google Maps Tools (Home Assistant LLM API)

Expose Google Maps Platform capabilities (geocoding, reverse geocoding, turn‑by‑turn directions) to Home Assistant Large Language Model (LLM) / Assist style agents via a custom LLM API. Backed by the official `googlemaps` Python SDK (run in a background executor) it lets an AI assistant inside Home Assistant call structured tools to:

* Convert an address (or component filters) to coordinates
* Convert coordinates to the best matching human readable address
* Get route summaries (distance, duration) between two locations

## Features

* Three LLM tools registered under API id `google_maps`:
	* `gmaps_geocode`
	* `gmaps_reverse_geocode`
	* `gmaps_directions`
* Sensible defaults for language, region, travel mode.
* Minimal prompt instructing the model how to use the tools.
* Simplified structured responses (status + concise summary) while retaining core route metrics.
* Uses official `googlemaps` SDK (no custom raw HTTP implementation) for reliability & maintenance.

## Installation

1. Copy `custom_components/google_maps_tools` into your Home Assistant `custom_components` directory (or install via HACS as a custom repository if publishing).
2. Restart Home Assistant.
3. In Settings → Devices & Services → Add Integration, search for "Google Maps Tools".
4. Enter a valid Google Maps Platform API key with Geocoding and Directions APIs enabled, optionally adjust defaults.

## Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| API Key | Google Maps Platform key (required) | — |
| Default Language | Response language passed to APIs | `en` |
| Default Region | Region code bias (e.g. `us`, leave blank for none) | none |
| Default Travel Mode | Directions mode (`driving`, `walking`, `bicycling`, `transit`) | `driving` |

You can override most defaults per tool call by passing parameters in the tool invocation.

## LLM Tool Schemas

### gmaps_geocode
Arguments: `address` (string, optional), `components` (string, optional), `language`, `region`.
At least one of `address` or `components` should be supplied.

### gmaps_reverse_geocode
Arguments: `lat` (float, required), `lng` (float, required), optional `language`, `result_type`, `location_type`.

### gmaps_directions
Arguments: `origin` (string), `destination` (string), optional: `mode`, `language`, `region`, `alternatives` (bool), `units` (`metric`/`imperial`), `departure_time` (unix), `arrival_time` (unix), `avoid` (string).

## Example (Pseudo) LLM Usage

The assistant may decide:
1. Call `gmaps_geocode` with an address → get coordinates.
2. Call `gmaps_directions` with textual addresses directly (API supports this) → summarize distance & ETA to user.

Returned direction route objects (list) each include:
* `summary`: Short textual summary of major roads (if provided by API)
* `legs`: List of legs with `distance`, `duration`, `start_address`, `end_address`
* `distance_meters`: Total aggregated distance across legs
* `duration_seconds`: Total aggregated duration across legs

The raw verbose Google Directions response is intentionally collapsed to keep payloads small for LLM summarization. (Previous versions used the Routes API with field masks; migration retained a similar concise shape.)

## Privacy / Quotas

All requests go through the official `googlemaps` client (which uses Google’s Web Service endpoints) from your Home Assistant instance. Ensure your API key is restricted (HTTP referrer / IP) per Google’s best practices. Usage counts against your Google Maps Platform billing account quotas.

## Troubleshooting

* `ZERO_RESULTS` is not an error—means no match.
* Other statuses raise integration errors logged in Home Assistant logs.
* Verify APIs (Geocoding API, Directions API) are enabled in Google Cloud Console.

## License

This project is released under the MIT License (see `LICENSE`).

## Disclaimer

Not an official Google product. Use at your own risk; observe Maps Platform Terms of Service.
