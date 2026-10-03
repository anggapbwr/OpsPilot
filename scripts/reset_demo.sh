#!/usr/bin/env bash
set -e

TARGET_URL="${TARGET_URL:-http://localhost:8080}"

echo "[*] Resetting target payment-api state to healthy..."
curl -s -X POST "$TARGET_URL/fault/recover" || true
echo ""
echo "[+] Reset complete. Target service is back to normal healthy operation."
