"""
stedi_client.py - Stedi Healthcare Eligibility Verification (Test Mode Only)

Provides mock eligibility checks against Stedi test mode endpoints.
Never sends real patient data. Requires a test API key (STEDI_TEST_API_KEY).
Refuses execution if the key is missing or resembles a production key.
"""

import os
import re
from typing import Any, Dict, Optional, Tuple
from dotenv import load_dotenv
import httpx

load_dotenv()

# Official Stedi Test Mode Eligibility Check Endpoint
STEDI_ELIGIBILITY_URL = "https://healthcare.us.stedi.com/2026-06-01/eligibility-check"

# Supported Mock Payers mapped to their official Stedi Payer IDs
SUPPORTED_PAYERS: Dict[str, Dict[str, str]] = {
    "aetna": {
        "payer_id": "60054",
        "display_name": "Aetna"
    },
    "cigna": {
        "payer_id": "62308",
        "display_name": "Cigna"
    },
    "unitedhealthcare": {
        "payer_id": "87726",
        "display_name": "UnitedHealthcare"
    },
    "uhc": {
        "payer_id": "87726",
        "display_name": "UnitedHealthcare"
    },
    "united healthcare": {
        "payer_id": "87726",
        "display_name": "UnitedHealthcare"
    },
    "cms": {
        "payer_id": "CMS",
        "display_name": "Medicare (CMS)"
    },
    "medicare": {
        "payer_id": "CMS",
        "display_name": "Medicare (CMS)"
    }
}


def mask_member_id(member_id: Optional[str]) -> str:
    """Masks all characters of a member ID except the last 4 characters."""
    if not member_id:
        return "<none>"
    cleaned = str(member_id).strip()
    if len(cleaned) <= 4:
        return "****"
    return f"{'*' * (len(cleaned) - 4)}{cleaned[-4:]}"


def validate_test_api_key(api_key: Optional[str]) -> str:
    """
    Validates that a test API key is provided and is not a production key.
    Raises ValueError if missing or invalid.
    """
    if not api_key:
        raise ValueError("STEDI_TEST_API_KEY is missing. Please set STEDI_TEST_API_KEY in your .env file.")
    key = api_key.strip()
    if not key:
        raise ValueError("STEDI_TEST_API_KEY is empty. Please set STEDI_TEST_API_KEY in your .env file.")

    # Guardrail: refuse to run if the key indicates production use
    key_lower = key.lower()
    if key_lower.startswith("prod_") or key_lower.startswith("live_") or "production" in key_lower:
        raise ValueError(
            "STEDI_TEST_API_KEY appears to be a production key. "
            "Only test keys are permitted for mock eligibility checks."
        )
    return key


def normalize_payer(payer_name: str) -> Optional[Tuple[str, str]]:
    """
    Normalizes user-supplied payer name and returns (payer_id, display_name).
    Returns None if the payer is not supported.
    """
    if not payer_name:
        return None
    cleaned = payer_name.strip().lower()
    for key, info in SUPPORTED_PAYERS.items():
        if key == cleaned or key in cleaned or cleaned in key:
            return info["payer_id"], info["display_name"]
    return None


def split_patient_name(full_name: str) -> Tuple[str, str]:
    """Splits full name into (first_name, last_name)."""
    parts = (full_name or "").strip().split()
    if not parts:
        return "Patient", "Name"
    if len(parts) == 1:
        return parts[0], "Patient"
    return parts[0], " ".join(parts[1:])


