# Plan: Three GSA MKS Tools as a Local stdio MCP Toolkit

## Top-Level Overview

Build a self-contained Python MCP toolkit that Orchestrate starts as a local subprocess and
communicates with over **stdin/stdout (stdio)**. The toolkit lives entirely in:

```
toolkits/
└── gsa_mks_tools/
    ├── server.py        ← FastMCP server: all three tools defined here
    └── requirements.txt ← third-party deps Orchestrate installs at runtime
```

`server.py` is a **single flat file** — no sub-packages, no `src/` layout, no separate tool
files. This matches the lab's expected package shape exactly and is what Orchestrate needs for
a local MCP toolkit: upload `package_root`, install `requirements.txt`, run `python server.py`
over stdio.

**Three tools, all prefixed `gsa_mks_`:**

| Tool name | Purpose | External call |
|---|---|---|
| `gsa_mks_get_current_weather` | Live weather via `wttr.in` | Yes — proves outbound internet access |
| `gsa_mks_get_programming_joke` | Random joke via Official Joke API | Yes — public REST API |
| `gsa_mks_convert_units` | Unit conversion | None — pure local logic |

**Framework:** FastMCP (`fastmcp>=2.0.0`), async tools, `httpx.AsyncClient` for HTTP.
**Transport:** stdio only (Orchestrate local toolkit pattern).
**Non-goals:** No HTTP server mode, no agent YAML, no Code Engine deploy, no separate tool files.

---

## Architecture

```
toolkits/gsa_mks_tools/
│
├── server.py
│     FastMCP("gsa_mks_mcp")
│     @mcp.tool("gsa_mks_get_current_weather")   → GET wttr.in
│     @mcp.tool("gsa_mks_get_programming_joke")  → GET official-joke-api.appspot.com
│     @mcp.tool("gsa_mks_convert_units")         → local math
│     if __name__ == "__main__": mcp.run("stdio")
│
└── requirements.txt
      fastmcp>=2.0.0
      httpx>=0.27.0
      pydantic>=2.0.0
```

Orchestrate registers this via `orchestrate toolkits import -f toolkit.yaml` where
`toolkit.yaml` points `package_root` at `toolkits/gsa_mks_tools/`.

---

## Sub-Task 1 — Scaffold the Toolkit Directory

### Intent
Create the `toolkits/gsa_mks_tools/` directory with a skeleton `server.py` (FastMCP
initialised, no tools yet) and a `requirements.txt`. This establishes the structure
that all subsequent sub-tasks build on.

### Expected Outcomes
- `toolkits/gsa_mks_tools/server.py` exists with FastMCP initialised and `mcp.run("stdio")` in `__main__`
- `toolkits/gsa_mks_tools/requirements.txt` contains `fastmcp>=2.0.0`, `httpx>=0.27.0`, `pydantic>=2.0.0`
- Running `python toolkits/gsa_mks_tools/server.py` from the workspace root blocks on stdin without error (Ctrl-C to exit)

### Todo List
- [ ] Create directory `toolkits/gsa_mks_tools/`
- [ ] Create `toolkits/gsa_mks_tools/requirements.txt` with the three runtime deps
- [ ] Create `toolkits/gsa_mks_tools/server.py` with: `from fastmcp import FastMCP`, `mcp = FastMCP("gsa_mks_mcp", instructions="...")`, and `if __name__ == "__main__": mcp.run(transport="stdio")`
- [ ] Write a meaningful `instructions=` string that names the server, lists the three tools, and explains when to use each
- [ ] Verify the skeleton runs without error: `cd toolkits/gsa_mks_tools && pip install -r requirements.txt --quiet && python server.py` (blocks on stdin = success)

### Relevant Context
- FastMCP initialization pattern from [`python_mcp_server.md`](mcp-hackathon-template/.agents/skills/mcp-builder/references/python_mcp_server.md) lines 20–24
- Server name convention: `{service}_mcp` → `gsa_mks_mcp`
- The venv at `/home/itzuser/wxo-agentic-workflow/venv` has Python 3.12; `fastmcp` and `httpx` are NOT pre-installed there, so install from the toolkit's own `requirements.txt`

