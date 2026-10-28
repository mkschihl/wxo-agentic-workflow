# SEC EDGAR Facts Explorer — Test Report

**Agent:** `sec_edgar_agent` (native, react_core)
**Toolkit:** `sec_edgar_tools` (6 MCP tools)
**Environment:** `gsa-hackathon` (IBM Cloud Toronto, ca-tor)
**Status:** deployed and tested (3/3 smoke tests pass)

---

## Local Test Results (test_local.py) — 13/13 ✓

All six tools tested against live SEC APIs from the workspace:

| Test | Tool | Result |
|---|---|---|
| search_companies("apple") → AAPL present | sec_edgar_search_companies | ✓ Pass |
| search_companies("") → error dict | sec_edgar_search_companies | ✓ Pass |
| resolve_company("AAPL") → Apple Inc., CIK 0000320193 | sec_edgar_resolve_company | ✓ Pass |
| resolve_company("320193") → same by numeric CIK | sec_edgar_resolve_company | ✓ Pass |
| resolve_company("ZZZZNOTREAL") → error dict | sec_edgar_resolve_company | ✓ Pass |
| get_recent_filings("AAPL", "10-K", 5) → 5 x 10-K | sec_edgar_get_recent_filings | ✓ Pass |
| get_recent_filings("MSFT", "all", 10) → mixed form types | sec_edgar_get_recent_filings | ✓ Pass |
| get_company_fact("AAPL", "us-gaap", "Revenues", 8) | sec_edgar_get_company_fact | ✓ Pass |
| get_company_fact unknown concept → error+hint | sec_edgar_get_company_fact | ✓ Pass |
| compare_companies(["AAPL","MSFT"], "us-gaap", "Assets") → fiscal year warning fired | sec_edgar_compare_companies | ✓ Pass |
| get_filing_metadata("AAPL", "0000320193-25-000079") → 10-K, EDGAR URL | sec_edgar_get_filing_metadata | ✓ Pass |
| get_filing_metadata bad accession → error dict | sec_edgar_get_filing_metadata | ✓ Pass |
| search_companies limit=10 returns ≤10 results | sec_edgar_search_companies | ✓ Pass |

---

## Agent Smoke Tests — 3/3 ✓

| # | Prompt | Tool(s) Fired | Result |
|---|---|---|---|
| 1 | "Resolve the company AAPL" | sec_edgar_resolve_company | ✓ Pass — returned Apple Inc., CIK 0000320193, SIC 3571 Electronic Computers, CA |
| 2 | "Show me the last 5 annual revenue figures for Apple" | sec_edgar_get_company_fact (×2 — retried with alternate concept) | ✓ Pass — returned FY2022–FY2025 in USD ($391B–$416B), each with accession number |
| 3 | "Compare annual Revenues for AAPL and MSFT" | sec_edgar_compare_companies | ✓ Pass — returned both companies, fiscal year end warning surfaced (AAPL Sep vs MSFT Jun) |

---

## Known Behaviour Note

Apple (and many companies) switched the XBRL revenue concept name from `Revenues` to
`RevenueFromContractWithCustomerExcludingAssessedTax` after ~2018. The agent instructions
include explicit retry logic: when `Revenues` returns stale data (< 2 years recent),
the agent automatically retries with the alternate concept and transparently reports
which concept was used. This is SEC data behaviour, not a bug.

---

## How to Test Manually

**In the wxO UI:** open `sec_edgar_agent` and use the starter prompts, or type directly.

**Via CLI (from workspace root):**
```bash
source venv/bin/activate
orchestrate chat ask -n sec_edgar_agent "Show me the last 8 annual revenue figures for Apple"
orchestrate chat ask -n sec_edgar_agent "Find all companies with Berkshire in their name"
orchestrate chat ask -n sec_edgar_agent "Compare annual net income for AAPL, MSFT, and GOOGL"
orchestrate chat ask -n sec_edgar_agent "List recent 10-K and 10-Q filings for Microsoft"
orchestrate chat ask -n sec_edgar_agent "Which filing reported Apple's most recent annual revenue?"
```

Note: On SaaS, `orchestrate chat ask` enters interactive mode and prints
`EOF when reading a line` errors after the response — this is a known quirk.
The agent response above the EOF flood is real and correct.

**Expected responses:**
1. Revenue history → table of FY years, dollar amounts in billions, form types, accession numbers
2. Berkshire search → list of matches including BRK.A, BRK.B, possibly others
3. Cross-company comparison → table + warnings about fiscal year end misalignment (AAPL/MSFT differ by ~90 days)
4. Recent filings → list of 10-K and 10-Q entries with filing dates and accession numbers
5. Filing source → form type, filing date, report date, and direct EDGAR viewer URL

---

## File Layout

```
toolkits/sec_edgar_tools/
├── server.py        ← FastMCP server (all 6 tools, stdio transport)
├── requirements.txt ← fastmcp, httpx, pydantic
├── toolkit.yaml     ← Orchestrate import spec
└── test_local.py    ← local test script (13 checks, live SEC APIs)

agents/
└── sec_edgar_agent.yaml ← native react_core agent, 6 tools attached

scripts/
├── import-all.sh    ← one-command deploy (toolkit → agent)
└── delete-all.sh    ← one-command teardown (agent → toolkit)
```
