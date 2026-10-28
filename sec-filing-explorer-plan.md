# SEC Filing Facts Explorer — Implementation Plan

## Top-Level Overview

Build a new FastMCP toolkit (`sec_edgar_tools`) and a paired native watsonx Orchestrate agent (`sec_edgar_agent`) that let an agent answer authoritative questions about SEC EDGAR filings and XBRL financial-statement data without relying on unconstrained internet search.

The toolkit wraps three public SEC REST APIs (no API key required):
- `https://www.sec.gov/files/company_tickers.json` — CIK lookup
- `https://data.sec.gov/submissions/CIK{10-digits}.json` — filing history & metadata
- `https://data.sec.gov/api/xbrl/companyfacts/CIK{10-digits}.json` — all XBRL facts

**Scope:** six MCP tools + one native agent + local test script + toolkit/agent YAML files.
**Not in scope:** bulk file downloads, disk-based caching, rate-limit token buckets, authentication/connections (SEC is public).

**Pattern source:** `toolkits/gsa_mks_tools/server.py` — FastMCP, async httpx, plain dict returns, `{"error": "…", "hint": "…"}` on failure.

**SEC User-Agent header (required on every request):**
```
Michael Schihl schihlm@sec.gov
```

---

## Sub-Task 1 — Scaffold the toolkit directory

**Intent:** Create the folder structure and supporting files so the toolkit can be imported into Orchestrate with zero changes to the import command.

**Expected Outcomes:**
- `toolkits/sec_edgar_tools/` exists with `requirements.txt`, `toolkit.yaml`, and an empty (stub) `server.py`
- `toolkit.yaml` follows the exact same schema as `toolkits/gsa_mks_tools/toolkit.yaml`
- `requirements.txt` lists only the packages the server needs

**Todo List:**
1. Create `toolkits/sec_edgar_tools/` directory
2. Write `toolkits/sec_edgar_tools/requirements.txt`:
   - `fastmcp>=2.0.0`
   - `httpx>=0.27.0`
   - `pydantic>=2.0.0`
3. Write `toolkits/sec_edgar_tools/toolkit.yaml`:
   - `spec_version: v1`, `kind: mcp`, `name: sec_edgar_tools`
   - `description:` one-line description of the toolkit
   - `command: python server.py`
   - `package_root: /home/itzuser/wxo-agentic-workflow/toolkits/sec_edgar_tools` (absolute path — same pattern as existing toolkit)
   - `tools: ["*"]`
4. Write a stub `toolkits/sec_edgar_tools/server.py` with the `FastMCP` instance declared (no tools yet) so Sub-Task 2 can fill it in

**Relevant Context:**
- Pattern: [`toolkits/gsa_mks_tools/toolkit.yaml`](toolkits/gsa_mks_tools/toolkit.yaml)
- Pattern: [`toolkits/gsa_mks_tools/requirements.txt`](toolkits/gsa_mks_tools/requirements.txt)

**Status:** [ ] pending

---

## Sub-Task 2 — Implement the five MCP tools in `server.py`

**Intent:** Write all five SEC EDGAR tools as async `@mcp.tool` functions inside `server.py`, following the patterns established in `gsa_mks_tools/server.py`.

**Expected Outcomes:**
- All five tools are registered in the FastMCP instance
- Every tool returns a plain `dict`; errors return `{"error": "…", "hint": "…"}`
- The SEC User-Agent header is applied via a single module-level constant and used by every `httpx` call
- CIK lookup is cached in a module-level dict (populated on first call) so the 6 MB `company_tickers.json` is only downloaded once per process lifetime
- The `if __name__ == "__main__": mcp.run(transport="stdio")` entry point is present

**Tool Specifications:**

### Tool 1 — `sec_edgar_resolve_company`
- **Purpose:** Resolve a company ticker symbol OR a raw CIK to canonical company info
- **Inputs:** `identifier: Annotated[str, "Ticker symbol (e.g. 'AAPL') or numeric CIK string"]`
- **Implementation:** Fetch `https://www.sec.gov/files/company_tickers.json` (cache in module-level dict `_TICKER_CACHE`). Match on ticker (case-insensitive) or on CIK integer value. Then fetch `https://data.sec.gov/submissions/CIK{padded}.json` to get `name`, `sic`, `sicDescription`, `stateOfIncorporation`.
- **Returns:** `{"cik": "0000320193", "name": "Apple Inc.", "ticker": "AAPL", "sic": "3571", "sic_description": "Electronic Computers", "state_of_incorporation": "CA"}`
- **Error cases:** ticker/CIK not found in SEC database; network failure

