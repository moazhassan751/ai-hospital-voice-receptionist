#!/usr/bin/env python3
"""
render_config.py - Render Assistant Configuration Template

Reads assistant_config.json and writes assistant_config.rendered.json
by substituting PUBLIC_BASE_URL and WEBHOOK_SECRET from your .env file.

Usage:
    python render_config.py
"""

import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()

TEMPLATE_FILE = "assistant_config.json"
OUTPUT_FILE = "assistant_config.rendered.json"


def render_config() -> None:
    """Renders assistant_config.json template with .env values."""
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
    front_desk_number = os.getenv("FRONT_DESK_NUMBER", "+1234567890").strip()

    if not public_base_url:
        print("[WARNING] PUBLIC_BASE_URL is not set in .env. Using fallback 'http://localhost:3000'.")
        public_base_url = "http://localhost:3000"

    if not webhook_secret:
        print("[WARNING] WEBHOOK_SECRET is not set in .env. Using default 'hospital_secret_123'.")
        webhook_secret = "hospital_secret_123"

    if not os.path.exists(TEMPLATE_FILE):
        print(f"[ERROR] Template file '{TEMPLATE_FILE}' does not exist.")
        sys.exit(1)

    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    rendered = content.replace("{{PUBLIC_BASE_URL}}", public_base_url)
    rendered = rendered.replace("{{WEBHOOK_SECRET}}", webhook_secret)
    rendered = rendered.replace("{{FRONT_DESK_NUMBER}}", front_desk_number)

    # Validate JSON syntax
    try:
        json_obj = json.loads(rendered)
    except json.JSONDecodeError as err:
        print(f"[ERROR] Rendered output is not valid JSON: {err}")
        sys.exit(1)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(json_obj, f, indent=2)

    masked_secret = f"{webhook_secret[:2]}****{webhook_secret[-4:]}" if len(webhook_secret) > 6 else "****"
    print(f"[SUCCESS] Wrote '{OUTPUT_FILE}' successfully.")
    print(f"  Target Public Base URL: {public_base_url}")
    print(f"  Target Webhook Secret:  {masked_secret}")


if __name__ == "__main__":
    render_config()
