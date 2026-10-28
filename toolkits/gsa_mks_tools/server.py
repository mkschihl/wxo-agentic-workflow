"""GSA MKS MCP Toolkit — stdio transport.

Three tools exposed to watsonx Orchestrate:
  - gsa_mks_get_current_weather  : live weather for a city via wttr.in
  - gsa_mks_get_programming_joke : random programming joke via Official Joke API
  - gsa_mks_convert_units        : unit conversion (temperature, distance, mass, volume)

Orchestrate starts this file as a subprocess and communicates over stdin/stdout.
"""

from __future__ import annotations

import httpx
from fastmcp import FastMCP
from typing import Annotated
from urllib.parse import quote

mcp = FastMCP(
    "gsa_mks_mcp",
    instructions=(
        "GSA MKS toolkit with three utility tools.\n\n"
        "TOOL SELECTION GUIDE:\n"
        "- Current weather for a city → gsa_mks_get_current_weather\n"
        "- A random programming joke → gsa_mks_get_programming_joke\n"
        "- Convert between units (temperature, distance, mass, volume) "
        "→ gsa_mks_convert_units\n\n"
        "No authentication required. All tools return dicts; errors include "
        "an 'error' key and a 'hint' key with recovery guidance."
    ),
)

# ---------------------------------------------------------------------------
# Tool 1 — Current weather
# ---------------------------------------------------------------------------

@mcp.tool(
    name="gsa_mks_get_current_weather",
    annotations={
        "title": "Get Current Weather",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def gsa_mks_get_current_weather(
    city: Annotated[str, "City name to fetch weather for, e.g. 'London' or 'New York'. Must be non-empty."],
) -> dict:
    """Return live current weather conditions for a city using wttr.in.

    Data is real-time (wttr.in updates every ~30 minutes). Returns temperature
    in both Celsius and Fahrenheit, a plain-English condition description,
    humidity percentage, and wind speed in km/h.

    Returns a dict with keys: city, condition, temp_c, temp_f, humidity_pct,
    wind_kph. On failure returns {"error": "...", "hint": "..."}.
    """
    safe_city = quote(city.strip(), safe="")
    if not safe_city:
        return {"error": "city must not be empty.", "hint": "Provide a city name such as 'London'."}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            response = await client.get(f"https://wttr.in/{safe_city}?format=j1")
            response.raise_for_status()
            data = response.json()
        cond = data["current_condition"][0]
        return {
            "city": city.strip(),
            "condition": cond["weatherDesc"][0]["value"],
            "temp_c": int(cond["temp_C"]),
            "temp_f": int(cond["temp_F"]),
            "humidity_pct": int(cond["humidity"]),
            "wind_kph": int(cond["windspeedKmph"]),
        }
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return {"error": str(exc), "hint": "Check the city name spelling and try again."}


# ---------------------------------------------------------------------------
# Tool 2 — Programming joke
# ---------------------------------------------------------------------------

@mcp.tool(
    name="gsa_mks_get_programming_joke",
    annotations={
        "title": "Get Programming Joke",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def gsa_mks_get_programming_joke() -> dict:
    """Fetch a random programming joke from the Official Joke API.

    Calls https://official-joke-api.appspot.com (free, no authentication).
    Returns a dict with keys: setup (the question/premise), punchline (the
    answer), and joke_type (always "programming").
    On failure returns {"error": "...", "hint": "..."}.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.get(
                "https://official-joke-api.appspot.com/jokes/programming/random"
            )
            response.raise_for_status()
            data = response.json()[0]
        return {
            "setup": data["setup"],
            "punchline": data["punchline"],
            "joke_type": data["type"],
        }
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return {"error": str(exc), "hint": "The joke API may be temporarily unavailable; try again shortly."}


# ---------------------------------------------------------------------------
# Tool 3 — Unit converter
# ---------------------------------------------------------------------------

_CONVERSIONS: dict[tuple[str, str], object] = {
    ("celsius", "fahrenheit"): lambda v: v * 9 / 5 + 32,
    ("fahrenheit", "celsius"): lambda v: (v - 32) * 5 / 9,
    ("celsius", "kelvin"):     lambda v: v + 273.15,
    ("kelvin", "celsius"):     lambda v: v - 273.15,
    ("fahrenheit", "kelvin"):  lambda v: (v - 32) * 5 / 9 + 273.15,
    ("kelvin", "fahrenheit"):  lambda v: (v - 273.15) * 9 / 5 + 32,
    ("km", "miles"):           lambda v: v * 0.621371,
    ("miles", "km"):           lambda v: v / 0.621371,
    ("kg", "pounds"):          lambda v: v * 2.20462,
    ("pounds", "kg"):          lambda v: v / 2.20462,
    ("liters", "gallons"):     lambda v: v * 0.264172,
    ("gallons", "liters"):     lambda v: v / 0.264172,
}

_SUPPORTED_UNITS = "celsius, fahrenheit, kelvin, km, miles, kg, pounds, liters, gallons"


@mcp.tool(
    name="gsa_mks_convert_units",
    annotations={
        "title": "Convert Units",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gsa_mks_convert_units(
    value: Annotated[float, "The numeric value to convert."],
    from_unit: Annotated[str, "Unit to convert from. One of: celsius, fahrenheit, kelvin, km, miles, kg, pounds, liters, gallons."],
    to_unit: Annotated[str, "Unit to convert to. Must be in the same family as from_unit (temperature, distance, mass, or volume)."],
) -> dict:
    """Convert a numeric value between units using local arithmetic — no network call.

    Supported unit families:
      - Temperature: celsius, fahrenheit, kelvin
      - Distance:    km, miles
      - Mass:        kg, pounds
      - Volume:      liters, gallons

    Returns a dict with keys: original_value, from_unit, converted_value, to_unit.
    On an unsupported pair returns {"error": "...", "hint": "Supported units: ..."}.
    """
    f = from_unit.lower().strip()
    t = to_unit.lower().strip()
    fn = _CONVERSIONS.get((f, t))
    if fn is None:
        return {
            "error": f"Unsupported conversion: '{from_unit}' → '{to_unit}'.",
            "hint": f"Supported units: {_SUPPORTED_UNITS}. Units must be in the same family.",
        }
    return {
        "original_value": value,
        "from_unit": from_unit.strip(),
        "converted_value": round(fn(value), 6),
        "to_unit": to_unit.strip(),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
