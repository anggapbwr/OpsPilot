#!/usr/bin/env bash
set -e

echo "[*] Starting OpsPilot environment via Docker Compose..."
docker compose up -d --build

echo "[*] Waiting for services to initialize..."
sleep 5

docker compose ps

echo ""
echo "[+] OpsPilot is running at: http://localhost:8000"
echo "[+] Swagger UI at:         http://localhost:8000/docs"
echo "[+] Prometheus at:         http://localhost:9090"
echo "[+] Target payment-api at: http://localhost:8080"
