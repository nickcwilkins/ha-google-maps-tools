---
description: A high-level overview of this integration's architecture
---

## Architecture: Google Maps Tools Home Assistant LLM API

This repository provides a custom Home Assistant integration that exposes external location / mapping capabilities (currently Google Maps Platform) to Assist / LLM style agents through Home Assistant's `llm` helper framework. The design favors: (1) low coupling between each external provider, (2) a consistent pattern for registering structured tools, and (3) clear separation of configuration, runtime state, and API-specific code. While only a single provider (Google Maps) is implemented today, the layout intentionally anticipates multiple future LLM APIs (e.g. weather, transit, other mapping backends, specialized knowledge sources).

---

### High‑Level Flow
1. User installs integration and supplies an API key via a config flow.
2. On setup (`async_setup_entry`), the integration creates an API client and registers one or more LLM APIs (currently one: Google Maps) using `homeassistant.helpers.llm.async_register_api`.
3. When Assist / an LLM session starts, HA requests an `APIInstance` from the registered LLM API. This instance exposes a list of `Tool` objects with JSON schemas (Voluptuous) describing arguments.
4. The LLM chooses tools and passes structured arguments back to Home Assistant, which calls the tool `async_call` coroutine.
5. Each tool retrieves the active config entry via its stored `entry_id`, applies defaults from `entry.options`, calls the underlying external web service through the API client, post‑processes results (simplification / localization), and returns a concise JSON payload suitable for summarization.
6. On reload / unload, the unregister callback automatically removes the LLM API.

---

### Directory Structure & File Responsibilities

```
custom_components/google_llm_tools/
  __init__.py           # Integration entrypoint: create API client, register LLM API(s)
  manifest.json         # Home Assistant integration metadata (domain, name, version)
  const.py              # Integration‑wide constants (domain, option keys, defaults, timeouts)
  config_flow.py        # Config + options flow (API key in config entry, behavioral defaults in options)
  util.py               # Cross‑provider utility helpers (e.g., location bias box)
  translations/         # Translation strings (en.json, future locales)
  google_maps/          # Provider subpackage for Google Maps
	 __init__.py         # GoogleMapsLLMAPI + tool classes (schemas, tool logic)
	 api.py              # Low‑level HTTP client & response shaping for Google web services
	 const.py            # Provider specific constants (tool names, endpoint URLs, doc strings)
docs/
  architecture.md       # (this document)
```

Future providers should follow a similar subpackage pattern (`<provider_name>/`) with an `__init__.py`, `api.py`, and `const.py` at minimum.

> NOTE: Ensure the `manifest.json` `domain` matches the integration folder name (`google_llm_tools`). If they diverge, Home Assistant will treat them as different domains. Align them when adding new functionality.

---

### Configuration, Options, Runtime Data
| Storage Location | Intended Contents | Mutability | Rationale |
|------------------|-------------------|------------|-----------|
| `ConfigEntry.data` | Required secrets / credentials (e.g., API key) | Set during config flow, updated during reconfigure | Stable identity & authentication |
| `ConfigEntry.options` | User‑tunable behavioral defaults (language, travel mode) | Options flow | Adjust without re‑entering secrets |
| `ConfigEntry.runtime_data` | In‑memory non‑persistent objects (API client instances) | Set on setup, internal use | Avoid global state; proper cleanup on unload |

The tools read defaults from `entry.options` first, then fallback to historical or constant defaults.

---

### LLM API & Tool Design
* `GoogleMapsLLMAPI` subclasses `llm.API` and implements `async_get_api_instance` to build a runtime `APIInstance` containing:
  * A short guiding prompt for the model.
  * A list of tool objects implementing domain actions.
* Each tool subclasses a lightweight base (`GoogleMapsTool`) holding the Voluptuous schema and the `entry_id` reference.
* Tool `async_call` pattern:
  1. Fetch config entry by stored `entry_id` (cheap O(1) lookup).
  2. Merge per‑call arguments with option defaults.
  3. Invoke API client (`geocode`, `reverse_geocode`, `directions`, etc.).
  4. Simplify & sanitize payload (remove bulky or unnecessary fields, localize values, collapse structures).
  5. Return structured dict (never raw HTTP response).
* Schemas use Voluptuous with explicit field help (descriptions for time parsing, etc.).

Error handling: Currently minimal; raise / bubble exceptions to HA logs. A future enhancement could standardize helper exceptions or embed status codes in tool output for the LLM to reason about retries.

---

### API Client Layer (`google_maps/api.py`)
Responsibilities:
* Build HTTP requests (parameters or JSON body) for Google endpoints.
* Map legacy style options to new Routes API (`computeRoutes`).
* Apply post‑processing transforms (field mask, localization, polyline stripping, structural collapsing) to reduce payload surface.
* Provide helper dataclasses (`DirectionsOptions`) to keep tool function signatures compact.

Separation Rationale:
* Keeps tool code declarative (arg extraction + call) and provider logic isolated.
* Facilitates future reuse if multiple tools share internal transformations.

---

### Utility Layer (`util.py`)
Holds integration‑agnostic helpers (e.g. generating a small geographic bias bounding box around the Home Assistant home location). Keep this file lean; provider‑specific logic belongs inside its provider subpackage.

---

