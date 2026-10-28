#!/usr/bin/env bash
# import-all.sh — import the SEC EDGAR toolkit and agent into Orchestrate
# Dependency order: toolkit (tools must exist before agent references them)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Activating venv ==="
source "$WORKSPACE/venv/bin/activate"

echo "=== Active Orchestrate environment ==="
orchestrate env list

echo ""
echo "=== Importing sec_edgar_tools toolkit ==="
orchestrate toolkits import -f "$WORKSPACE/toolkits/sec_edgar_tools/toolkit.yaml"

echo ""
echo "=== Importing sec_edgar_agent ==="
orchestrate agents import -f "$WORKSPACE/agents/sec_edgar_agent.yaml"

echo ""
echo "=== Done — verify with: ==="
echo "  orchestrate tools list     (look for sec_edgar_* entries)"
echo "  orchestrate agents list    (look for sec_edgar_agent)"
