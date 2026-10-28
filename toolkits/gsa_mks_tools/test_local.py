"""Local test script for the gsa_mks_tools MCP toolkit.

Tests three things the lab requires:
  1. Initialization  — server.py imports and FastMCP instance is created
  2. Tool discovery  — all three gsa_mks_* tool names are registered
  3. Tool calls      — each tool returns correct structure and live data

Run from the toolkit directory:
    python test_local.py

Or from the workspace root:
    /home/itzuser/wxo-agentic-workflow/venv/bin/python toolkits/gsa_mks_tools/test_local.py
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
# 2. Tool discovery — all three gsa_mks_* names must be registered
# ---------------------------------------------------------------------------
async def check_discovery() -> bool:
    print("\n=== 2. Tool Discovery ===")
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    print(f"  Registered tools: {sorted(names)}")
    expected = {
        "gsa_mks_get_current_weather",
        "gsa_mks_get_programming_joke",
        "gsa_mks_convert_units",
    }
    missing = expected - names
    if missing:
        print(f"  [FAIL] Missing tools: {missing}")
        return False
    print("  [OK] All three gsa_mks_* tools discovered")
    return True


# ---------------------------------------------------------------------------
# 3. Tool calls — call each tool and assert structure
# ---------------------------------------------------------------------------
async def check_tool_calls() -> bool:
    print("\n=== 3. Tool Calls ===")
    all_passed = True

    # --- Weather ---
    print("\n  -- gsa_mks_get_current_weather(city='London') --")
    result = await server.gsa_mks_get_current_weather(city="London")
    print(f"  result: {result}")
    if "error" in result:
        print(f"  [WARN] returned error dict (network issue?): {result}")
    else:
        assert "temp_c" in result, f"missing temp_c: {result}"
        assert "condition" in result, f"missing condition: {result}"
        assert isinstance(result["temp_c"], int), f"temp_c not int: {result}"
        assert result["city"] == "London", f"city mismatch: {result}"
        print("  [OK] weather tool returned live data with correct keys")

    # --- Joke ---
    print("\n  -- gsa_mks_get_programming_joke() --")
    result = await server.gsa_mks_get_programming_joke()
    print(f"  result: {result}")
    if "error" in result:
        print(f"  [WARN] returned error dict (network issue?): {result}")
    else:
        assert "setup" in result, f"missing setup: {result}"
        assert "punchline" in result, f"missing punchline: {result}"
        assert "joke_type" in result, f"missing joke_type: {result}"
        assert isinstance(result["setup"], str), f"setup not str: {result}"
        print("  [OK] joke tool returned live data with correct keys")

    # --- Unit converter: celsius → fahrenheit (boiling point) ---
    print("\n  -- gsa_mks_convert_units(100, 'celsius', 'fahrenheit') --")
    result = await server.gsa_mks_convert_units(
        value=100.0, from_unit="celsius", to_unit="fahrenheit"
    )
    print(f"  result: {result}")
    assert "error" not in result, f"unexpected error: {result}"
    assert abs(result["converted_value"] - 212.0) < 0.01, f"wrong value: {result}"
    print("  [OK] 100 °C = 212.0 °F ✓")

    # --- Unit converter: km → miles ---
    print("\n  -- gsa_mks_convert_units(5, 'km', 'miles') --")
    result = await server.gsa_mks_convert_units(
        value=5.0, from_unit="km", to_unit="miles"
    )
    print(f"  result: {result}")
    assert "error" not in result, f"unexpected error: {result}"
    assert abs(result["converted_value"] - 3.10686) < 0.001, f"wrong value: {result}"
    print("  [OK] 5 km ≈ 3.107 miles ✓")

    # --- Unit converter: unsupported pair ---
    print("\n  -- gsa_mks_convert_units(10, 'km', 'kg') [should error] --")
    result = await server.gsa_mks_convert_units(
        value=10.0, from_unit="km", to_unit="kg"
    )
    print(f"  result: {result}")
    assert "error" in result, f"expected error dict for unsupported pair: {result}"
    print("  [OK] unsupported pair returns error dict ✓")

    return all_passed


async def main() -> None:
    ok = await check_discovery()
    if not ok:
        sys.exit(1)
    await check_tool_calls()
    print("\n=== All tests passed ===")


if __name__ == "__main__":
    asyncio.run(main())