### Tool 2 — `sec_edgar_get_recent_filings`
- **Purpose:** Return recent SEC filings for a company, optionally filtered by form type
- **Inputs:**
  - `identifier: Annotated[str, "Ticker symbol or CIK"]`
  - `form_type: Annotated[str, "Form type filter, e.g. '10-K', '10-Q', '8-K'. Use empty string or 'all' for all types."]`
  - `limit: Annotated[int, "Maximum number of filings to return. Default 10, max 50."]`
- **Implementation:** Fetch `https://data.sec.gov/submissions/CIK{padded}.json`. Parse the `filings.recent` object (parallel arrays: `form`, `filingDate`, `reportDate`, `accessionNumber`, `primaryDocument`). Filter by form_type if provided. Slice to `limit`.
- **Returns:** `{"company": "Apple Inc.", "cik": "0000320193", "filings": [{"form": "10-K", "filing_date": "2024-11-01", "report_date": "2024-09-28", "accession_number": "0000320193-24-000123", "primary_document": "aapl-20240928.htm"}]}`
- **Note:** `limit` is capped at 50 server-side regardless of the requested value

### Tool 3 — `sec_edgar_get_company_fact`
- **Purpose:** Return the full time series for a single XBRL concept for one company
- **Inputs:**
  - `identifier: Annotated[str, "Ticker symbol or CIK"]`
  - `taxonomy: Annotated[str, "XBRL taxonomy, e.g. 'us-gaap' or 'dei'"]`
  - `concept: Annotated[str, "XBRL concept tag, e.g. 'Revenues', 'NetIncomeLoss', 'Assets'"]`
  - `limit: Annotated[int, "Maximum observations per unit type to return. 0 = all. Default 8."]`
- **Implementation:** Fetch `https://data.sec.gov/api/xbrl/companyfacts/CIK{padded}.json`. Navigate `facts[taxonomy][concept]`. Return all unit types as separate lists under a `units` dict. If `limit > 0`, slice each list to the last `limit` entries (most recent last). Include `label` and `description` from the concept metadata.
- **Returns:**
```json
{
  "company": "Apple Inc.",
  "cik": "0000320193",
  "taxonomy": "us-gaap",
  "concept": "Revenues",
  "label": "Revenue from Contract with Customer...",
  "description": "...",
  "units": {
    "USD": [
      {"end": "2024-09-28", "val": 391035000000, "form": "10-K",
       "accn": "0000320193-24-000123", "fy": 2024, "fp": "FY", "frame": "CY2024"}
    ]
  }
}
```
- **Error cases:** taxonomy or concept not found for this company; network failure

### Tool 4 — `sec_edgar_compare_companies`
- **Purpose:** Compare a single XBRL concept across multiple companies, returning the most recent annual figure for each plus comparability warnings
- **Inputs:**
  - `identifiers: Annotated[list[str], "List of ticker symbols or CIKs to compare"]`
  - `taxonomy: Annotated[str, "XBRL taxonomy, e.g. 'us-gaap'"]`
  - `concept: Annotated[str, "XBRL concept tag, e.g. 'Revenues'"]`
- **Implementation:**
  1. For each identifier, resolve CIK then fetch company facts
  2. For each company, find the most recent `FY` (full-year) entry under the most common unit type
  3. Compare fiscal year end dates (`end` field) across companies — emit a warning if any two differ by more than 45 days
  4. Check that all companies report in the same unit; emit a warning if units differ
  5. Collect results; partial success is acceptable (include companies that succeeded, note failures in warnings)
  6. Throttle calls: `asyncio.sleep(0.12)` between sequential company fetches to respect the SEC 10 req/s limit
- **Returns:**
```json
{
  "concept": "Revenues",
  "taxonomy": "us-gaap",
  "results": [
    {"company": "Apple Inc.", "cik": "0000320193", "ticker": "AAPL",
     "value": 391035000000, "unit": "USD", "period_end": "2024-09-28",
     "fiscal_year": 2024, "accession_number": "0000320193-24-000123", "form": "10-K"},
    {"company": "Microsoft Corp", ...}
  ],
  "warnings": [
    "Fiscal year ends differ: AAPL ends 2024-09-28, MSFT ends 2024-06-30 (90 days apart — not calendar-year aligned)"
  ]
}
```