### Status
`[ ] pending`

---

## Sub-Task 2 — Implement `gsa_mks_get_current_weather`

### Intent
Add the weather tool to `server.py`. This tool calls `wttr.in`'s free JSON API to
fetch live current conditions for a city — the proof that the toolkit can reach the
public internet when running inside Orchestrate.

### Expected Outcomes
- `server.py` contains `@mcp.tool(name="gsa_mks_get_current_weather", ...)` on an async function
- Calling it with `city="London"` returns a dict with keys: `city`, `condition`, `temp_c`, `temp_f`, `humidity_pct`, `wind_kph`
- A bad city name or network failure returns `{"error": "...", "hint": "..."}` — never raises to the client

### Todo List
- [ ] Add `import httpx` and `from urllib.parse import quote` at the top of `server.py`
- [ ] Add the `@mcp.tool` decorator block with `name="gsa_mks_get_current_weather"` and annotations: `readOnlyHint: True`, `destructiveHint: False`, `idempotentHint: False`, `openWorldHint: True`
- [ ] Define `async def gsa_mks_get_current_weather(city: Annotated[str, "City name, e.g. 'London' or 'New York'.  Must be non-empty."]) -> dict`
- [ ] URL-encode the city with `quote(city, safe="")` before inserting into the URL
- [ ] Call `GET https://wttr.in/{safe_city}?format=j1` via `httpx.AsyncClient(timeout=15.0)`
- [ ] Parse `data["current_condition"][0]`: cast `temp_C`, `temp_F`, `humidity`, `windspeedKmph` to `int`; extract `weatherDesc[0]["value"]` for condition
- [ ] Return `{"city": city, "condition": ..., "temp_c": ..., "temp_f": ..., "humidity_pct": ..., "wind_kph": ...}`
- [ ] Wrap in `try/except (httpx.HTTPStatusError, httpx.RequestError)` → return `{"error": str(exc), "hint": "Check city name spelling."}`
- [ ] Write a docstring: one-line summary, what the data source is, that values are real-time, and the return shape

### Relevant Context
- wttr.in JSON shape: `{ "current_condition": [{ "weatherDesc": [{"value": "Partly cloudy"}], "temp_C": "15", "temp_F": "59", "humidity": "72", "windspeedKmph": "19" }] }` — all numeric fields come back as **strings**, cast them
- Do NOT use `follow_redirects=True`; wttr.in responds directly on the first request
- `Annotated` import: `from typing import Annotated`

### Status
`[ ] pending`

---

## Sub-Task 3 — Implement `gsa_mks_get_programming_joke`

### Intent
Add the joke tool to `server.py`. Calls the free Official Joke API with no parameters
and no authentication. Demonstrates calling a distinct public API and returning
structured data.

### Expected Outcomes
- `server.py` contains `@mcp.tool(name="gsa_mks_get_programming_joke", ...)` on an async function
- Calling it (no arguments) returns `{"setup": "...", "punchline": "...", "joke_type": "programming"}`
- Network failures return `{"error": "...", "hint": "..."}` — never raises

### Todo List
- [ ] Add `@mcp.tool` decorator block with `name="gsa_mks_get_programming_joke"` and annotations: `readOnlyHint: True`, `destructiveHint: False`, `idempotentHint: False`, `openWorldHint: True`
- [ ] Define `async def gsa_mks_get_programming_joke() -> dict` (no parameters at all)
- [ ] Call `GET https://official-joke-api.appspot.com/jokes/programming/random` via `httpx.AsyncClient(timeout=10.0)`
- [ ] Parse `response.json()[0]` — the API returns a list with one item
- [ ] Return `{"setup": data["setup"], "punchline": data["punchline"], "joke_type": data["type"]}`
- [ ] Wrap in `try/except (httpx.HTTPStatusError, httpx.RequestError)` → return `{"error": str(exc), "hint": "The joke API may be temporarily unavailable."}`
- [ ] Write a docstring describing the data source and return shape