def check_eligibility_mock(
    payer: str,
    member_id: str,
    patient_name: str,
    date_of_birth: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout_seconds: float = 8.0,
    client: Optional[httpx.Client] = None
) -> Dict[str, Any]:
    """
    Executes a mock eligibility check against Stedi test mode.
    Returns a dictionary with status, voice-friendly message, and benefit details.
    """
    effective_key = api_key or os.getenv("STEDI_TEST_API_KEY", "")
    masked_id = mask_member_id(member_id)

    # 1. Validate API Key
    try:
        validated_key = validate_test_api_key(effective_key)
    except ValueError as val_err:
        return {
            "status": "bad_key",
            "payer": payer,
            "masked_member_id": masked_id,
            "message": (
                "I am having trouble checking your insurance right now. "
                "Let me connect you directly to our front desk so they can verify your coverage."
            ),
            "detail": str(val_err)
        }

    # 2. Normalize and validate Payer
    payer_info = normalize_payer(payer)
    if not payer_info:
        return {
            "status": "unsupported_payer",
            "payer": payer,
            "masked_member_id": masked_id,
            "message": (
                "We currently only support automated checks for Aetna, Cigna, UnitedHealthcare, and Medicare in test mode. "
                "Let me connect you with our front desk to verify your coverage manually."
            )
        }

    payer_id, display_name = payer_info
    first_name, last_name = split_patient_name(patient_name)

    # 3. Build Stedi mock JSON request payload
    request_payload: Dict[str, Any] = {
        "payerId": payer_id,
        "provider": {
            "npi": "1999999984",
            "name": {
                "organization": "Hospital Receptionist Clinic"
            }
        },
        "subscriber": {
            "memberId": member_id.strip(),
            "name": {
                "person": {
                    "firstName": first_name,
                    "lastName": last_name
                }
            }
        }
    }

    if date_of_birth:
        request_payload["subscriber"]["dateOfBirth"] = date_of_birth

    # Stedi Sandbox Mock Scenarios:
    # In Stedi test mode, the preconfigured Aetna mock profile (AETNA9wcSu) requires
    # the dependent patient record (Jordan Doe, DOB 2001-07-14) to return active coverage.
    if member_id.strip() == "AETNA9wcSu":
        request_payload["dependent"] = {
            "name": {
                "person": {
                    "firstName": "Jordan",
                    "lastName": last_name or "Doe"
                }
            },
            "dateOfBirth": "2001-07-14"
        }

    headers = {
        "Authorization": validated_key,
        "Content-Type": "application/json"
    }

    # 4. Dispatch HTTP request to Stedi
    try:
        if client:
            resp = client.post(
                STEDI_ELIGIBILITY_URL,
                headers=headers,
                json=request_payload,
                timeout=timeout_seconds
            )
        else:
            with httpx.Client(timeout=timeout_seconds) as default_client:
                resp = default_client.post(
                    STEDI_ELIGIBILITY_URL,
                    headers=headers,
                    json=request_payload
                )

        if resp.status_code == 200:
            data = resp.json()
            return parse_stedi_response(data, display_name, masked_id)

        elif resp.status_code in (401, 403):
            return {
                "status": "bad_key",
                "payer": display_name,
                "masked_member_id": masked_id,
                "message": (
                    "I am having trouble validating your insurance details with our verification system. "
                    "Let me connect you directly to our front desk for assistance."
                )
            }

        elif resp.status_code in (400, 422):
            err_data = {}
            try:
                err_data = resp.json()
            except Exception:
                pass
            return parse_stedi_error(err_data, display_name, masked_id)

        else:
            return {
                "status": "error",
                "payer": display_name,
                "masked_member_id": masked_id,
                "message": (
                    "I am having trouble checking your insurance right now. "
                    "Let me connect you directly to our front desk so they can verify your coverage."
                )
            }

    except (httpx.TimeoutException, httpx.ConnectTimeout):
        return {
            "status": "timeout",
            "payer": display_name,
            "masked_member_id": masked_id,
            "message": (
                "I am having trouble reaching the insurance verification service right now. "
                "Let me connect you directly to our front desk so they can check your coverage."
            )
        }
    except Exception as exc:
        return {
            "status": "error",
            "payer": display_name,
            "masked_member_id": masked_id,
            "message": (
                "I am having trouble checking your insurance right now. "
                "Let me connect you directly to our front desk so they can verify your coverage."
            ),
            "detail": str(exc)
        }