### Tool 5 — `sec_edgar_get_filing_metadata`
- **Purpose:** Return the filing index and document list for a specific accession number — answers "which filing supplied this number?"
- **Inputs:**
  - `identifier: Annotated[str, "Ticker symbol or CIK"]`
  - `accession_number: Annotated[str, "Accession number, e.g. '0000320193-24-000123' or '000032019324000123'"]`
- **Implementation:** Normalize accession number to dashed format (`XXXXXXXXXX-YY-ZZZZZZ`). Fetch `https://data.sec.gov/submissions/CIK{padded}.json` and locate the filing in `filings.recent` arrays by accession number. Return form type, filing date, report date, primary document, and the EDGAR viewer URL.
- **Returns:**
```json
{
  "company": "Apple Inc.",
  "cik": "0000320193",
  "accession_number": "0000320193-24-000123",
  "form": "10-K",
  "filing_date": "2024-11-01",
  "report_date": "2024-09-28",
  "primary_document": "aapl-20240928.htm",
  "edgar_viewer_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
}
```

### Tool 6 — `sec_edgar_search_companies`
- **Purpose:** Search for companies by partial name — lets users discover a ticker or CIK without already knowing it
- **Inputs:**
  - `query: Annotated[str, "Partial company name to search for, e.g. 'apple', 'berkshire', 'general electric'"]`
  - `limit: Annotated[int, "Maximum number of matches to return. Default 10, max 50."]`
- **Implementation:** Reuse `_TICKER_CACHE` (populated from `company_tickers.json` — no extra API call). Do a case-insensitive substring match against the `title` field of every entry. Slice to `min(limit, 50)` results. Because this is a pure in-memory scan with no network call, it is always fast and costs zero against the SEC rate limit.
- **Returns:**
```json
{
  "query": "apple",
  "match_count": 3,
  "matches": [
    {"ticker": "AAPL", "cik": "0000320193", "name": "Apple Inc."},
    {"ticker": "APLE", "cik": "0001418121", "name": "Apple Hospitality REIT Inc"},
    {"ticker": "AGPL", "cik": "0001754820", "name": "Apple Green Holding Inc"}
  ]
}
```
- **Note:** If `_TICKER_CACHE` is empty (first call before `resolve_company` has been called), fetch and populate it first, then search.
- **Error cases:** empty query string

**Relevant Context:**
- Pattern: [`toolkits/gsa_mks_tools/server.py`](toolkits/gsa_mks_tools/server.py) — FastMCP instance, `@mcp.tool` decorator with `annotations` dict, `Annotated` params, async httpx, dict returns
- SEC User-Agent: `"Michael Schihl schihlm@sec.gov"` — module-level constant `SEC_USER_AGENT`, used in every `httpx.AsyncClient` headers dict
- CIK cache: module-level `_TICKER_CACHE: dict = {}` — populated on first call to any function that needs it

**Status:** [ ] pending

---

## Sub-Task 3 — Write the local test script

**Intent:** Write `toolkits/sec_edgar_tools/test_local.py` that validates all six tools locally against the live SEC APIs, following the same three-section structure as `gsa_mks_tools/test_local.py`.

**Expected Outcomes:**
- Script tests initialization, tool discovery (all six `sec_edgar_*` names), and direct async tool calls
- Uses **Apple Inc. (AAPL, CIK 0000320193)** and **Microsoft Corp (MSFT)** as test fixtures — both are stable, well-known, and have rich XBRL data
- Tests `sec_edgar_compare_companies` with AAPL + MSFT on `us-gaap / Revenues` and asserts that a `warnings` list is present (even if empty)
- Tests `sec_edgar_search_companies` with query `"apple"` and asserts AAPL appears in results
- Tests the error path: an unknown ticker returns `{"error": "…", "hint": "…"}`
- Can be run from the workspace root: `python toolkits/sec_edgar_tools/test_local.py`

**Relevant Context:**
- Pattern: [`toolkits/gsa_mks_tools/test_local.py`](toolkits/gsa_mks_tools/test_local.py)
- Note that `test_local.py` does not use pytest — it runs as a plain async `main()` with `asyncio.run(main())`

**Status:** [ ] pending

---

## Sub-Task 4 — Write the agent YAML and import scripts