### Relevant Context
- API response shape: `[{ "id": 23, "type": "programming", "setup": "Why do Java developers...", "punchline": "Because they don't C#" }]`
- No API key needed; no documented rate limits — safe for hackathon use
- `httpx` is already imported from Sub-Task 2; no new import needed

### Status
`[ ] pending`

---

## Sub-Task 4 — Implement `gsa_mks_convert_units`

### Intent
Add the unit converter tool to `server.py`. Pure local arithmetic — no network call.
Uses a dispatch table (dict of `(from, to)` tuples → lambda) to keep the function
concise and easy to extend.

### Expected Outcomes
- `server.py` contains `@mcp.tool(name="gsa_mks_convert_units", ...)` on an async function
- Accepts `value: float`, `from_unit: str`, `to_unit: str`
- Supported pairs: `celsius`↔`fahrenheit`, `celsius`↔`kelvin`, `fahrenheit`↔`kelvin`, `km`↔`miles`, `kg`↔`pounds`, `liters`↔`gallons` (12 directions total)
- Returns `{"original_value": ..., "from_unit": ..., "converted_value": ..., "to_unit": ...}`
- Unsupported pair returns `{"error": "Unsupported conversion.", "hint": "Supported units: celsius, fahrenheit, kelvin, km, miles, kg, pounds, liters, gallons"}`

### Todo List
- [ ] Define `_CONVERSIONS: dict[tuple[str, str], ...]` at module level (before the tool) mapping `(from_unit, to_unit)` tuples to lambda functions for the 12 conversion directions
- [ ] Include all 12 directions (see formulas in Relevant Context)
- [ ] Add `@mcp.tool` decorator with `name="gsa_mks_convert_units"` and annotations: `readOnlyHint: True`, `destructiveHint: False`, `idempotentHint: True`, `openWorldHint: False`
- [ ] Define `async def gsa_mks_convert_units(value: Annotated[float, "The numeric value to convert."], from_unit: Annotated[str, "Unit to convert from. One of: celsius, fahrenheit, kelvin, km, miles, kg, pounds, liters, gallons."], to_unit: Annotated[str, "Unit to convert to. Must be in the same unit family as from_unit."]) -> dict`
- [ ] Normalise inputs: `from_unit.lower().strip()`, `to_unit.lower().strip()`
- [ ] Look up `(from_unit, to_unit)` in `_CONVERSIONS`; if missing return the error/hint dict
- [ ] If found, compute `result = round(_CONVERSIONS[(from_unit, to_unit)](value), 6)` and return the result dict
- [ ] Write a docstring listing supported unit families and the return shape

### Relevant Context
- Conversion formulas:
  - `celsius → fahrenheit`: `v * 9/5 + 32`
  - `fahrenheit → celsius`: `(v - 32) * 5/9`
  - `celsius → kelvin`: `v + 273.15`
  - `kelvin → celsius`: `v - 273.15`
  - `fahrenheit → kelvin`: `(v - 32) * 5/9 + 273.15`
  - `kelvin → fahrenheit`: `(v - 273.15) * 9/5 + 32`
  - `km → miles`: `v * 0.621371`
  - `miles → km`: `v / 0.621371`
  - `kg → pounds`: `v * 2.20462`
  - `pounds → kg`: `v / 2.20462`
  - `liters → gallons`: `v * 0.264172`
  - `gallons → liters`: `v / 0.264172`
- `openWorldHint: False` because this tool does no external I/O
- No new imports needed — this is pure Python

### Status
`[ ] pending`

---

## Sub-Task 5 — Local Test: Init, Discovery, and Every Tool Call

### Intent
Verify the toolkit works correctly before touching Orchestrate. Run three checks:
init (the server starts cleanly), tool discovery (all three tools are listed), and
tool calls (each tool returns correct output). These are the same checks Orchestrate
will run at import time.

