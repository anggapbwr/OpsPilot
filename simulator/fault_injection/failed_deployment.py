"""Fault injection script: simulate failed deployment."""

import sys

import httpx

TARGET_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"


def main():
    url = f"{TARGET_URL.rstrip('/')}/fault/unhealthy"
    print(f"[*] Simulating failed deployment on: {url}")
    try:
        res = httpx.post(url, timeout=5.0)
        res.raise_for_status()
        print(f"[+] Failed deployment simulated: {res.json()}")
    except Exception as e:
        print(f"[-] Failed to simulate deployment failure: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
