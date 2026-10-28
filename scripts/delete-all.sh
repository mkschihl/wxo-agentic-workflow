#!/usr/bin/env bash
# delete-all.sh — remove the SEC EDGAR agent and toolkit from Orchestrate
# Reverse dependency order: agent first, then toolkit
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Activating venv ==="
source "$WORKSPACE/venv/bin/activate"

echo ""
echo "=== Removing sec_edgar_agent ==="
orchestrate agents remove -n sec_edgar_agent --kind native || true

echo ""
echo "=== Removing sec_edgar_tools toolkit ==="
orchestrate toolkits remove -n sec_edgar_tools || true

echo ""
echo "=== Done ==="