### Expected Outcomes
- `python server.py` starts without error and waits on stdin
- A FastMCP in-process test confirms all three tool names are discoverable
- `gsa_mks_get_current_weather("London")` returns a dict with `temp_c` key
- `gsa_mks_get_programming_joke()` returns a dict with `setup` and `punchline` keys
- `gsa_mks_convert_units(100.0, "celsius", "fahrenheit")` returns `{"converted_value": 212.0, ...}`
- `gsa_mks_convert_units(5.0, "km", "miles")` returns `{"converted_value": 3.10686, ...}` (approximately)

### Todo List
- [ ] Create `toolkits/gsa_mks_tools/test_local.py` — a standalone async test script (not pytest)
- [ ] Import the three tool functions directly from `server.py` and call them with `await` inside `asyncio.run(main())`
- [ ] Assert each result has the expected keys and correct types (not just print)
- [ ] Add a tool discovery check: create a `FastMCP` instance, register tools, call `await mcp.list_tools()`, assert all three `gsa_mks_*` names are present
- [ ] Run: `cd toolkits/gsa_mks_tools && python test_local.py` — all assertions pass
- [ ] Confirm the internet-access tools return real (non-stub) data

### Relevant Context
- To call the tools directly for testing, define them as module-level `async def` functions that the `@mcp.tool` decorator wraps — FastMCP preserves the original callable, so you can `await gsa_mks_get_current_weather("London")` directly in the test
- Alternatively, use the FastMCP in-process test client: `async with mcp.test_client() as client: result = await client.call_tool("gsa_mks_get_current_weather", {"city": "London"})`
- The test file is local only — it does not need to ship to Orchestrate

### Status
`[x] done`

---

## Sub-Task 6 — Create `toolkit.yaml` and Import into Orchestrate

### Intent
Write the toolkit spec file and import the toolkit into the active watsonx Orchestrate
environment via `orchestrate toolkits import`. Then verify all three tools are visible
in `orchestrate toolkits list`.

### Expected Outcomes
- `toolkits/gsa_mks_tools/toolkit.yaml` exists with `kind: mcp`, `name: gsa_mks_tools`, `command: python server.py`, `tools: ["*"]`, and `package_root` pointing at `toolkits/gsa_mks_tools/`
- `orchestrate toolkits import -f toolkits/gsa_mks_tools/toolkit.yaml` succeeds
- `orchestrate toolkits list` shows `gsa_mks_tools`
- The three tool names (`gsa_mks_get_current_weather`, `gsa_mks_get_programming_joke`, `gsa_mks_convert_units`) are visible in the Orchestrate UI or via the MCP list tools call

### Todo List
- [ ] Create `toolkits/gsa_mks_tools/toolkit.yaml` with:
  ```yaml
  spec_version: v1
  kind: mcp
  name: gsa_mks_tools
  description: "GSA MKS toolkit: current weather, programming jokes, and unit conversion."
  command: python server.py
  env: []
  tools:
    - "*"
  package_root: ./toolkits/gsa_mks_tools
  ```
- [ ] Confirm the ADK environment is active: `orchestrate env list` shows an active env
- [ ] Run: `orchestrate toolkits import -f toolkits/gsa_mks_tools/toolkit.yaml`
- [ ] Run: `orchestrate toolkits list` — confirm `gsa_mks_tools` appears
- [ ] Use the MCP tool `list_toolkits` to verify from within Bob
- [ ] Confirm all three `gsa_mks_*` tool names are visible

### Relevant Context
- `toolkit.yaml` schema from [`deploy/ibm/local-mcp-toolkit/toolkit.yaml`](mcp-hackathon-template/deploy/ibm/local-mcp-toolkit/toolkit.yaml): `spec_version: v1`, `kind: mcp`, `command`, `tools`, `package_root`
- `package_root` is the directory Orchestrate uploads and installs deps from — point it at `toolkits/gsa_mks_tools/` (relative to where the CLI runs, which is the workspace root)
- No `connections:` needed — none of the three tools require credentials
- If the toolkit already exists from a previous attempt: `orchestrate toolkits remove --name gsa_mks_tools` before re-importing

### Status
`[ ] pending`