def parse_stedi_response(data: Dict[str, Any], display_name: str, masked_id: str) -> Dict[str, Any]:
    """Parses successful Stedi 200 JSON eligibility response into natural voice response."""
    # Check if subscriber not found AAA code or error is present in response body
    aaa_list = data.get("aaa") or data.get("errors") or []
    for item in aaa_list:
        code = str(item.get("rejectReasonCode") or item.get("code") or "")
        msg = str(item.get("followupAction") or item.get("message") or "")
        if code in ("71", "72", "73", "75") or "not found" in msg.lower() or "not match" in msg.lower():
            return {
                "status": "not_found",
                "payer": display_name,
                "masked_member_id": masked_id,
                "message": (
                    f"I could not verify that member ID with {display_name}. "
                    "Let me connect you with our front desk to help confirm your details."
                )
            }

    plans = data.get("plans") or []
    if not plans and "benefitsInformation" not in data:
        return {
            "status": "not_found",
            "payer": display_name,
            "masked_member_id": masked_id,
            "message": (
                f"I could not locate active eligibility records for that member ID with {display_name}. "
                "Let me connect you with our front desk to confirm."
            )
        }

    # Evaluate active coverage status
    is_active = False
    copay_amount: Optional[float] = None
    deductible_amount: Optional[float] = None

    # Redesigned plans structure
    if plans:
        first_plan = plans[0]
        benefits = first_plan.get("benefits", {})
        statuses = benefits.get("statuses", [])
        for st in statuses:
            st_val = str(st.get("status", "")).upper()
            if st_val in ("ACTIVE_COVERAGE", "1", "ACTIVE"):
                is_active = True
                break

        # Check copayment
        copays = benefits.get("coPayment") or []
        for cp in copays:
            amt = cp.get("amount") or cp.get("monetaryAmount")
            if amt is not None:
                try:
                    copay_amount = float(amt)
                    break
                except (ValueError, TypeError):
                    pass

        # Check deductible
        deductibles = benefits.get("deductible") or []
        for ded in deductibles:
            amt = ded.get("amount") or ded.get("monetaryAmount")
            if amt is not None:
                try:
                    deductible_amount = float(amt)
                    break
                except (ValueError, TypeError):
                    pass

    # Legacy benefitsInformation structure fallback
    benefits_info = data.get("benefitsInformation") or []
    if benefits_info:
        for b in benefits_info:
            code = str(b.get("code", "")).upper()
            if code == "1":
                is_active = True
            elif code == "B" and copay_amount is None:
                try:
                    copay_amount = float(b.get("monetaryAmount") or b.get("amount"))
                except (ValueError, TypeError):
                    pass
            elif code == "C" and deductible_amount is None:
                try:
                    deductible_amount = float(b.get("monetaryAmount") or b.get("amount"))
                except (ValueError, TypeError):
                    pass

    if not is_active:
        return {
            "status": "inactive",
            "payer": display_name,
            "masked_member_id": masked_id,
            "copay": copay_amount,
            "deductible": deductible_amount,
            "message": (
                f"Your coverage with {display_name} appears inactive. "
                "Would you like me to connect you with our front desk to review options?"
            )
        }

    # Format voice-friendly spoken text
    copay_str = f"${int(copay_amount)}" if (copay_amount is not None and copay_amount.is_integer()) else (f"${copay_amount:.2f}" if copay_amount is not None else None)
    ded_str = f"${int(deductible_amount)}" if (deductible_amount is not None and deductible_amount.is_integer()) else (f"${deductible_amount:.2f}" if deductible_amount is not None else None)

    if copay_str and ded_str:
        voice_msg = (
            f"Your coverage with {display_name} is active. "
            f"Your copay is {copay_str} and your remaining deductible is {ded_str}."
        )
    elif copay_str:
        voice_msg = (
            f"Your coverage with {display_name} is active. "
            f"Your copay is {copay_str}."
        )
    elif ded_str:
        voice_msg = (
            f"Your coverage with {display_name} is active. "
            f"Your remaining deductible is {ded_str}."
        )
    else:
        voice_msg = (
            f"Your coverage with {display_name} is active. "
            "Would you like me to go ahead and book your appointment?"
        )

    return {
        "status": "active",
        "payer": display_name,
        "masked_member_id": masked_id,
        "copay": copay_amount,
        "deductible": deductible_amount,
        "message": voice_msg
    }


def parse_stedi_error(err_data: Dict[str, Any], display_name: str, masked_id: str) -> Dict[str, Any]:
    """Parses error bodies returned by Stedi."""
    err_text = str(err_data).lower()
    if "71" in err_text or "72" in err_text or "73" in err_text or "75" in err_text or "not found" in err_text or "subscriber" in err_text:
        return {
            "status": "not_found",
            "payer": display_name,
            "masked_member_id": masked_id,
            "message": (
                f"I could not verify that member ID with {display_name}. "
                "Let me connect you with our front desk to help confirm your details."
            )
        }
    return {
        "status": "error",
        "payer": display_name,
        "masked_member_id": masked_id,
        "message": (
            "I am having trouble checking your insurance right now. "
            "Let me connect you directly to our front desk so they can verify your coverage."
        )
    }
