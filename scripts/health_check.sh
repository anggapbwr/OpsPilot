#!/usr/bin/env bash
set -e

OPSPILOT_URL="${OPSPILOT_URL:-http://localhost:8000}"
TARGET_URL="${TARGET_URL:-http://localhost:8080}"

echo "=== OpsPilot Platform Health ==="
curl -s "$OPSPILOT_URL/health" | jq . || curl -s "$OPSPILOT_URL/health"
echo ""

echo "=== Component Details ==="
curl -s "$OPSPILOT_URL/api/v1/health" | jq . || curl -s "$OPSPILOT_URL/api/v1/health"
echo ""

echo "=== Target payment-api Health ==="
curl -s "$TARGET_URL/health" | jq . || curl -s "$TARGET_URL/health"
echo ""