**Intent:** Define the `sec_edgar_agent` native agent and write the `import-all.sh` / `delete-all.sh` scripts for one-command deployment.

**Expected Outcomes:**
- `agents/sec_edgar_agent.yaml` is a valid native agent spec referencing all six toolkit tools
- Agent instructions include explicit tool-selection rules mapped to the four example question patterns from the brief plus the company search pattern
- `scripts/import-all.sh` imports the toolkit then the agent (toolkit first — dependency order)
- `scripts/delete-all.sh` removes in reverse order

**Agent Spec:**
```yaml
spec_version: v1
kind: native
name: sec_edgar_agent
description: >
  SEC EDGAR filing and financial facts explorer. Retrieves authoritative
  filing history, XBRL financial-statement data, and cross-company comparisons
  from the SEC's public APIs. Use this agent for questions about annual revenue,
  earnings, assets, recent 10-K/10-Q filings, or any XBRL financial concept.
llm: groq/openai/gpt-oss-120b
style: react_core
```

**Instructions must cover:**
1. "Show the latest N annual observations for concept X" → `sec_edgar_resolve_company` → `sec_edgar_get_company_fact` with `limit=N`, filter for `FY` (full-year) entries
2. "Which filing supplied each number?" → `sec_edgar_get_filing_metadata` with the accession number from the fact observation
3. "List recent 10-K and 10-Q filings for a ticker" → `sec_edgar_get_recent_filings` with the appropriate form_type (call twice if both types needed, or once with `""` and filter in response)
4. "Compare concept X across companies" → `sec_edgar_compare_companies`; always surface `warnings` from the result to the user
5. "Find a company by name" / user doesn't know the ticker → `sec_edgar_search_companies` first, then proceed with the resolved ticker/CIK

**Starter Prompts (5):**
1. "Show me the last 8 annual revenue figures for Apple."
2. "List recent 10-K and 10-Q filings for Microsoft."
3. "Compare annual net income for AAPL, MSFT, and GOOGL."
4. "Which SEC filing reported Apple's 2024 annual revenue?"
5. "Find all companies with 'Berkshire' in their name."

**Import script notes:**
- Check whether `scripts/` directory exists; create it if not
- `toolkit.yaml` uses `orchestrate toolkits import -f` (not `tools import`)
- Toolkit must be imported before the agent that references its tools
- Both scripts `source venv/bin/activate` first

**Relevant Context:**
- Pattern: [`toolkits/gsa_mks_tools/toolkit.yaml`](toolkits/gsa_mks_tools/toolkit.yaml)
- Pattern: [`agents/gsa_mks_agent.yaml`](agents/gsa_mks_agent.yaml)
- Toolkit tools are referenced in agent YAML as `sec_edgar_tools:sec_edgar_*` (toolkit_name:tool_name format)

**Status:** [ ] pending

---

## Sub-Task 5 — Deploy and smoke-test

**Intent:** Import the toolkit and agent into the active Orchestrate environment and verify all six tools fire correctly end-to-end.

**Expected Outcomes:**
- `./scripts/import-all.sh` completes without errors
- All six `sec_edgar_*` tools appear in `orchestrate tools list`
- `sec_edgar_agent` appears in `orchestrate agents list`
- Smoke-test via `chat_with_agent` MCP tool: at least one single-turn prompt succeeds and shows correct tool firing in reasoning trace
- `TEST_REPORT.md` written to workspace root

**Smoke-test prompts to run:**
1. "Resolve the company AAPL" — expects `sec_edgar_resolve_company` to fire
2. "Show me the last 5 annual Revenues figures for Apple" — expects `sec_edgar_resolve_company` + `sec_edgar_get_company_fact`
3. "Compare annual Revenues for AAPL and MSFT" — expects `sec_edgar_compare_companies` + warnings surface

**Fix loop:** If any test fails — read agent reasoning → fix `server.py` or `sec_edgar_agent.yaml` → re-run `./scripts/import-all.sh` → re-test.

**Relevant Context:**
- Active Orchestrate env: `gsa-hackathon` (IBM Cloud Toronto, `ca-tor` region)
- If token is expired: `orchestrate env activate gsa-hackathon --api-key "$WXO_API_KEY"`
- MCP tool: `mcp__watsonx-orchestrate-adk__chat_with_agent` with `include_reasoning=True`

**Status:** [ ] pending
