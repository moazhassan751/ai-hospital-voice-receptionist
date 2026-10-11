#!/usr/bin/env python3
"""
setup_telephony.py - Automated Telephony Provisioning for AI Hospital Voice Receptionist.
Supports Vapi phone provisioning and integrations for:
- Scenario 1: Marketplace virtual number (directory and clinic concierge)
- Scenario 2: Vapi Phone Number for Carrier Call Forwarding
- Scenario 3: BYO SIP Trunk for Cloud PBX (3CX, FreePBX, Asterisk, RingCentral)
- Scenario 4: BYOC (Bring Your Own Carrier) with Twilio, Telnyx, or Plivo

Supports --dry-run on every subcommand to preview exact API calls with masked secrets.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

from dotenv import load_dotenv
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Load variables from .env
load_dotenv()

VAPI_BASE_URL = "https://api.vapi.ai"


def mask_secret(secret: Optional[str]) -> str:
    """Masks sensitive credentials to prevent leaking secrets in stdout or logs."""
    if not secret:
        return "<not configured>"
    s = str(secret).strip()
    if len(s) <= 6:
        return "******"
    return f"{s[:2]}****{s[-4:]}"


def get_vapi_headers(api_key: str) -> Dict[str, str]:
    """Builds standard authorization headers for Vapi REST API."""
    return {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json"
    }


def validate_api_key(allow_placeholder: bool = False) -> str:
    """Retrieves and validates VAPI_API_KEY from environment."""
    key = os.getenv("VAPI_API_KEY", "").strip()
    if not key:
        if allow_placeholder:
            return "vapi_test_key_placeholder"
        print("\n[ERROR] Missing 'VAPI_API_KEY' in your .env file.")
        print("Please add your Vapi private API key to .env:")
        print("  VAPI_API_KEY=your_vapi_private_key_here\n")
        print("Get your API key at: https://dashboard.vapi.ai/org")
        sys.exit(1)
    return key


# ==============================================================================
# SUBCOMMAND 1: marketplace-number (Scenario 1: Marketplace Directory Number)
# ==============================================================================
def handle_marketplace_number(args: argparse.Namespace) -> None:
    """Provisions a dedicated virtual number for Scenario 1 Marketplace Concierge."""
    print("=" * 60)
    print("SCENARIO 1: MARKETPLACE VIRTUAL NUMBER SETUP")
    print("=" * 60)

    is_dry_run = getattr(args, "dry_run", False)
    api_key = validate_api_key(allow_placeholder=is_dry_run)
    assistant_id = (args.assistant_id or os.getenv("VAPI_ASSISTANT_ID", "ff49877a-8eb8-4a95-b1b3-8dcf847b706a")).strip()
    area_code = str(args.area_code or 415)

    print(f"[*] Vapi API Key: {mask_secret(api_key)}")
    print(f"[*] Target Assistant ID: {assistant_id or '<none>'}")
    print(f"[*] Desired Area Code: {area_code}")
    print(f"[*] Friendly Name: {args.name}")

    create_payload: Dict[str, Any] = {
        "provider": "vapi",
        "name": args.name or "Marketplace Concierge Number",
        "numberDesiredAreaCode": area_code
    }
    if assistant_id:
        create_payload["assistantId"] = assistant_id

    headers_masked = {
        "Authorization": f"Bearer {mask_secret(api_key)}",
        "Content-Type": "application/json"
    }

    if is_dry_run:
        print("\n[DRY RUN] Simulating Vapi API request (no network call sent):")
        print("------------------------------------------------------------")
        print("Method: POST")
        print(f"URL:    {VAPI_BASE_URL}/phone-number")
        print(f"Headers: {json.dumps(headers_masked, indent=2)}")
        print(f"Body:\n{json.dumps(create_payload, indent=2)}")
        print("------------------------------------------------------------")
        print("Note: The generated phone number cannot be known without a real response from the Vapi API.")
        print_marketplace_instructions("[EXAMPLE NUMBER: +14155550100]")
        return

    headers = get_vapi_headers(api_key)
    print("\n[*] Purchasing marketplace virtual number via Vapi API...")
    try:
        with httpx.Client(timeout=25.0) as client:
            res = client.post(f"{VAPI_BASE_URL}/phone-number", headers=headers, json=create_payload)
            res.raise_for_status()
            data = res.json()
            new_num = data.get("number") or data.get("id")
            print(f"[SUCCESS] Provisioned Marketplace phone number: {new_num}")
            print_marketplace_instructions(new_num)
    except httpx.HTTPStatusError as exc:
        print(f"\n[ERROR] Could not provision marketplace number (HTTP {exc.response.status_code}): {exc.response.text}")
    except Exception as exc:
        print(f"\n[ERROR] Request failed: {str(exc)}")


def print_marketplace_instructions(phone_number: str) -> None:
    """Prints next steps for Scenario 1 Marketplace setup."""
    print("-" * 60)
    print("NEXT STEPS: MARKETPLACE CONCIERGE (SCENARIO 1)")
    print("-" * 60)
    print(f"Branded Directory Number: {phone_number}")
    print("1. In .env, set:")
    print("   DEPLOYMENT_MODE=marketplace")
    print("   CALL_MODE=marketplace")
    print("2. Callers to this number hear:")
    print("   'Welcome to HealthNetwork AI, are you looking for a clinic in a specific area or a specific doctor?'")
    print("3. AI uses the find_clinic tool to search data.json across areas and specialties.")
    print("-" * 60)


# ==============================================================================
# SUBCOMMAND 2: vapi-number (Scenario 2: Forwarding Target)
# ==============================================================================
def handle_vapi_number(args: argparse.Namespace) -> None:
    """Provisions or attaches a Vapi phone number to receive forwarded calls."""
    print("=" * 60)
    print("SCENARIO 2: VAPI PHONE NUMBER SETUP (CALL FORWARDING)")
    print("=" * 60)

    is_dry_run = getattr(args, "dry_run", False)
    api_key = validate_api_key(allow_placeholder=is_dry_run)
    assistant_id = (args.assistant_id or os.getenv("VAPI_ASSISTANT_ID", "")).strip()

    print(f"[*] Vapi API Key: {mask_secret(api_key)}")
    if assistant_id:
        print(f"[*] Target Assistant ID: {assistant_id}")
    else:
        print("[!] Note: VAPI_ASSISTANT_ID is not set in .env. The number will be created without assistant binding.")

    headers_masked = {
        "Authorization": f"Bearer {mask_secret(api_key)}",
        "Content-Type": "application/json"
    }

    # 1. Attach existing number if number_id is provided
    if args.number_id:
        patch_payload: Dict[str, Any] = {}
        if assistant_id:
            patch_payload["assistantId"] = assistant_id
        if args.name:
            patch_payload["name"] = args.name

        if is_dry_run:
            print(f"\n[DRY RUN] Simulating Vapi API request to attach number {args.number_id}:")
            print("------------------------------------------------------------")
            print("Method: PATCH")
            print(f"URL:    {VAPI_BASE_URL}/phone-number/{args.number_id}")
            print(f"Headers: {json.dumps(headers_masked, indent=2)}")
            print(f"Body:\n{json.dumps(patch_payload, indent=2)}")
            print("------------------------------------------------------------")
            print_forwarding_instructions("[EXAMPLE NUMBER: +14155550199]")
            return

        headers = get_vapi_headers(api_key)
        try:
            with httpx.Client(timeout=20.0) as client:
                res = client.patch(
                    f"{VAPI_BASE_URL}/phone-number/{args.number_id}",
                    headers=headers,
                    json=patch_payload
                )
                res.raise_for_status()
                data = res.json()
                phone_num = data.get("number", args.number_id)
                print(f"[SUCCESS] Attached assistant to phone number: {phone_num}")
                print_forwarding_instructions(phone_num)
                return
        except httpx.HTTPStatusError as exc:
            print(f"\n[ERROR] Failed to attach number (HTTP {exc.response.status_code}): {exc.response.text}")
            return
        except Exception as exc:
            print(f"\n[ERROR] Network error: {str(exc)}")
            return

    # 2. Provision new number
    desired_area_code = str(args.area_code) if args.area_code else "415"
    create_payload: Dict[str, Any] = {
        "provider": "vapi",
        "name": args.name or "Clinic AI Receptionist",
        "numberDesiredAreaCode": desired_area_code
    }
    if assistant_id:
        create_payload["assistantId"] = assistant_id

    if is_dry_run:
        print("\n[DRY RUN] Simulating Vapi API request to provision new number:")
        print("------------------------------------------------------------")
        print("Method: POST")
        print(f"URL:    {VAPI_BASE_URL}/phone-number")
        print(f"Headers: {json.dumps(headers_masked, indent=2)}")
        print(f"Body:\n{json.dumps(create_payload, indent=2)}")
        print("------------------------------------------------------------")
        print("Note: The provisioned phone number cannot be known without a real response from the Vapi API.")
        print_forwarding_instructions("[EXAMPLE NUMBER: +14155550199]")
        return

    headers = get_vapi_headers(api_key)
    print("[*] Creating a new Vapi phone number...")
    try:
        with httpx.Client(timeout=25.0) as client:
            res = client.post(f"{VAPI_BASE_URL}/phone-number", headers=headers, json=create_payload)
            res.raise_for_status()
            data = res.json()
            new_num = data.get("number") or data.get("id")
            print(f"[SUCCESS] Provisioned new Vapi phone number: {new_num}")
            print_forwarding_instructions(new_num)
    except httpx.HTTPStatusError as exc:
        print(f"\n[ERROR] Could not provision Vapi phone number (HTTP {exc.response.status_code}): {exc.response.text}")
    except Exception as exc:
        print(f"\n[ERROR] Request failed: {str(exc)}")


def print_forwarding_instructions(target_number: str) -> None:
    """Prints clear call forwarding instructions."""
    print("-" * 60)
    print("NEXT STEPS: CONFIGURE CLINIC CALL FORWARDING (SCENARIO 2)")
    print("-" * 60)
    print(f"Target AI Number: {target_number}\n")
    print("Option A: Overflow Forwarding (Recommended for busy hours)")
    print("  On your existing clinic phone or carrier portal dial:")
    print(f"    *71{target_number}")
    print("  (Forwards calls to the AI after 4 rings or when front desk is busy).")
    print("  Caller hears: 'Thank you for waiting, how can I help you today?'\n")

    print("Option B: After-Hours Forwarding")
    print("  At closing time (5:00 PM), forward clinic phone to this number.")
    print("  Caller hears: 'Hello, our clinic is closed right now, but I can book you an appointment...'")
    print("  At opening time (9:00 AM), turn off forwarding (dial *73 or carrier code).\n")

    print("Option C: 24/7 AI Receptionist (Unconditional Forwarding)")
    print(f"  Dial *72{target_number}")
    print("  All inbound calls route directly to the AI.\n")

    print("In .env: Ensure CALL_MODE=auto (or normal, after_hours, overflow)")
    print("Emergencies in all modes immediately transfer to FRONT_DESK_NUMBER.")
    print("-" * 60)


# ==============================================================================
# SUBCOMMAND 3: sip-trunk (Scenario 3: Cloud PBX 3CX / FreePBX / RingCentral)
# ==============================================================================
def handle_sip_trunk(args: argparse.Namespace) -> None:
    """Sets up a BYO SIP Trunk credential and registers the PBX extension in Vapi."""
    print("=" * 60)
    print("SCENARIO 3: CLOUD PBX / SIP TRUNK SETUP")
    print("=" * 60)

    is_dry_run = getattr(args, "dry_run", False)
    api_key = validate_api_key(allow_placeholder=is_dry_run)
    assistant_id = (args.assistant_id or os.getenv("VAPI_ASSISTANT_ID", "")).strip()

    # Read PBX parameters from CLI or .env
    gateway_ip = (args.host or os.getenv("SIP_GATEWAY_IP", "198.51.100.10")).strip()
    username = (args.username or os.getenv("SIP_AUTH_USERNAME", "")).strip()
    password = (args.password or os.getenv("SIP_AUTH_PASSWORD", "")).strip()
    extension = (args.extension or os.getenv("SIP_EXTENSION", "101")).strip()

    print(f"[*] Vapi API Key: {mask_secret(api_key)}")
    print(f"[*] SIP Gateway IP: {gateway_ip}")
    print(f"[*] SIP Username: {username or '<ip-auth>'}")
    print(f"[*] SIP Password: {mask_secret(password)}")
    print(f"[*] PBX Extension: {extension}")
    if assistant_id:
        print(f"[*] Assistant ID: {assistant_id}")

    cred_payload: Dict[str, Any] = {
        "provider": "byo-sip-trunk",
        "name": args.name or f"Clinic PBX Trunk ({gateway_ip})",
        "gateways": [
            {
                "ip": gateway_ip,
                "inboundEnabled": True
            }
        ]
    }
    if username or password:
        cred_payload["sipAuth"] = {
            "username": username,
            "password": mask_secret(password) if is_dry_run else password
        }

    phone_payload: Dict[str, Any] = {
        "provider": "byo-sip-trunk",
        "credentialId": "cred_mock_pbx_123" if is_dry_run else "<credential_id>",
        "name": f"Extension {extension} (AI Receptionist)",
        "number": f"sip:{extension}@{gateway_ip}"
    }
    if assistant_id:
        phone_payload["assistantId"] = assistant_id

    headers_masked = {
        "Authorization": f"Bearer {mask_secret(api_key)}",
        "Content-Type": "application/json"
    }

    if is_dry_run:
        print("\n[DRY RUN] Simulating Vapi API requests (no network calls sent):")
        print("------------------------------------------------------------")
        print("Request 1: Create SIP Trunk Credential")
        print("Method: POST")
        print(f"URL:    {VAPI_BASE_URL}/credential")
        print(f"Headers: {json.dumps(headers_masked, indent=2)}")
        print(f"Body:\n{json.dumps(cred_payload, indent=2)}")
        print("\nRequest 2: Map PBX Extension to Inbound Trunk")
        print("Method: POST")
        print(f"URL:    {VAPI_BASE_URL}/phone-number")
        print(f"Headers: {json.dumps(headers_masked, indent=2)}")
        print(f"Body:\n{json.dumps(phone_payload, indent=2)}")
        print("------------------------------------------------------------")
        print("Note: The credentialId in Request 2 cannot be known without a real response from Request 1.")
        print_sip_instructions(extension)
        return

    headers = get_vapi_headers(api_key)
    try:
        with httpx.Client(timeout=25.0) as client:
            res_cred = client.post(f"{VAPI_BASE_URL}/credential", headers=headers, json=cred_payload)
            res_cred.raise_for_status()
            cred_id = res_cred.json().get("id")
            print(f"[SUCCESS] Created SIP Trunk Credential ID: {cred_id}")

            phone_payload["credentialId"] = cred_id
            res_phone = client.post(f"{VAPI_BASE_URL}/phone-number", headers=headers, json=phone_payload)
            res_phone.raise_for_status()
            print(f"[SUCCESS] Extension {extension} linked to Vapi Assistant!")
            print_sip_instructions(extension)
    except httpx.HTTPStatusError as exc:
        print(f"\n[ERROR] SIP trunk provisioning failed (HTTP {exc.response.status_code}): {exc.response.text}")
    except Exception as exc:
        print(f"\n[ERROR] Network error: {str(exc)}")


def print_sip_instructions(extension: str) -> None:
    """Prints PBX configuration instructions."""
    print("-" * 60)
    print("NEXT STEPS: CONFIGURE YOUR CLOUD PBX (SCENARIO 3)")
    print("-" * 60)
    print("1. In 3CX, FreePBX, Asterisk, or RingCentral:")
    print("   - Add a Generic SIP Trunk pointing to: sip.vapi.ai (Port: 5060, UDP/TCP)")
    print(f"   - Add Extension {extension} mapped to this SIP trunk.")
    print("2. Call Routing in PBX:")
    print(f"   - Route main line or queue overflow to Extension {extension}.")
    print("3. Front Desk Transfers:")
    print("   - In .env, set FRONT_DESK_NUMBER to your hospital's human front desk extension (e.g. 100).")
    print("   - Emergencies immediately transfer back to this extension.")
    print("-" * 60)


# ==============================================================================
# SUBCOMMAND 4: byoc (Scenario 4: Bring Your Own Carrier - Twilio / Telnyx / Plivo)
# ==============================================================================
def handle_byoc(args: argparse.Namespace) -> None:
    """Attaches an external carrier phone number (Twilio, Telnyx, Plivo) to Vapi."""
    print("=" * 60)
    print("SCENARIO 4: BYOC (BRING YOUR OWN CARRIER) SETUP")
    print("=" * 60)

    is_dry_run = getattr(args, "dry_run", False)
    api_key = validate_api_key(allow_placeholder=is_dry_run)
    assistant_id = (args.assistant_id or os.getenv("VAPI_ASSISTANT_ID", "")).strip()
    provider = (args.provider or "twilio").lower()

    print(f"[*] Vapi API Key: {mask_secret(api_key)}")
    print(f"[*] Telephony Provider: {provider.upper()}")
    if assistant_id:
        print(f"[*] Target Assistant ID: {assistant_id}")

    headers_masked = {
        "Authorization": f"Bearer {mask_secret(api_key)}",
        "Content-Type": "application/json"
    }

    if provider == "twilio":
        account_sid = (args.account_sid or os.getenv("TWILIO_ACCOUNT_SID", "your_twilio_account_sid_here")).strip()
        auth_token = (args.auth_token or os.getenv("TWILIO_AUTH_TOKEN", "twilio_auth_token_secret")).strip()
        phone_number = (args.number or os.getenv("TWILIO_PHONE_NUMBER", "+1234567890")).strip()

        payload_dry: Dict[str, Any] = {
            "provider": "twilio",
            "number": phone_number,
            "twilioAccountSid": mask_secret(account_sid),
            "twilioAuthToken": mask_secret(auth_token),
            "name": args.name or f"Clinic Twilio BYOC ({phone_number})"
        }
        if assistant_id:
            payload_dry["assistantId"] = assistant_id

        if is_dry_run:
            print("\n[DRY RUN] Simulating Twilio BYOC import into Vapi (no network calls sent):")
            print("------------------------------------------------------------")
            print("Method: POST")
            print(f"URL:    {VAPI_BASE_URL}/phone-number")
            print(f"Headers: {json.dumps(headers_masked, indent=2)}")
            print(f"Body:\n{json.dumps(payload_dry, indent=2)}")
            print("------------------------------------------------------------")
            print("Note: The assigned Vapi Phone Number ID cannot be known without a real response from the Vapi API.")
            phone_display = f"[EXAMPLE NUMBER: {phone_number}]" if phone_number in ("+1234567890", "") else phone_number
            print_byoc_instructions("Twilio", phone_display)
            return

        headers = get_vapi_headers(api_key)
        payload = dict(payload_dry)
        payload["twilioAccountSid"] = account_sid
        payload["twilioAuthToken"] = auth_token

        try:
            with httpx.Client(timeout=25.0) as client:
                res = client.post(f"{VAPI_BASE_URL}/phone-number", headers=headers, json=payload)
                res.raise_for_status()
                data = res.json()
                print(f"[SUCCESS] Successfully imported Twilio number: {data.get('number', phone_number)}")
                print_byoc_instructions("Twilio", phone_number)
        except httpx.HTTPStatusError as exc:
            print(f"\n[ERROR] Could not import Twilio number (HTTP {exc.response.status_code}): {exc.response.text}")
        except Exception as exc:
            print(f"\n[ERROR] Network error: {str(exc)}")

    elif provider == "telnyx":
        phone_num = (args.number or os.getenv("TELNYX_PHONE_NUMBER", "")).strip()
        if not phone_num:
            print("\n[ERROR] Missing required phone number for TELNYX BYOC.")
            print("Please provide --number (e.g. --number +14155550188) or set TELNYX_PHONE_NUMBER in .env.")
            sys.exit(1)

        carrier_key = (args.auth_token or os.getenv("TELNYX_API_KEY", "KEY0123456789_placeholder")).strip()

        payload_dry: Dict[str, Any] = {
            "provider": "telnyx",
            "number": phone_num,
            "telnyxApiKey": mask_secret(carrier_key),
            "name": args.name or f"Clinic Telnyx BYOC ({phone_num})"
        }
        if assistant_id:
            payload_dry["assistantId"] = assistant_id

        if is_dry_run:
            print("\n[DRY RUN] Simulating Telnyx BYOC import into Vapi (no network calls sent):")
            print("------------------------------------------------------------")
            print("Method: POST")
            print(f"URL:    {VAPI_BASE_URL}/phone-number")
            print(f"Headers: {json.dumps(headers_masked, indent=2)}")
            print(f"Body:\n{json.dumps(payload_dry, indent=2)}")
            print("------------------------------------------------------------")
            print("Note: The assigned Vapi Phone Number ID cannot be known without a real response from the Vapi API.")
            phone_display = f"[EXAMPLE NUMBER: {phone_num}]" if phone_num in ("+14155550188", "+1234567890") else phone_num
            print_byoc_instructions("Telnyx", phone_display)
            return

        headers = get_vapi_headers(api_key)
        payload = dict(payload_dry)
        payload["telnyxApiKey"] = carrier_key

        try:
            with httpx.Client(timeout=25.0) as client:
                res = client.post(f"{VAPI_BASE_URL}/phone-number", headers=headers, json=payload)
                res.raise_for_status()
                data = res.json()
                print(f"[SUCCESS] Successfully imported Telnyx number: {data.get('number', phone_num)}")
                print_byoc_instructions("Telnyx", phone_num)
        except httpx.HTTPStatusError as exc:
            print(f"\n[ERROR] Could not import Telnyx number (HTTP {exc.response.status_code}): {exc.response.text}")
        except Exception as exc:
            print(f"\n[ERROR] Network error: {str(exc)}")

    elif provider == "plivo":
        phone_num = (args.number or os.getenv("PLIVO_PHONE_NUMBER", "")).strip()
        if not phone_num:
            print("\n[ERROR] Missing required phone number for PLIVO BYOC.")
            print("Please provide --number (e.g. --number +14155550188) or set PLIVO_PHONE_NUMBER in .env.")
            sys.exit(1)

        auth_id = (args.account_sid or os.getenv("PLIVO_AUTH_ID", "MAMOCKAUTHID12345")).strip()
        auth_token = (args.auth_token or os.getenv("PLIVO_AUTH_TOKEN", "plivo_auth_token_mock")).strip()

        payload_dry: Dict[str, Any] = {
            "provider": "byo-phone-number",
            "number": phone_num,
            "name": args.name or f"Clinic Plivo BYOC ({phone_num})",
            "credential": {
                "provider": "plivo",
                "authId": mask_secret(auth_id),
                "authToken": mask_secret(auth_token)
            }
        }
        if assistant_id:
            payload_dry["assistantId"] = assistant_id

        if is_dry_run:
            print("\n[DRY RUN] Simulating Plivo BYOC import into Vapi (no network calls sent):")
            print("------------------------------------------------------------")
            print("Method: POST")
            print(f"URL:    {VAPI_BASE_URL}/phone-number")
            print(f"Headers: {json.dumps(headers_masked, indent=2)}")
            print(f"Body:\n{json.dumps(payload_dry, indent=2)}")
            print("------------------------------------------------------------")
            print("Note: The assigned Vapi Phone Number ID cannot be known without a real response from the Vapi API.")
            phone_display = f"[EXAMPLE NUMBER: {phone_num}]" if phone_num in ("+14155550188", "+1234567890") else phone_num
            print_byoc_instructions("Plivo", phone_display)
            return

        headers = get_vapi_headers(api_key)
        payload = {
            "provider": "byo-phone-number",
            "number": phone_num,
            "name": args.name or f"Clinic Plivo BYOC ({phone_num})",
            "credential": {
                "provider": "plivo",
                "authId": auth_id,
                "authToken": auth_token
            }
        }
        if assistant_id:
            payload["assistantId"] = assistant_id

        try:
            with httpx.Client(timeout=25.0) as client:
                res = client.post(f"{VAPI_BASE_URL}/phone-number", headers=headers, json=payload)
                res.raise_for_status()
                data = res.json()
                print(f"[SUCCESS] Successfully imported Plivo number: {data.get('number', phone_num)}")
                print_byoc_instructions("Plivo", phone_num)
        except httpx.HTTPStatusError as exc:
            print(f"\n[ERROR] Could not import Plivo number (HTTP {exc.response.status_code}): {exc.response.text}")
        except Exception as exc:
            print(f"\n[ERROR] Network error: {str(exc)}")

    else:
        print(f"[ERROR] Unsupported provider: {provider}. Supported options: twilio, telnyx, plivo.")


def print_byoc_instructions(provider_name: str, phone_number: str) -> None:
    """Prints clear next steps for BYOC scenario."""
    print("-" * 60)
    print(f"NEXT STEPS: {provider_name} BYOC (SCENARIO 4)")
    print("-" * 60)
    print(f"1. Your clinic keeps its existing {provider_name} carrier relationship & billing.")
    print(f"2. Inbound calls to {phone_number} are now automatically bridged to your AI assistant.")
    print("3. How to test:")
    print(f"   - Place a phone call to {phone_number} from any mobile phone.")
    print("   - Verify the AI greets you and checks Doctor Steve or Nurse Maha availability.")
    print("4. Emergencies transfer to FRONT_DESK_NUMBER configured in .env.")
    print("-" * 60)


def handle_sync_assistant(args: argparse.Namespace) -> None:
    """Synchronizes assistant configuration, system prompt, multilingual standards, and tools directly to Vapi dashboard."""
    print("=" * 60)
    print("VAPI DASHBOARD ASSISTANT SYNCHRONIZATION")
    print("=" * 60)

    is_dry_run = getattr(args, "dry_run", False)
    api_key = validate_api_key(allow_placeholder=is_dry_run)
    assistant_id = (args.assistant_id or os.getenv("VAPI_ASSISTANT_ID", "")).strip()

    if not assistant_id:
        print("[ERROR] Missing VAPI_ASSISTANT_ID in .env or --assistant-id flag.")
        sys.exit(1)

    config_path = args.config or "assistant_config.rendered.json"
    if not os.path.exists(config_path):
        print(f"[*] '{config_path}' not found, rendering from template...")
        from render_config import render_config
        render_config()

    with open(config_path, "r", encoding="utf-8") as f:
        rendered_cfg = json.load(f)

    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
    front_desk = os.getenv("FRONT_DESK_NUMBER", "+923007903061").strip()

    system_prompt = ""
    messages = rendered_cfg.get("model", {}).get("messages", [])
    if messages and isinstance(messages, list) and len(messages) > 0 and "content" in messages[0]:
        system_prompt = messages[0]["content"]
    elif "systemPrompt" in rendered_cfg.get("model", {}):
        system_prompt = rendered_cfg["model"]["systemPrompt"]

    patch_payload: Dict[str, Any] = {
        "name": rendered_cfg.get("name", "Hospital AI Voice Receptionist"),
        "firstMessage": rendered_cfg.get("firstMessage", "Hello! How can I help you today?"),
        "firstMessageMode": rendered_cfg.get("firstMessageMode", "assistant-speaks-first"),
        "transcriber": rendered_cfg.get("transcriber", {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "multi"
        }),
        "voice": rendered_cfg.get("voice", {
            "provider": "11labs",
            "voiceId": "21m00Tcm4TlvDq8ikWAM",
            "model": "eleven_turbo_v2_5"
        }),
        "model": {
            "provider": rendered_cfg.get("model", {}).get("provider", "openai"),
            "model": rendered_cfg.get("model", {}).get("model", "gpt-4o"),
            "temperature": rendered_cfg.get("model", {}).get("temperature", 0.2),
            "systemPrompt": system_prompt,
            "messages": messages,
            "tools": rendered_cfg.get("model", {}).get("tools", [])
        },
        "server": {
            "url": f"{public_base_url}/webhook",
            "timeoutSeconds": 20,
            "headers": {
                "x-vapi-secret": webhook_secret
            }
        }
    }

    print(f"[*] Target Assistant ID: {assistant_id}")
    print(f"[*] Multilingual Support: Urdu, English, French, Spanish, Arabic")
    print(f"[*] Medical Providers: Doctor Steve & Nurse Maha")
    print(f"[*] Voice Provider: {patch_payload['voice']['provider']} ({patch_payload['voice'].get('model', 'eleven_turbo_v2_5')})")
    print(f"[*] Transcriber: {patch_payload['transcriber']['provider']} ({patch_payload['transcriber']['model']}, language: {patch_payload['transcriber']['language']})")
    print(f"[*] Webhook Server URL: {patch_payload['server']['url']}")
    print(f"[*] Emergency Forwarding: {front_desk}")

    if is_dry_run:
        print("\n[DRY RUN] Simulating Vapi API PATCH request (no network call sent):")
        print("------------------------------------------------------------")
        print("Method: PATCH")
        print(f"URL:    {VAPI_BASE_URL}/assistant/{assistant_id}")
        masked_headers = {"Authorization": f"Bearer {mask_secret(api_key)}", "Content-Type": "application/json"}
        print(f"Headers: {json.dumps(masked_headers, indent=2)}")
        print(f"Body keys: {list(patch_payload.keys())}")
        print("------------------------------------------------------------")
        print("[DRY RUN SUCCESS] Assistant update preview completed.")
        return

    print("\n[*] Sending PATCH request to Vapi API...")
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.patch(
                f"{VAPI_BASE_URL}/assistant/{assistant_id}",
                headers=get_vapi_headers(api_key),
                json=patch_payload
            )
            if resp.status_code == 200:
                resp_data = resp.json()
                print("\n" + "=" * 60)
                print("[SUCCESS] VAPI DASHBOARD ASSISTANT UPDATED SUCCESSFULLY!")
                print("=" * 60)
                print(f"Assistant ID:   {resp_data.get('id')}")
                print(f"Name:           {resp_data.get('name')}")
                print(f"Updated At:     {resp_data.get('updatedAt')}")
                print(f"First Message:  {resp_data.get('firstMessage')}")
                print(f"Model:          {resp_data.get('model', {}).get('model')}")
                print(f"Language Mode:  {resp_data.get('transcriber', {}).get('language')}")
                print("\nYour Vapi Assistant is now live and updated with:")
                print("  [OK] Full Multilingual Support (Urdu, English, French, Spanish, Arabic)")
                print("  [OK] Nurse Maha & Doctor Steve clinical scopes")
                print("  [OK] Up-to-date system prompt & live webhooks")
                print("=" * 60)
            else:
                print(f"\n[ERROR] Vapi API returned HTTP {resp.status_code}:")
                try:
                    print(json.dumps(resp.json(), indent=2))
                except Exception:
                    print(resp.text)
                sys.exit(1)
    except Exception as exc:
        print(f"\n[ERROR] Network error during Vapi assistant update: {exc}")
        sys.exit(1)


# ==============================================================================
# MAIN CLI ENTRY POINT
# ==============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Telephony Provisioning Tool for AI Hospital Voice Receptionist (Vapi/Retell).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python setup_telephony.py sync-assistant
  python setup_telephony.py sync-assistant --dry-run
  python setup_telephony.py marketplace-number --dry-run
  python setup_telephony.py vapi-number --dry-run
  python setup_telephony.py sip-trunk --dry-run
  python setup_telephony.py byoc --provider twilio --dry-run
  python setup_telephony.py byoc --provider telnyx --number +14155550188 --dry-run
  python setup_telephony.py byoc --provider plivo --number +14155550188 --dry-run
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="Telephony scenario command")

    # Subcommand: sync-assistant (Synchronize assistant to Vapi dashboard)
    parser_sync = subparsers.add_parser("sync-assistant", help="Sync assistant config, prompt, and tools to Vapi dashboard")
    parser_sync.add_argument("--assistant-id", default=None, help="Vapi Assistant ID (defaults to VAPI_ASSISTANT_ID from .env)")
    parser_sync.add_argument("--config", default="assistant_config.rendered.json", help="Path to rendered assistant config JSON")
    parser_sync.add_argument("--dry-run", action="store_true", help="Print exact API call with masked secrets and send nothing")

    # Subcommand: marketplace-number (Scenario 1)
    parser_market = subparsers.add_parser("marketplace-number", help="Set up virtual number for multi-clinic network (Scenario 1)")
    parser_market.add_argument("--name", default="Marketplace Concierge Number", help="Friendly name for the phone number")
    parser_market.add_argument("--assistant-id", default=None, help="Vapi Assistant ID")
    parser_market.add_argument("--area-code", type=int, default=415, help="US Area code for number provisioning")
    parser_market.add_argument("--dry-run", action="store_true", help="Print exact API call with masked secrets and send nothing")

    # Subcommand: vapi-number (Scenario 2)
    parser_vapi = subparsers.add_parser("vapi-number", help="Create or attach a Vapi phone number (Scenario 2 Call Forwarding)")
    parser_vapi.add_argument("--name", default="Clinic AI Receptionist", help="Friendly name for the phone number")
    parser_vapi.add_argument("--assistant-id", default=None, help="Vapi Assistant ID (defaults to VAPI_ASSISTANT_ID from .env)")
    parser_vapi.add_argument("--area-code", type=int, default=None, help="US Area code for number provisioning")
    parser_vapi.add_argument("--number-id", default=None, help="ID of an existing Vapi number to attach")
    parser_vapi.add_argument("--dry-run", action="store_true", help="Print exact API call with masked secrets and send nothing")

    # Subcommand: sip-trunk (Scenario 3)
    parser_sip = subparsers.add_parser("sip-trunk", help="Set up SIP trunk & extension for Cloud PBX (Scenario 3)")
    parser_sip.add_argument("--host", default=None, help="PBX Gateway IP or host (defaults to SIP_GATEWAY_IP from .env)")
    parser_sip.add_argument("--username", default=None, help="SIP Auth Username (defaults to SIP_AUTH_USERNAME from .env)")
    parser_sip.add_argument("--password", default=None, help="SIP Auth Password (defaults to SIP_AUTH_PASSWORD from .env)")
    parser_sip.add_argument("--extension", default=None, help="PBX Extension (defaults to SIP_EXTENSION from .env or 101)")
    parser_sip.add_argument("--assistant-id", default=None, help="Vapi Assistant ID (defaults to VAPI_ASSISTANT_ID from .env)")
    parser_sip.add_argument("--name", default="Clinic PBX Trunk", help="Trunk display name in Vapi")
    parser_sip.add_argument("--dry-run", action="store_true", help="Print exact API call with masked secrets and send nothing")

    # Subcommand: byoc (Scenario 4)
    parser_byoc = subparsers.add_parser("byoc", help="Attach Twilio, Telnyx, or Plivo BYOC number (Scenario 4)")
    parser_byoc.add_argument("--provider", default="twilio", choices=["twilio", "telnyx", "plivo"], help="Telephony provider")
    parser_byoc.add_argument("--account-sid", default=None, help="Twilio/Plivo Account SID/Auth ID")
    parser_byoc.add_argument("--auth-token", default=None, help="Carrier Auth Token / API Key")
    parser_byoc.add_argument("--number", default=None, help="Carrier phone number in E.164 format (+1...)")
    parser_byoc.add_argument("--assistant-id", default=None, help="Vapi Assistant ID (defaults to VAPI_ASSISTANT_ID from .env)")
    parser_byoc.add_argument("--name", default=None, help="Display name for imported number")
    parser_byoc.add_argument("--dry-run", action="store_true", help="Print exact API call with masked secrets and send nothing")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "sync-assistant":
        handle_sync_assistant(args)
    elif args.command == "marketplace-number":
        handle_marketplace_number(args)
    elif args.command == "vapi-number":
        handle_vapi_number(args)
    elif args.command == "sip-trunk":
        handle_sip_trunk(args)
    elif args.command == "byoc":
        handle_byoc(args)


if __name__ == "__main__":
    main()
