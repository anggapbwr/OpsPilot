"""Fault injection script: simulate service crash or stop."""

import sys

import httpx

TARGET_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"


def main():
    url = f"{TARGET_URL.rstrip('/')}/fault/crash"
    print(f"[*] Stopping target service at: {url}")
    try:
        httpx.post(url, timeout=2.0)
    except (httpx.ConnectError, httpx.RemoteProtocolError):
        print("[+] Service stopped/crashed as expected.")
    except Exception as e:
        print(f"[*] Sent crash signal: {e}")


if __name__ == "__main__":
    main()
