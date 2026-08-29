#!/usr/bin/env python
"""Eagle Financial Reconciliation Engine — Reviewer Demo Launcher.

Starts the FastAPI server, validates dependencies and AI provider availability,
and launches the interactive Web Dashboard in the user's default browser.
"""

import argparse
import os
import socket
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

import httpx
import uvicorn
from eagle.core.config import settings


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check whether a local TCP port is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def check_llama_server(url: str) -> tuple[bool, str]:
    """Check if the external llama-server HTTP service is responding."""
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(f"{url.rstrip('/')}/health")
            if resp.status_code == 200:
                return True, "Online (200 OK)"
            return False, f"HTTP Status {resp.status_code}"
    except Exception as e:
        return False, str(e)


def resolve_ports(preferred_port: int, llama_url: str) -> int:
    """Resolve port collisions between Eagle and llama-server."""
    parsed_llama = urllib.parse.urlparse(llama_url)
    llama_port = parsed_llama.port or 8000

    target_port = preferred_port
    if target_port == llama_port:
        # Avoid colliding with llama-server
        target_port = 8080 if llama_port == 8000 else 8000

    # If target port is already in use by another process, find next available port
    while is_port_in_use(target_port):
        print(f"[INFO] Port {target_port} is already in use, trying {target_port + 1}...")
        target_port += 1

    return target_port


def main():
    parser = argparse.ArgumentParser(
        description="Eagle AI Financial Reconciliation Controller — Demo Launcher"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser")
    parser.add_argument("--provider", choices=["mock", "llama_server", "gemini", "claude"], help="Override AI provider")
    args = parser.parse_args()

    if args.provider:
        os.environ["AI_PROVIDER"] = args.provider
        settings.AI_PROVIDER = args.provider

    ai_provider = settings.AI_PROVIDER
    llama_url = settings.LLAMA_SERVER_URL
    port = resolve_ports(args.port, llama_url)
    host = args.host
    base_url = f"http://{host}:{port}"

    print("\n" + "=" * 75)
    print("  🦅  EAGLE — AI FINANCIAL RECONCILIATION CONTROLLER")
    print("=" * 75)
    print(f"  Eagle API & UI Port:  {port}")
    print(f"  Dashboard URL:        {base_url}/")
    print(f"  API Docs (Swagger):   {base_url}/docs")
    print(f"  Active AI Provider:   {ai_provider}")

    if ai_provider == "llama_server":
        print(f"  LLM Server Target:    {llama_url}")
        is_online, status_msg = check_llama_server(llama_url)
        if is_online:
            print(f"  LLM Server Status:    ✅ {status_msg}")
        else:
            print(f"  LLM Server Status:    ⚠️  {status_msg}")
            print("\n  [NOTICE] llama-server is currently unreachable.")
            print(f"  To use local LLM reasoning, start llama-server externally:")
            print(f'      llama-server.exe -m "<path_to_model.gguf>" --port {urllib.parse.urlparse(llama_url).port or 8000}')
            print("  Alternatively, set AI_PROVIDER=mock in .env for 100% offline deterministic execution.")
    elif ai_provider == "mock":
        print("  LLM Mode:             Deterministic Offline MockProvider (Zero external dependencies)")
    print("=" * 75)
    print("\nStarting Eagle application server...")

    if not args.no_browser:
        # Schedule opening browser once server starts
        import threading
        def open_browser():
            # Poll health endpoint until server is ready
            health_url = f"{base_url}/health"
            for _ in range(30):
                time.sleep(0.3)
                try:
                    with httpx.Client(timeout=1.0) as client:
                        r = client.get(health_url)
                        if r.status_code == 200:
                            print(f"\n[READY] Server is live! Opening browser at {base_url}/")
                            webbrowser.open(base_url)
                            return
                except Exception:
                    pass
            print(f"\n[INFO] Please open {base_url}/ in your browser.")

        threading.Thread(target=open_browser, daemon=True).start()

    # Run uvicorn server
    uvicorn.run(
        "eagle.api.main:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