### Adding a New LLM API Provider
Follow this checklist when introducing another external capability (e.g. `openstreetmap`, `weather_service`, etc.):

1. Create subpackage: `custom_components/google_llm_tools/<provider>/`.
	* `__init__.py`: Define `<ProviderName>LLMAPI` subclass of `llm.API` and provider tool classes.
	* `api.py`: Implement low‑level HTTP client (session injection, request methods, transformation helpers). Accept an `aiohttp.ClientSession` from core integration entrypoint for connection reuse.
	* `const.py`: Provider‑specific constants (endpoint URLs, tool names, descriptive strings).
2. Define tool classes mirroring the Google pattern:
	* Base tool (optional) capturing common provider context.
	* One class per action. Provide concise `description` tuned for LLM planning.
3. Schemas:
	* Use Voluptuous; keep arguments minimal & composable.
	* Prefer explicit enumerations (`vol.In([...])`) for constrained fields (modes, units, etc.).
	* Input surface minimization principle: aggressively limit the number of required / branching parameters so smaller LLMs reliably fill them. Favor a few high‑leverage arguments with strong defaults over many toggles. Provide sensible defaults via options (and server‑side fallbacks) so most calls only need 1–2 fields. When possible accept a single natural language field (e.g. `query`, `origin_text`) that the tool interprets internally instead of exposing many discrete knobs. Keep types simple (string, number, enum, boolean) and avoid deeply nested objects or arrays unless essential. This reduces validation friction, improves tool selection accuracy, and mitigates model omission / hallucination of parameter names.
4. Register the new LLM API in the integration entrypoint (`__init__.py`):
	* Instantiate its API object alongside Google Maps.
	* Capture the unregister callback with `entry.async_on_unload`.
	* You may re‑use the same credential if appropriate or extend the config/option flows to capture provider‑specific settings (see step 7).
5. Runtime data:
	* Extend the `GoogleMapsRuntimeData` dataclass (rename to a generic `IntegrationRuntimeData` if multiple clients) to hold additional clients.
6. Constants:
	* Add new `LLM_API_ID` style constant(s) in `const.py`, or move to provider constants if uniqueness is clear.
7. Config / Options Flow:
	* If the new provider needs separate credentials, update `config_flow.py`:
	  - Store only required secrets in `ConfigEntry.data`.
	  - Use options for defaults (language, region, units, etc.).
	  - Consider adding a reconfigure step for new credentials or using a multi‑step flow.
8. Translations:
	* Add tool names / descriptions to translation JSON once you localize; current implementation relies on code strings.
9. Testing (recommended):
	* Mock HTTP responses for each tool path.
	* Validate schemas reject invalid input.
	* Snapshot the simplified tool outputs.
10. Documentation:
	* Update this architecture doc & README to list the new API and tools.

Minimal Registration Example Sketch (inside `async_setup_entry`):
```python
unregister_provider = llm.async_register_api(
	 hass,
	 ProviderLLMAPI(
		  hass=hass,
		  api_id="provider_id",
		  name="Provider Friendly Name",
		  entry_id=entry.entry_id,
		  client=provider_client,
	 ),
)
entry.async_on_unload(unregister_provider)
```

---

### Design Principles
* Single responsibility per layer (config vs runtime vs API glue).
* Voluptuous schemas = explicit & self‑documenting contract for LLM planning.
* Keep tool responses small & semantically rich for summarization (avoid raw bulk data like polylines or entire step lists unless essential).
* Provider isolation: All external service specifics remain in its subpackage.
* Stateless tools: No internal caching; rely on upstream APIs & HA session management.

---

### Extensibility Considerations
| Concern | Current Approach | Future Option |
|---------|------------------|---------------|
| Multiple providers | Manual registration of each API | Dynamic discovery & registry table |
| Credentials | Single API key (Google) | Per‑provider secret storage & reauth flows |
| Rate limiting | Delegate to provider quotas | Add internal throttling / backoff wrappers |
| Error semantics | Raw exceptions surfaced | Standardized error envelope (`{"error": {code, message}}`) |
| Localization | Language option passed through | Automatic fallback detection & per‑tool override |

---

### Making Code Changes Safely
1. Prefer small, incremental commits focusing on one layer (e.g., tool schema tweak or API client enhancement).
2. Preserve existing public identifiers (tool names, API id) to avoid breaking references in prompts or automations.
3. Update docstrings & this file when behavior or structure changes.
4. Add / adjust translation strings before publishing—tool descriptions feed into LLM planning.
5. Run linting & type checks (`ruff`, `mypy`) if you add optional static typing (can be extended to strict mode later).

---

### Known Improvement Areas
* Align `manifest.json` domain with folder (`google_llm_tools`) if mismatched.
* Fill in unimplemented sections in `google_maps/api.py` for full functionality (some helper functions are currently stubs in the excerpt).
* Add tests: tool schemas, direction time parsing, localization transforms.
* Add diagnostics (optional) for tracing quota usage or error rates.

---

### Summary
The integration layers Google Maps (and future providers) behind a consistent LLM API abstraction, giving Assist agents structured, predictable tools. Adding a new provider is primarily additive: create a subpackage, mirror the API & tool patterns, register it in the entry setup, and extend configuration if needed. Keep transformations close to the API client, keep tool schemas minimal, and maintain clear separation of configuration vs runtime state.
