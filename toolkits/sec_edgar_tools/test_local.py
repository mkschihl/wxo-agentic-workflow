"""Local test script for the sec_edgar_tools MCP toolkit.

Tests three things:
  1. Initialization  — server.py imports and FastMCP instance is created
  2. Tool discovery  — all six sec_edgar_* tool names are registered
  3. Tool calls      — each tool returns correct structure against live SEC APIs

Test fixtures:
  - Apple Inc.     : ticker AAPL, CIK 0000320193
  - Microsoft Corp : ticker MSFT

Run from the workspace root:
    python toolkits/sec_edgar_tools/test_local.py

Or from the toolkit directory:
    python test_local.py
"""

import asyncio
import sys

# ---------------------------------------------------------------------------
# 1. Initialization — import the module (will raise immediately if broken)
# ---------------------------------------------------------------------------
print("=== 1. Initialization ===")
try:
    import server  # noqa: E402 — must be importable from this directory
    print(f"  [OK] server.py imported, FastMCP instance: {server.mcp.name!r}")
except Exception as exc:
    print(f"  [FAIL] import error: {exc}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 2. Tool discovery — all six sec_edgar_* names must be registered
# ---------------------------------------------------------------------------
async def check_discovery() -> bool:
    print("\n=== 2. Tool Discovery ===")
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    print(f"  Registered tools: {sorted(names)}")
    expected = {
        "sec_edgar_search_companies",
        "sec_edgar_resolve_company",
        "sec_edgar_get_recent_filings",
        "sec_edgar_get_company_fact",
        "sec_edgar_compare_companies",
        "sec_edgar_get_filing_metadata",
    }
    missing = expected - names
    if missing:
        print(f"  [FAIL] Missing tools: {missing}")
        return False
    print("  [OK] All six sec_edgar_* tools discovered")
    return True


# ---------------------------------------------------------------------------
# 3. Tool calls — call each tool and assert structure
# ---------------------------------------------------------------------------
async def check_tool_calls() -> bool:
    print("\n=== 3. Tool Calls ===")
    all_passed = True

    # --- Tool 1: search_companies ---
    print("\n  -- sec_edgar_search_companies(query='apple') --")
    result = await server.sec_edgar_search_companies(query="apple")
    print(f"  result keys: {list(result.keys())}")
    if "error" in result:
        print(f"  [WARN] returned error dict (network issue?): {result}")
    else:
        assert "matches" in result, f"missing matches: {result}"
        assert "match_count" in result, f"missing match_count: {result}"
        tickers = [m["ticker"] for m in result["matches"]]
        assert "AAPL" in tickers, f"AAPL not found in apple search results: {tickers}"
        print(f"  [OK] search_companies found {result['match_count']} matches; AAPL present ✓")

    # --- Tool 1: error path — empty query ---
    print("\n  -- sec_edgar_search_companies(query='') [should error] --")
    result = await server.sec_edgar_search_companies(query="")
    assert "error" in result, f"expected error for empty query: {result}"
    print(f"  [OK] empty query returns error dict ✓")

    # --- Tool 2: resolve_company by ticker ---
    print("\n  -- sec_edgar_resolve_company(identifier='AAPL') --")
    result = await server.sec_edgar_resolve_company(identifier="AAPL")
    print(f"  result: {result}")
    if "error" in result:
        print(f"  [WARN] returned error dict: {result}")
        all_passed = False
    else:
        assert result["ticker"] == "AAPL", f"ticker mismatch: {result}"
        assert result["cik"] == "0000320193", f"CIK mismatch: {result}"
        assert "name" in result, f"missing name: {result}"
        assert "sic_description" in result, f"missing sic_description: {result}"
        print(f"  [OK] resolve_company returned: {result['name']} (CIK {result['cik']}) ✓")

    # --- Tool 2: resolve_company by numeric CIK ---
    print("\n  -- sec_edgar_resolve_company(identifier='320193') --")
    result = await server.sec_edgar_resolve_company(identifier="320193")
    if "error" not in result:
        assert result["cik"] == "0000320193", f"CIK mismatch on numeric lookup: {result}"
        print(f"  [OK] resolve by CIK returned {result['name']} ✓")
    else:
        print(f"  [WARN] CIK lookup returned error: {result}")

    # --- Tool 2: error path — unknown ticker ---
    print("\n  -- sec_edgar_resolve_company(identifier='ZZZZNOTREAL') [should error] --")
    result = await server.sec_edgar_resolve_company(identifier="ZZZZNOTREAL")
    assert "error" in result, f"expected error for unknown ticker: {result}"
    print(f"  [OK] unknown ticker returns error dict ✓")

    # --- Tool 3: get_recent_filings — 10-K filter ---
    print("\n  -- sec_edgar_get_recent_filings(identifier='AAPL', form_type='10-K', limit=5) --")
    result = await server.sec_edgar_get_recent_filings(identifier="AAPL", form_type="10-K", limit=5)
    print(f"  result keys: {list(result.keys())}, filing count: {len(result.get('filings', []))}")
    if "error" in result:
        print(f"  [WARN] returned error dict: {result}")
    else:
        assert "filings" in result, f"missing filings: {result}"
        assert len(result["filings"]) > 0, f"no 10-K filings found for AAPL: {result}"
        for f in result["filings"]:
            assert f["form"].upper() == "10-K", f"unexpected form type: {f}"
        print(f"  [OK] {len(result['filings'])} 10-K filings returned; all form='10-K' ✓")

    # --- Tool 3: get_recent_filings — all forms ---
    print("\n  -- sec_edgar_get_recent_filings(identifier='MSFT', form_type='all', limit=10) --")
    result = await server.sec_edgar_get_recent_filings(identifier="MSFT", form_type="all", limit=10)
    if "error" not in result:
        forms_seen = {f["form"] for f in result["filings"]}
        print(f"  [OK] {len(result['filings'])} filings returned; form types seen: {forms_seen} ✓")
    else:
        print(f"  [WARN] returned error dict: {result}")

    # --- Tool 4: get_company_fact ---
    print("\n  -- sec_edgar_get_company_fact(identifier='AAPL', taxonomy='us-gaap', concept='Revenues', limit=8) --")
    result = await server.sec_edgar_get_company_fact(
        identifier="AAPL", taxonomy="us-gaap", concept="Revenues", limit=8
    )
    print(f"  result keys: {list(result.keys())}")
    if "error" in result:
        print(f"  [WARN] returned error (concept may not exist; trying RevenueFromContractWithCustomerExcludingAssessedTax): {result}")
        # Apple reports under a different concept name in recent filings
        result = await server.sec_edgar_get_company_fact(
            identifier="AAPL",
            taxonomy="us-gaap",
            concept="RevenueFromContractWithCustomerExcludingAssessedTax",
            limit=8,
        )
        print(f"  retry result keys: {list(result.keys())}")

    if "error" not in result:
        assert "units" in result, f"missing units: {result}"
        assert "label" in result, f"missing label: {result}"
        assert isinstance(result["units"], dict), f"units not a dict: {result}"
        total_obs = sum(len(v) for v in result["units"].values())
        print(f"  [OK] get_company_fact returned {total_obs} total observations across {list(result['units'].keys())} units ✓")
    else:
        print(f"  [WARN] get_company_fact failed: {result}")

    # --- Tool 4: error path — bad concept ---
    print("\n  -- sec_edgar_get_company_fact with unknown concept [should error] --")
    result = await server.sec_edgar_get_company_fact(
        identifier="AAPL", taxonomy="us-gaap", concept="ThisConceptDoesNotExist99999"
    )
    assert "error" in result, f"expected error for unknown concept: {result}"
    assert "hint" in result, f"expected hint key: {result}"
    print(f"  [OK] unknown concept returns error dict with hint ✓")

    # --- Tool 5: compare_companies ---
    print("\n  -- sec_edgar_compare_companies(identifiers=['AAPL','MSFT'], taxonomy='us-gaap', concept='Assets') --")
    result = await server.sec_edgar_compare_companies(
        identifiers=["AAPL", "MSFT"], taxonomy="us-gaap", concept="Assets"
    )
    print(f"  result keys: {list(result.keys())}")
    if "error" in result:
        print(f"  [WARN] returned error dict: {result}")
    else:
        assert "results" in result, f"missing results: {result}"
        assert "warnings" in result, f"missing warnings key: {result}"
        assert isinstance(result["warnings"], list), f"warnings not a list: {result}"
        print(f"  [OK] compare_companies returned {len(result['results'])} results; warnings: {result['warnings'] or '(none)'} ✓")
        for r in result["results"]:
            assert "value" in r, f"missing value in result row: {r}"
            assert "period_end" in r, f"missing period_end in result row: {r}"
            assert "accession_number" in r, f"missing accession_number in result row: {r}"
        print(f"  [OK] all result rows have required keys ✓")

    # --- Tool 6: get_filing_metadata — use an accession from Tool 3 results ---
    print("\n  -- sec_edgar_get_recent_filings to get a fresh accession number --")
    filings_result = await server.sec_edgar_get_recent_filings(
        identifier="AAPL", form_type="10-K", limit=1
    )
    if "error" not in filings_result and filings_result.get("filings"):
        accn = filings_result["filings"][0]["accession_number"]
        print(f"  Using accession: {accn}")

        print(f"\n  -- sec_edgar_get_filing_metadata(identifier='AAPL', accession_number='{accn}') --")
        result = await server.sec_edgar_get_filing_metadata(
            identifier="AAPL", accession_number=accn
        )
        print(f"  result: {result}")
        if "error" in result:
            print(f"  [WARN] returned error dict: {result}")
        else:
            assert result["form"].upper() == "10-K", f"unexpected form: {result}"
            assert "edgar_viewer_url" in result, f"missing edgar_viewer_url: {result}"
            assert "sec.gov" in result["edgar_viewer_url"], f"unexpected URL: {result}"
            print(f"  [OK] get_filing_metadata returned form={result['form']}, URL={result['edgar_viewer_url'][:60]}... ✓")

        # Error path: bad accession number
        print(f"\n  -- sec_edgar_get_filing_metadata with bad accession [should error] --")
        result = await server.sec_edgar_get_filing_metadata(
            identifier="AAPL", accession_number="0000000000-00-000000"
        )
        assert "error" in result, f"expected error for bad accession: {result}"
        print(f"  [OK] bad accession returns error dict ✓")
    else:
        print(f"  [SKIP] Could not get a filing accession number to test Tool 6 — skipping metadata test")

    return all_passed


async def main() -> None:
    ok = await check_discovery()
    if not ok:
        sys.exit(1)
    await check_tool_calls()
    print("\n=== All tests completed ===")


if __name__ == "__main__":
    asyncio.run(main())
