"""SEC EDGAR MCP Toolkit — stdio transport.

Six tools exposed to watsonx Orchestrate:
  - sec_edgar_search_companies    : search exchange-listed companies by partial name
  - sec_edgar_resolve_company     : resolve ticker or CIK to canonical company info
  - sec_edgar_get_recent_filings  : recent filing history with optional form-type filter
  - sec_edgar_get_company_fact    : XBRL concept time series for one company
  - sec_edgar_compare_companies   : compare one XBRL concept across multiple companies
  - sec_edgar_get_filing_metadata : filing doc list and EDGAR URL for an accession number

Orchestrate starts this file as a subprocess and communicates over stdin/stdout.
SEC APIs require no API key. Rate limit: 10 req/s per IP.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Annotated

import httpx
from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Module-level constants and shared state
# ---------------------------------------------------------------------------

SEC_USER_AGENT = "Michael Schihl schihlm@sec.gov"

# In-memory cache: populated once per process lifetime on first call that
# needs it. Keys are uppercase tickers; values are raw SEC dict entries
# with keys: cik_str, ticker, title.
_TICKER_CACHE: dict[str, dict] = {}

# Secondary index keyed by zero-padded 10-digit CIK string
_CIK_CACHE: dict[str, dict] = {}

mcp = FastMCP(
    "sec_edgar_tools",
    instructions=(
        "SEC EDGAR toolkit with six tools for authoritative SEC filing data.\n\n"
        "TOOL SELECTION GUIDE:\n"
        "- Find companies by partial name → sec_edgar_search_companies\n"
        "- Resolve a ticker or CIK to canonical info → sec_edgar_resolve_company\n"
        "- List recent 10-K/10-Q/8-K filings → sec_edgar_get_recent_filings\n"
        "- Fetch an XBRL financial concept time series → sec_edgar_get_company_fact\n"
        "- Compare a concept across multiple companies → sec_edgar_compare_companies\n"
        "- Look up a specific filing by accession number → sec_edgar_get_filing_metadata\n\n"
        "No authentication required. All tools return dicts; errors include "
        "an 'error' key and a 'hint' key with recovery guidance."
    ),
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_headers() -> dict[str, str]:
    return {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}


async def _ensure_ticker_cache(client: httpx.AsyncClient) -> None:
    """Fetch company_tickers.json and populate _TICKER_CACHE / _CIK_CACHE if empty."""
    global _TICKER_CACHE, _CIK_CACHE
    if _TICKER_CACHE:
        return
    resp = await client.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers=_make_headers(),
    )
    resp.raise_for_status()
    data = resp.json()
    for entry in data.values():
        ticker = entry["ticker"].upper()
        padded_cik = f"{int(entry['cik_str']):010d}"
        record = {
            "ticker": ticker,
            "cik_str": padded_cik,
            "title": entry["title"],
        }
        _TICKER_CACHE[ticker] = record
        _CIK_CACHE[padded_cik] = record


def _normalize_accession(raw: str) -> str:
    """Normalize an accession number to dashed format XXXXXXXXXX-YY-ZZZZZZ."""
    clean = raw.replace("-", "").strip()
    if len(clean) != 18:
        return raw  # pass through unmodified; caller will handle the error
    return f"{clean[:10]}-{clean[10:12]}-{clean[12:]}"


def _accession_to_path(accession_dashed: str) -> str:
    """Convert '0000320193-24-000123' → '000032019324000123' (path segment form)."""
    return accession_dashed.replace("-", "")


def _days_between(date_str_a: str, date_str_b: str) -> int:
    """Return absolute day difference between two ISO date strings."""
    try:
        a = datetime.strptime(date_str_a, "%Y-%m-%d").date()
        b = datetime.strptime(date_str_b, "%Y-%m-%d").date()
        return abs((a - b).days)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Tool 1 — Search companies by partial name
# ---------------------------------------------------------------------------

@mcp.tool(
    name="sec_edgar_search_companies",
    annotations={
        "title": "Search SEC Companies by Name",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def sec_edgar_search_companies(
    query: Annotated[str, "Partial company name to search for, e.g. 'apple', 'berkshire', 'general electric'. Case-insensitive substring match."],
    limit: Annotated[int, "Maximum number of matches to return. Default 10, max 50."] = 10,
) -> dict:
    """Search SEC-registered exchange-listed companies by partial name.

    Searches the SEC's company_tickers.json (covers ~10,000 exchange-listed
    companies). Performs a case-insensitive substring match on the company
    title. The ticker cache is populated on the first call and reused for
    all subsequent calls in the same process.

    Returns a dict with keys: query, match_count, matches (list of
    ticker/cik/name). On failure returns {"error": "...", "hint": "..."}.
    """
    query = query.strip()
    if not query:
        return {"error": "query must not be empty.", "hint": "Provide a partial company name such as 'apple' or 'berkshire'."}
    limit = max(1, min(limit, 50))
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            await _ensure_ticker_cache(client)
        query_lower = query.lower()
        matches = [
            {"ticker": v["ticker"], "cik": v["cik_str"], "name": v["title"]}
            for v in _TICKER_CACHE.values()
            if query_lower in v["title"].lower()
        ]
        matches = matches[:limit]
        return {"query": query, "match_count": len(matches), "matches": matches}
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return {"error": str(exc), "hint": "Could not fetch company list from SEC. Try again shortly."}


# ---------------------------------------------------------------------------
# Tool 2 — Resolve company ticker or CIK
# ---------------------------------------------------------------------------

@mcp.tool(
    name="sec_edgar_resolve_company",
    annotations={
        "title": "Resolve SEC Company",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sec_edgar_resolve_company(
    identifier: Annotated[str, "Ticker symbol (e.g. 'AAPL') or numeric CIK string (e.g. '320193' or '0000320193')."],
) -> dict:
    """Resolve a company ticker symbol or CIK to canonical SEC company info.

    Looks up the company in the SEC's exchange-listed ticker file, then fetches
    the full submission metadata to return SIC code, industry description, and
    state of incorporation.

    Returns a dict with keys: cik, name, ticker, sic, sic_description,
    state_of_incorporation. On failure returns {"error": "...", "hint": "..."}.
    """
    identifier = identifier.strip()
    if not identifier:
        return {"error": "identifier must not be empty.", "hint": "Provide a ticker like 'AAPL' or a numeric CIK."}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            await _ensure_ticker_cache(client)

            # Determine if identifier is a CIK (all digits) or ticker
            clean_digits = identifier.lstrip("0")
            if identifier.isdigit() or (identifier.startswith("0") and identifier.isdigit()):
                padded_cik = f"{int(identifier):010d}"
                record = _CIK_CACHE.get(padded_cik)
            else:
                record = _TICKER_CACHE.get(identifier.upper())

            if record is None:
                return {
                    "error": f"'{identifier}' not found in the SEC exchange-listed company database.",
                    "hint": "Check the ticker spelling or use sec_edgar_search_companies to find the correct identifier.",
                }

            padded_cik = record["cik_str"]
            resp = await client.get(
                f"https://data.sec.gov/submissions/CIK{padded_cik}.json",
                headers=_make_headers(),
            )
            resp.raise_for_status()
            sub = resp.json()

        return {
            "cik": padded_cik,
            "name": sub.get("name", record["title"]),
            "ticker": record["ticker"],
            "sic": sub.get("sic", ""),
            "sic_description": sub.get("sicDescription", ""),
            "state_of_incorporation": sub.get("stateOfIncorporation", ""),
        }
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return {"error": str(exc), "hint": "Check the identifier and try again. The SEC API may be temporarily unavailable."}


# ---------------------------------------------------------------------------
# Tool 3 — Get recent filings
# ---------------------------------------------------------------------------

@mcp.tool(
    name="sec_edgar_get_recent_filings",
    annotations={
        "title": "Get Recent SEC Filings",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def sec_edgar_get_recent_filings(
    identifier: Annotated[str, "Ticker symbol or CIK."],
    form_type: Annotated[str, "Form type filter, e.g. '10-K', '10-Q', '8-K'. Use empty string or 'all' to return all form types."] = "",
    limit: Annotated[int, "Maximum number of filings to return. Default 10, max 50."] = 10,
) -> dict:
    """Return recent SEC filings for a company, optionally filtered by form type.

    Fetches the submission history from data.sec.gov. When form_type is empty
    or 'all', returns all recent form types. Results are ordered most-recent
    first.

    Returns a dict with keys: company, cik, form_type_filter, filings (list).
    Each filing has: form, filing_date, report_date, accession_number,
    primary_document. On failure returns {"error": "...", "hint": "..."}.
    """
    limit = max(1, min(limit, 50))
    form_filter = "" if form_type.strip().lower() in ("", "all") else form_type.strip().upper()
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            await _ensure_ticker_cache(client)

            # Resolve identifier to padded CIK
            if identifier.strip().isdigit():
                padded_cik = f"{int(identifier.strip()):010d}"
            else:
                record = _TICKER_CACHE.get(identifier.strip().upper())
                if record is None:
                    return {
                        "error": f"'{identifier}' not found in the SEC database.",
                        "hint": "Use sec_edgar_search_companies to find the correct ticker or CIK.",
                    }
                padded_cik = record["cik_str"]

            resp = await client.get(
                f"https://data.sec.gov/submissions/CIK{padded_cik}.json",
                headers=_make_headers(),
            )
            resp.raise_for_status()
            sub = resp.json()

        company_name = sub.get("name", identifier)
        recent = sub.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        filings = []
        for i in range(len(forms)):
            if form_filter and forms[i].upper() != form_filter:
                continue
            filings.append({
                "form": forms[i],
                "filing_date": filing_dates[i] if i < len(filing_dates) else "",
                "report_date": report_dates[i] if i < len(report_dates) else "",
                "accession_number": accessions[i] if i < len(accessions) else "",
                "primary_document": primary_docs[i] if i < len(primary_docs) else "",
            })
            if len(filings) >= limit:
                break

        return {
            "company": company_name,
            "cik": padded_cik,
            "form_type_filter": form_filter or "all",
            "filings": filings,
        }
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return {"error": str(exc), "hint": "Check the identifier and try again. The SEC API may be temporarily unavailable."}


# ---------------------------------------------------------------------------
# Tool 4 — Get company XBRL fact time series
# ---------------------------------------------------------------------------

@mcp.tool(
    name="sec_edgar_get_company_fact",
    annotations={
        "title": "Get XBRL Company Fact",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sec_edgar_get_company_fact(
    identifier: Annotated[str, "Ticker symbol or CIK."],
    taxonomy: Annotated[str, "XBRL taxonomy, e.g. 'us-gaap' or 'dei'."],
    concept: Annotated[str, "XBRL concept tag, e.g. 'Revenues', 'NetIncomeLoss', 'Assets'."],
    limit: Annotated[int, "Maximum observations per unit type to return. Use 0 for all. Default 8."] = 8,
) -> dict:
    """Return the XBRL fact time series for a single concept and company.

    Fetches all XBRL-tagged values for the given taxonomy/concept from the
    SEC companyfacts endpoint. Returns all unit types as separate lists under
    a 'units' dict (e.g. {'USD': [...], 'shares': [...]}). When limit > 0,
    each list is trimmed to the last N entries (most recent last).

    Returns a dict with keys: company, cik, taxonomy, concept, label,
    description, units. On failure returns {"error": "...", "hint": "..."}.
    """
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            await _ensure_ticker_cache(client)

            if identifier.strip().isdigit():
                padded_cik = f"{int(identifier.strip()):010d}"
            else:
                record = _TICKER_CACHE.get(identifier.strip().upper())
                if record is None:
                    return {
                        "error": f"'{identifier}' not found in the SEC database.",
                        "hint": "Use sec_edgar_search_companies to find the correct ticker or CIK.",
                    }
                padded_cik = record["cik_str"]

            resp = await client.get(
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{padded_cik}.json",
                headers=_make_headers(),
            )
            resp.raise_for_status()
            facts = resp.json()

        company_name = facts.get("entityName", identifier)
        taxonomy_data = facts.get("facts", {}).get(taxonomy)
        if taxonomy_data is None:
            available = list(facts.get("facts", {}).keys())
            return {
                "error": f"Taxonomy '{taxonomy}' not found for {company_name}.",
                "hint": f"Available taxonomies: {available}. Common values: 'us-gaap', 'dei'.",
            }

        concept_data = taxonomy_data.get(concept)
        if concept_data is None:
            sample = list(taxonomy_data.keys())[:10]
            return {
                "error": f"Concept '{concept}' not found in taxonomy '{taxonomy}' for {company_name}.",
                "hint": f"Sample available concepts (first 10): {sample}. Check spelling and capitalisation.",
            }

        label = concept_data.get("label", concept)
        description = concept_data.get("description", "")
        raw_units = concept_data.get("units", {})

        units_out: dict[str, list] = {}
        for unit_label, observations in raw_units.items():
            obs_list = list(observations)  # observations is already a list of dicts
            if limit > 0:
                obs_list = obs_list[-limit:]
            units_out[unit_label] = obs_list

        return {
            "company": company_name,
            "cik": padded_cik,
            "taxonomy": taxonomy,
            "concept": concept,
            "label": label,
            "description": description,
            "units": units_out,
        }
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return {"error": str(exc), "hint": "Check the identifier and concept, and try again."}


# ---------------------------------------------------------------------------
# Tool 5 — Compare XBRL concept across companies
# ---------------------------------------------------------------------------

@mcp.tool(
    name="sec_edgar_compare_companies",
    annotations={
        "title": "Compare XBRL Concept Across Companies",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sec_edgar_compare_companies(
    identifiers: Annotated[list[str], "List of ticker symbols or CIKs to compare, e.g. ['AAPL', 'MSFT', 'GOOGL']."],
    taxonomy: Annotated[str, "XBRL taxonomy, e.g. 'us-gaap'."],
    concept: Annotated[str, "XBRL concept tag, e.g. 'Revenues', 'NetIncomeLoss'."],
) -> dict:
    """Compare one XBRL financial concept across multiple companies.

    For each company, finds the most recent full-year (FY) observation under
    the most prevalent unit type. Emits warnings when fiscal year ends differ
    by more than 45 days across companies, or when unit types are inconsistent.
    Companies are fetched sequentially with a small delay to respect the SEC
    10 req/s rate limit.

    Returns a dict with keys: concept, taxonomy, results (list), warnings (list).
    Each result has: company, cik, ticker, value, unit, period_end, fiscal_year,
    accession_number, form. On failure returns {"error": "...", "hint": "..."}.
    """
    if not identifiers:
        return {"error": "identifiers must be a non-empty list.", "hint": "Provide at least one ticker or CIK."}

    results = []
    warnings: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            await _ensure_ticker_cache(client)

            for idx, identifier in enumerate(identifiers):
                if idx > 0:
                    await asyncio.sleep(0.12)  # respect SEC 10 req/s limit

                # Resolve CIK
                id_clean = identifier.strip()
                if id_clean.isdigit():
                    padded_cik = f"{int(id_clean):010d}"
                    cache_record = _CIK_CACHE.get(padded_cik)
                    ticker = cache_record["ticker"] if cache_record else id_clean
                else:
                    cache_record = _TICKER_CACHE.get(id_clean.upper())
                    if cache_record is None:
                        warnings.append(f"'{identifier}' not found in the SEC database — skipped.")
                        continue
                    padded_cik = cache_record["cik_str"]
                    ticker = cache_record["ticker"]

                try:
                    resp = await client.get(
                        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{padded_cik}.json",
                        headers=_make_headers(),
                    )
                    resp.raise_for_status()
                    facts = resp.json()
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    warnings.append(f"Could not fetch facts for '{identifier}': {exc} — skipped.")
                    continue

                company_name = facts.get("entityName", identifier)
                concept_data = (
                    facts.get("facts", {})
                    .get(taxonomy, {})
                    .get(concept)
                )
                if concept_data is None:
                    warnings.append(f"{company_name}: concept '{taxonomy}/{concept}' not found — skipped.")
                    continue

                raw_units = concept_data.get("units", {})

                # Pick the unit with the most observations
                best_unit = max(raw_units.keys(), key=lambda u: len(raw_units[u]), default=None)
                if best_unit is None:
                    warnings.append(f"{company_name}: no unit data for '{concept}' — skipped.")
                    continue

                observations = raw_units[best_unit]

                # Find the most recent full-year (fp == "FY") observation
                fy_obs = [o for o in observations if o.get("fp") == "FY" and o.get("form", "").startswith("10-")]
                if not fy_obs:
                    # Fall back to any FY observation
                    fy_obs = [o for o in observations if o.get("fp") == "FY"]
                if not fy_obs:
                    warnings.append(f"{company_name}: no full-year (FY) observations found for '{concept}' — using most recent available.")
                    fy_obs = observations

                latest = fy_obs[-1]
                results.append({
                    "company": company_name,
                    "cik": padded_cik,
                    "ticker": ticker,
                    "value": latest.get("val"),
                    "unit": best_unit,
                    "period_end": latest.get("end", ""),
                    "fiscal_year": latest.get("fy"),
                    "accession_number": latest.get("accn", ""),
                    "form": latest.get("form", ""),
                })

    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return {"error": str(exc), "hint": "A network error occurred. Check identifiers and try again."}

    # --- Post-collection comparability checks ---
    if len(results) >= 2:
        # Check unit consistency
        units_seen = {r["unit"] for r in results}
        if len(units_seen) > 1:
            unit_list = ", ".join(f"{r['ticker']}={r['unit']}" for r in results)
            warnings.append(f"Unit mismatch — companies report in different units: {unit_list}. Values are not directly comparable.")

        # Check fiscal year end alignment (45-day threshold)
        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                a, b = results[i], results[j]
                if a["period_end"] and b["period_end"]:
                    days = _days_between(a["period_end"], b["period_end"])
                    if days > 45:
                        warnings.append(
                            f"Fiscal year ends differ: {a['ticker']} ends {a['period_end']}, "
                            f"{b['ticker']} ends {b['period_end']} ({days} days apart — not calendar-year aligned)."
                        )

    return {
        "concept": concept,
        "taxonomy": taxonomy,
        "results": results,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Tool 6 — Get filing metadata by accession number
# ---------------------------------------------------------------------------

@mcp.tool(
    name="sec_edgar_get_filing_metadata",
    annotations={
        "title": "Get SEC Filing Metadata",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sec_edgar_get_filing_metadata(
    identifier: Annotated[str, "Ticker symbol or CIK."],
    accession_number: Annotated[str, "Accession number, e.g. '0000320193-24-000123' or '000032019324000123' (dashes optional)."],
) -> dict:
    """Return metadata for a specific SEC filing identified by its accession number.

    Answers the question 'which filing supplied this number?' by looking up
    the accession number in the company's submission history and returning
    the form type, dates, primary document filename, and a direct EDGAR
    viewer URL.

    Returns a dict with keys: company, cik, accession_number, form,
    filing_date, report_date, primary_document, edgar_viewer_url.
    On failure returns {"error": "...", "hint": "..."}.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            await _ensure_ticker_cache(client)

            if identifier.strip().isdigit():
                padded_cik = f"{int(identifier.strip()):010d}"
            else:
                record = _TICKER_CACHE.get(identifier.strip().upper())
                if record is None:
                    return {
                        "error": f"'{identifier}' not found in the SEC database.",
                        "hint": "Use sec_edgar_search_companies to find the correct ticker or CIK.",
                    }
                padded_cik = record["cik_str"]

            resp = await client.get(
                f"https://data.sec.gov/submissions/CIK{padded_cik}.json",
                headers=_make_headers(),
            )
            resp.raise_for_status()
            sub = resp.json()

        company_name = sub.get("name", identifier)
        accession_dashed = _normalize_accession(accession_number.strip())
        accession_path = _accession_to_path(accession_dashed)

        recent = sub.get("filings", {}).get("recent", {})
        accessions = recent.get("accessionNumber", [])

        idx = None
        for i, acc in enumerate(accessions):
            # Normalize stored value for comparison
            if _normalize_accession(acc) == accession_dashed:
                idx = i
                break

        if idx is None:
            return {
                "error": f"Accession number '{accession_dashed}' not found in recent filings for {company_name}.",
                "hint": "Verify the accession number. Very old filings may not appear in the recent submissions list.",
            }

        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_docs = recent.get("primaryDocument", [])

        form = forms[idx] if idx < len(forms) else ""
        filing_date = filing_dates[idx] if idx < len(filing_dates) else ""
        report_date = report_dates[idx] if idx < len(report_dates) else ""
        primary_doc = primary_docs[idx] if idx < len(primary_docs) else ""

        # Numeric CIK (no leading zeros) is used in the EDGAR archive path
        numeric_cik = str(int(padded_cik))
        edgar_url = (
            f"https://www.sec.gov/Archives/edgar/data/{numeric_cik}/{accession_path}/{primary_doc}"
            if primary_doc else
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={padded_cik}&type={form}"
        )

        return {
            "company": company_name,
            "cik": padded_cik,
            "accession_number": accession_dashed,
            "form": form,
            "filing_date": filing_date,
            "report_date": report_date,
            "primary_document": primary_doc,
            "edgar_viewer_url": edgar_url,
        }
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return {"error": str(exc), "hint": "Check the identifier and accession number and try again."}


if __name__ == "__main__":
    mcp.run(transport="stdio")
