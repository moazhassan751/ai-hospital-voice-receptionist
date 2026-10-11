"""
AI Hospital Voice Receptionist - FastAPI Webhook Backend
Handles Vapi and Retell tool-call webhooks for checking doctor/nurse availability,
booking appointments, clinic marketplace search, warm transfers, dynamic greetings,
and Stedi insurance eligibility verification in test mode.
Supports 4 Telephony Call Modes: auto, normal, after_hours, overflow, and marketplace.
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import httpx
from pydantic import BaseModel

# Load environment variables from .env
load_dotenv()

# ==============================================================================
# LOGGING CONFIGURATION
# ==============================================================================
logger = logging.getLogger("hospital_voice_agent")
logger.setLevel(logging.INFO)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    log_format = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

# ==============================================================================
# CONFIGURATION (Easily configured via .env)
# ==============================================================================
TIMEZONE_STR = os.getenv("TIMEZONE", "Asia/Karachi")
CLINIC_TZ = ZoneInfo(TIMEZONE_STR)

# Mode configurations:
# BACKEND_MODE: 'local' (JSON storage) or 'mock' (HTTP forwards to MOCK_URL)
BACKEND_MODE = os.getenv("BACKEND_MODE", "local").lower()
MOCK_URL = os.getenv("MOCK_URL", "http://localhost:3001").rstrip("/")

# DEPLOYMENT_MODE: 'single_hospital' or 'marketplace'
DEPLOYMENT_MODE = os.getenv("DEPLOYMENT_MODE", "single_hospital").lower()

# CALL_MODE: 'auto', 'normal', 'after_hours', 'overflow', 'marketplace' (Default: auto)
CALL_MODE = os.getenv("CALL_MODE", "auto").lower()

# Working hours: Monday (0) to Saturday (5). Sunday (6) is closed.
WORKING_DAYS = [0, 1, 2, 3, 4, 5]
START_HOUR = 9      # 9:00 AM
END_HOUR = 17       # 5:00 PM (17:00)
SLOT_MINUTES = 30   # 30-minute appointments

# Authorized medical providers and their scopes
VALID_PROVIDERS = {
    "Doctor Steve": "consultations, check-ups, new problems, and follow-ups",
    "Nurse Maha": "routine care, blood pressure checks, injections, dressing changes, and vaccinations"
}

DATA_FILE = "data.json"
APPOINTMENTS_FILE = "appointments.json"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
FRONT_DESK_NUMBER = os.getenv("FRONT_DESK_NUMBER", "+1234567890")


def get_webhook_secret() -> str:
    """Returns the configured webhook secret from environment or module setting."""
    return os.getenv("WEBHOOK_SECRET", WEBHOOK_SECRET)


def print_startup_warnings() -> None:
    """
    Checks for default or missing placeholder configuration and prints clear warnings.
    """
    if FRONT_DESK_NUMBER in ("+1234567890", "1234567890", ""):
        print("[WARNING] FRONT_DESK_NUMBER is still set to the placeholder (+1234567890).")
        print("          Urgent and emergency transfers will fail on live calls until updated in .env.")
    if not WEBHOOK_SECRET:
        print("[WARNING] WEBHOOK_SECRET is empty.")
        print("          Please set a secret in .env before exposing webhooks to public traffic.")
    elif WEBHOOK_SECRET == "hospital_secret_123":
        print("[WARNING] WEBHOOK_SECRET is set to the default placeholder ('hospital_secret_123').")
        print("          Please set a unique secret before exposing webhooks to public traffic.")


# Initialize FastAPI application
app = FastAPI(
    title="Hospital Voice Receptionist Webhook",
    description="Webhook backend for Vapi & Retell Voice Receptionist with slot checking, booking, marketplace, mock mode, and telephony call modes.",
    version="2.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_app_startup():
    """Runs configuration checks when server starts up."""
    print_startup_warnings()


# ==============================================================================
# MASKING & LOGGING HELPERS
# ==============================================================================
def mask_phone_number(phone: Optional[str]) -> str:
    """Masks all characters of a phone number except the last 4 digits."""
    if not phone:
        return "<none>"
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) <= 4:
        return "****"
    return f"***-***-{digits[-4:]}"


def mask_member_id(member_id: Optional[str]) -> str:
    """Masks all characters of a member ID except the last 4 characters."""
    if not member_id:
        return "<none>"
    s = str(member_id).strip()
    if len(s) <= 4:
        return "****"
    return f"{'*' * (len(s) - 4)}{s[-4:]}"


def mask_args_for_logging(args: Dict[str, Any]) -> Dict[str, Any]:
    """Masks phone numbers and insurance member IDs in tool argument dictionaries."""
    if not isinstance(args, dict):
        return args
    masked = dict(args)
    if "phone" in masked and masked["phone"]:
        masked["phone"] = mask_phone_number(str(masked["phone"]))
    if "member_id" in masked and masked["member_id"]:
        masked["member_id"] = mask_member_id(str(masked["member_id"]))
    return masked


def get_scenario_label(active_mode: str, payload: Optional[Dict[str, Any]] = None) -> str:
    """
    Resolves a human-readable label for the telephony scenario.
    Detects custom scenario tags, SIP headers, or BYOC provider attributes.
    """
    if payload:
        call_obj = payload.get("call") or payload.get("message", {}).get("call") or {}
        custom_scenario = (
            call_obj.get("scenario")
            or payload.get("scenario")
            or call_obj.get("metadata", {}).get("scenario")
            or payload.get("metadata", {}).get("scenario")
        )
        if custom_scenario:
            return str(custom_scenario)

        # Check for SIP trunk indicators
        if call_obj.get("sipHeaders") or "sip" in str(payload).lower():
            return "Scenario 3 (SIP Trunk / Cloud PBX)"

        # Check for BYOC provider indicators
        provider = call_obj.get("provider") or payload.get("provider")
        if provider in ("twilio", "telnyx", "plivo"):
            return f"Scenario 4 (BYOC - {provider.upper()})"

    if DEPLOYMENT_MODE == "marketplace" or active_mode == "marketplace":
        return "Scenario 1 (Marketplace Number)"
    elif active_mode == "overflow":
        return "Scenario 2 (Call Forwarding - Overflow)"
    elif active_mode == "after_hours":
        return "Scenario 2 (Call Forwarding - After Hours)"
    else:
        return "Scenario 2 (Call Forwarding - Standard Hours)"


# ==============================================================================
# CALL MODE & DYNAMIC GREETING LOGIC
# ==============================================================================
def get_time_period_str(dt: datetime) -> str:
    """Returns 'good morning', 'good afternoon', or 'good evening' based on hour."""
    hour = dt.hour
    if hour < 12:
        return "good morning"
    elif hour < 17:
        return "good afternoon"
    else:
        return "good evening"


def get_active_call_mode(current_dt: Optional[datetime] = None, mode: Optional[str] = None) -> str:
    """
    Resolves the active call mode:
    - If DEPLOYMENT_MODE == 'marketplace' or CALL_MODE == 'marketplace': always 'marketplace'
    - If mode is passed or CALL_MODE is explicitly 'normal', 'after_hours', or 'overflow': returns that mode
    - If CALL_MODE is 'auto' (default):
      Checks current Asia/Karachi time. Mon-Sat 9:00 to 17:00 is 'normal'.
      Nights, early mornings, and Sundays are 'after_hours'.
    """
    effective_call_mode = (mode or CALL_MODE).lower()
    if DEPLOYMENT_MODE == "marketplace" or effective_call_mode == "marketplace":
        return "marketplace"

    if effective_call_mode in ("normal", "after_hours", "overflow"):
        return effective_call_mode

    # Auto mode resolution
    now = current_dt or datetime.now(CLINIC_TZ)
    # Sunday is 6 in Python datetime
    if now.weekday() == 6:
        return "after_hours"
    if START_HOUR <= now.hour < END_HOUR:
        return "normal"
    return "after_hours"


def get_dynamic_greeting(current_dt: Optional[datetime] = None, mode: Optional[str] = None) -> str:
    """
    Computes the exact dynamic greeting per call:
    - normal: 'Hello, [good morning/afternoon/evening]! How can I help you today?'
    - after_hours: 'Hello, [good morning/afternoon/evening], our clinic is closed right now, but I can book you an appointment, or connect you to our front desk if it's urgent.'
    - overflow: 'Thank you for waiting, how can I help you today?'
    - marketplace: 'Welcome to HealthNetwork AI, are you looking for a clinic in a specific area or a specific doctor?'
    """
    now = current_dt or datetime.now(CLINIC_TZ)
    resolved_mode = get_active_call_mode(now, mode=mode)
    period = get_time_period_str(now)

    if resolved_mode == "marketplace":
        return "Welcome to HealthNetwork AI, are you looking for a clinic in a specific area or a specific doctor?"
    elif resolved_mode == "overflow":
        return "Thank you for waiting, how can I help you today?"
    elif resolved_mode == "after_hours":
        return f"Hello, {period}, our clinic is closed right now, but I can book you an appointment, or connect you to our front desk if it's urgent."
    else:
        return f"Hello, {period}! How can I help you today?"


# ==============================================================================
# STORAGE HELPERS (Supports data.json and appointments.json)
# ==============================================================================
def load_clinics() -> List[Dict[str, Any]]:
    """Loads sample clinics list from data.json for marketplace mode."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                content = json.load(f)
                return content.get("clinics", [])
        except Exception:
            pass
    return []


def load_appointments() -> List[Dict[str, Any]]:
    """Loads all existing appointments from data.json or appointments.json."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, dict) and "appointments" in content:
                    return content["appointments"]
        except Exception:
            pass
    if os.path.exists(APPOINTMENTS_FILE):
        try:
            with open(APPOINTMENTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_appointments(appointments: List[Dict[str, Any]]) -> None:
    """Saves appointments to both data.json and appointments.json for synchronized storage."""
    clinics = load_clinics()
    data_content = {"clinics": clinics, "appointments": appointments}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data_content, f, indent=2, ensure_ascii=False)
    with open(APPOINTMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(appointments, f, indent=2, ensure_ascii=False)


# ==============================================================================
# PROVIDER & DATE/TIME NORMALIZATION HELPERS
# ==============================================================================
def normalize_provider(name: str) -> Optional[str]:
    """
    Matches caller input to either 'Doctor Steve' or 'Nurse Maha'.
    Supports English, Urdu (اردو / Roman Urdu), Arabic (العربية), French (Français), and Spanish (Español).
    """
    if not name:
        return None
    lower_name = name.strip().lower()

    # Nurse Maha keywords across English, Urdu, Arabic, French, Spanish
    nurse_keywords = [
        "maha", "amber", "nurse", "nars", "نرس", "ماہا", "مها",
        "infirmiere", "infirmière", "infirmier",
        "enfermera", "enfermero",
        "mumarrida", "mumarrid", "ممرضة", "ممرض"
    ]
    if any(k in lower_name for k in nurse_keywords):
        return "Nurse Maha"

    # Doctor Steve keywords across English, Urdu, Arabic, French, Spanish
    doctor_keywords = [
        "steve", "doctor", "dr", "docteur", "medecin", "médecin",
        "medico", "médico", "medica", "médica",
        "daaktar", "ڈاکٹر", "اسٹیو",
        "tabib", "tabeeb", "duktur", "طبيب", "دكتور", "ستيف"
    ]
    if any(k in lower_name for k in doctor_keywords):
        return "Doctor Steve"

    return None


def parse_date(date_str: str) -> Optional[datetime]:
    """Parses date strings into a timezone-aware datetime at midnight in clinic timezone."""
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=CLINIC_TZ)
        except ValueError:
            continue
    return None


def normalize_time(time_str: str) -> Optional[str]:
    """Converts various time representations into standardized 24-hour 'HH:MM' string format."""
    if not time_str:
        return None
    time_clean = time_str.strip().upper()
    time_clean = re.sub(r"\s+", " ", time_clean)

    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M", "%H"):
        try:
            parsed = datetime.strptime(time_clean, fmt).time()
            return f"{parsed.hour:02d}:{parsed.minute:02d}"
        except ValueError:
            continue
    return None


def format_time_voice(time_24: str) -> str:
    """Converts '14:30' into natural voice-friendly '2:30 PM'."""
    try:
        t = datetime.strptime(time_24, "%H:%M").time()
        hour_12 = t.hour % 12
        hour_12 = 12 if hour_12 == 0 else hour_12
        period = "AM" if t.hour < 12 else "PM"
        if t.minute == 0:
            return f"{hour_12}:00 {period}"
        return f"{hour_12}:{t.minute:02d} {period}"
    except Exception:
        return time_24


def generate_day_slots(target_date: datetime) -> List[str]:
    """Generates standard 30-minute slots between START_HOUR and END_HOUR."""
    slots = []
    current_dt = target_date.replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
    end_dt = target_date.replace(hour=END_HOUR, minute=0, second=0, microsecond=0)

    now_karachi = datetime.now(CLINIC_TZ)
    is_today = (target_date.date() == now_karachi.date())

    while current_dt < end_dt:
        time_str = f"{current_dt.hour:02d}:{current_dt.minute:02d}"
        if is_today:
            if current_dt > now_karachi + timedelta(minutes=10):
                slots.append(time_str)
        else:
            slots.append(time_str)
        current_dt += timedelta(minutes=SLOT_MINUTES)
    return slots


# ==============================================================================
# TOOL 1: CHECK AVAILABILITY (Local + Mock Mode)
# ==============================================================================
def check_availability(provider: str, date: str) -> Dict[str, Any]:
    """
    Checks free 30-minute slots for Doctor Steve or Nurse Maha on a given date.
    In 'mock' mode: forwards GET request to MOCK_URL/availability.
    On 404: returns slot unavailable message.
    On 500/network error: stays calm and offers front desk.
    """
    # MOCK MODE FORWARDING
    if BACKEND_MODE == "mock":
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{MOCK_URL}/availability", params={"provider": provider, "date": date})
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict):
                        if "message" not in data and "available_slots" in data:
                            slots_str = ", ".join(data.get("available_slots", []))
                            data["message"] = f"Available slots for {provider} on {date} include: {slots_str}. What time works best for you?"
                        return data
                    return {"status": "available", "message": str(data)}
                elif resp.status_code == 404:
                    return {
                        "status": "unavailable",
                        "message": "That time slot was just taken, would another time work?"
                    }
                elif resp.status_code >= 500:
                    return {
                        "status": "error",
                        "message": "I am having trouble accessing our scheduling system right now. Let me connect you directly to our front desk so they can help you right away."
                    }
                else:
                    return {"status": "error", "message": f"Scheduling service returned status {resp.status_code}."}
        except Exception:
            return {
                "status": "error",
                "message": "I am having trouble accessing our scheduling system right now. Let me connect you directly to our front desk so they can help you right away."
            }

    # LOCAL CALENDAR MODE
    matched_provider = normalize_provider(provider)
    if not matched_provider:
        return {
            "status": "error",
            "message": "We only have appointments available with Doctor Steve or Nurse Maha. Which provider would you prefer to see?"
        }

    parsed_date = parse_date(date)
    if not parsed_date:
        return {
            "status": "error",
            "message": "I did not catch the date clearly. What day would you like to schedule your visit?"
        }

    now_karachi = datetime.now(CLINIC_TZ)
    today_midnight = now_karachi.replace(hour=0, minute=0, second=0, microsecond=0)

    if parsed_date < today_midnight:
        next_day = now_karachi + timedelta(days=1)
        if next_day.weekday() == 6:
            next_day += timedelta(days=1)
        suggested_day = next_day.strftime("%A, %B %d")
        return {
            "status": "error",
            "message": f"That date has already passed. The next available clinic day is {suggested_day}. Would that work for you?"
        }

    if parsed_date.weekday() == 6:
        next_monday = parsed_date + timedelta(days=1)
        monday_str = next_monday.strftime("%A, %B %d")
        return {
            "status": "closed",
            "message": f"Our clinic is closed on Sundays. Our next available open day is {monday_str}. Would you like to check times for that day?"
        }

    all_slots = generate_day_slots(parsed_date)
    if not all_slots:
        return {
            "status": "full",
            "message": f"There are no remaining slots available on {parsed_date.strftime('%A, %B %d')}. Would you like to check the next business day?"
        }

    date_iso = parsed_date.strftime("%Y-%m-%d")
    booked_slots = {
        apt.get("time") for apt in load_appointments()
        if apt.get("provider") == matched_provider and apt.get("date") == date_iso
    }

    free_slots = [s for s in all_slots if s not in booked_slots]

    if not free_slots:
        return {
            "status": "full",
            "message": f"{matched_provider} is fully booked on {parsed_date.strftime('%A, %B %d')}. Would you like to try another date?"
        }

    spoken_slots = [format_time_voice(s) for s in free_slots[:5]]
    slots_speech = ", ".join(spoken_slots[:-1]) + f", and {spoken_slots[-1]}" if len(spoken_slots) > 1 else spoken_slots[0]

    return {
        "status": "available",
        "provider": matched_provider,
        "date": date_iso,
        "available_slots": free_slots,
        "message": f"On {parsed_date.strftime('%A, %B %d')}, {matched_provider} has openings at {slots_speech}. What time works best for you?"
    }


# ==============================================================================
# TOOL 2: BOOK APPOINTMENT (Local + Mock Mode)
# ==============================================================================
def book_appointment(
    patient_name: str,
    phone: str,
    provider: str,
    date: str,
    time: str,
    reason: str = ""
) -> Dict[str, Any]:
    """
    Books a 30-minute appointment.
    In 'mock' mode: forwards POST request to MOCK_URL/book.
    On 404: returns slot collision message.
    On 500/network error: stays calm and offers front desk.
    """
    # MOCK MODE FORWARDING
    if BACKEND_MODE == "mock":
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    f"{MOCK_URL}/book",
                    json={
                        "patient_name": patient_name,
                        "phone": phone,
                        "provider": provider,
                        "date": date,
                        "time": time,
                        "reason": reason
                    }
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    ref_id = data.get("appointment_id", f"APT-{uuid.uuid4().hex[:6].upper()}")
                    return {
                        "status": "confirmed",
                        "appointment_id": ref_id,
                        "message": f"Your appointment is confirmed with {provider} on {date} at {time}. Your reference number is {ref_id}."
                    }
                elif resp.status_code == 404:
                    return {
                        "status": "collision",
                        "message": "That time slot was just taken, would another time work?"
                    }
                elif resp.status_code >= 500:
                    return {
                        "status": "error",
                        "message": "I am having trouble accessing our booking system right now. Let me connect you directly to our front desk so they can help you right away."
                    }
                else:
                    return {"status": "error", "message": f"Booking service returned status {resp.status_code}."}
        except Exception:
            return {
                "status": "error",
                "message": "I am having trouble accessing our booking system right now. Let me connect you directly to our front desk so they can help you right away."
            }

    # LOCAL CALENDAR MODE
    matched_provider = normalize_provider(provider)
    if not matched_provider:
        return {
            "status": "error",
            "message": "We only schedule appointments for Doctor Steve or Nurse Maha. Which provider should I book this with?"
        }

    # Clinical Scope Guardrail: Nurse Maha cannot handle consultations or complex symptoms
    if matched_provider == "Nurse Maha" and reason:
        reason_lower = reason.lower()
        consult_terms = (
            "consultation", "consult", "diagnose", "diagnosis", "chest pain", "second opinion", "severe", "sick", "illness",
            # Urdu terms
            "طبیعت", "بیمار", "درد", "بخار", "کھانسی", "مشورہ", "چیک اپ",
            # Arabic terms
            "استشارة", "مريض", "ألم", "حمى", "سعال", "تشخيص", "فحص",
            # French terms
            "malade", "douleur", "fièvre", "fievre", "toux",
            # Spanish terms
            "enfermo", "fiebre", "tos"
        )
        if any(term in reason_lower for term in consult_terms):
            return {
                "status": "error",
                "message": (
                    "Nurse Maha specializes in routine care, injections, dressing changes, and vaccinations. "
                    "For consultations and medical check-ups, I can schedule you with Doctor Steve instead. Would that work?"
                )
            }

    parsed_date = parse_date(date)
    if not parsed_date:
        return {
            "status": "error",
            "message": "I could not confirm the appointment date. What day would you like to schedule?"
        }

    now_karachi = datetime.now(CLINIC_TZ)
    today_midnight = now_karachi.replace(hour=0, minute=0, second=0, microsecond=0)

    if parsed_date < today_midnight:
        return {
            "status": "error",
            "message": "We cannot book an appointment for a past date. Please suggest a future date."
        }

    if parsed_date.weekday() == 6:
        next_monday = parsed_date + timedelta(days=1)
        monday_str = next_monday.strftime("%A, %B %d")
        return {
            "status": "error",
            "message": f"Our clinic is closed on Sundays. Would you like me to book you for {monday_str} instead?"
        }

    normalized_time_24 = normalize_time(time)
    if not normalized_time_24:
        return {
            "status": "error",
            "message": "I did not catch the appointment time. Could you please repeat the time you prefer?"
        }

    date_iso = parsed_date.strftime("%Y-%m-%d")
    appointments = load_appointments()

    # Collision detection
    for apt in appointments:
        if (
            apt.get("provider") == matched_provider
            and apt.get("date") == date_iso
            and apt.get("time") == normalized_time_24
        ):
            return {
                "status": "collision",
                "message": "That time slot was just taken, would another time work?"
            }

    all_slots = generate_day_slots(parsed_date)
    if normalized_time_24 not in all_slots:
        return {
            "status": "error",
            "message": (
                f"{format_time_voice(normalized_time_24)} is outside our operating hours or has already passed. "
                "Our clinic operates Monday to Saturday, 9:00 AM to 5:00 PM."
            )
        }

    appointment_id = f"APT-{uuid.uuid4().hex[:6].upper()}"
    new_appointment = {
        "appointment_id": appointment_id,
        "patient_name": patient_name.strip(),
        "phone": phone.strip(),
        "provider": matched_provider,
        "date": date_iso,
        "time": normalized_time_24,
        "reason": (reason or "General consultation").strip(),
        "created_at": now_karachi.isoformat()
    }

    appointments.append(new_appointment)
    save_appointments(appointments)

    voice_time = format_time_voice(normalized_time_24)
    voice_date = parsed_date.strftime("%A, %B %d, %Y")

    return {
        "status": "confirmed",
        "appointment_id": appointment_id,
        "details": new_appointment,
        "message": (
            f"Your appointment is confirmed with {matched_provider} on {voice_date} at {voice_time}. "
            f"Your reference number is {appointment_id}."
        )
    }


# ==============================================================================
# TOOL 3: FIND CLINIC (Marketplace Mode)
# ==============================================================================
def find_clinic(area: Optional[str] = None, specialty: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
    """
    Marketplace mode tool: Finds sample clinics based on geographic area, medical specialty, or name.
    """
    clinics = load_clinics()
    matched = []
    area_q = (area or "").strip().lower()
    spec_q = (specialty or "").strip().lower()
    name_q = (name or "").strip().lower()

    for c in clinics:
        c_area = c.get("area", "").lower()
        c_name = c.get("name", "").lower()
        c_specs = [s.lower() for s in c.get("specialties", [])]
        c_docs = [d.lower() for d in c.get("providers", [])]

        score = 0
        if area_q and (area_q in c_area or c_area in area_q):
            score += 2
        if spec_q and any(spec_q in s or s in spec_q for s in c_specs):
            score += 2
        if name_q and (name_q in c_name or any(name_q in d for d in c_docs)):
            score += 2

        if not (area_q or spec_q or name_q) or score > 0:
            matched.append(c)

    if not matched:
        matched = clinics

    clinic_summaries = []
    for c in matched:
        docs = " and ".join(c.get("providers", []))
        clinic_summaries.append(f"{c['name']} located in {c['area']} with {docs}")

    speech = (
        "Here are our available clinics: " + "; ".join(clinic_summaries) +
        ". Which clinic location or doctor would you like to book with?"
    )

    return {
        "status": "success",
        "clinics": matched,
        "message": speech
    }


# ==============================================================================
# TOOL 4: WARM TRANSFER HELPER
# ==============================================================================
def prepare_warm_transfer(caller_issue: str) -> Dict[str, Any]:
    """
    Warm transfer helper: summarizes caller issue to prepare handover to front desk.
    """
    issue_clean = (caller_issue or "Caller requires front desk assistance").strip()
    summary = f"Patient Transfer Summary: {issue_clean}. Priority: Urgent/Front Desk."
    return {
        "status": "transfer_prepared",
        "summary": summary,
        "message": "I'm connecting you to our front desk right away. Please stay on the line."
    }


# ==============================================================================
# TOOL 5: CHECK INSURANCE (Stedi Test Mode Mock Eligibility)
# ==============================================================================
def check_insurance(payer: str, member_id: str, patient_name: str) -> Dict[str, Any]:
    """
    Checks insurance eligibility via Stedi test mode mock API.
    Supports Aetna, Cigna, UnitedHealthcare, and CMS (Medicare).
    Never transmits real PHI. Masks member ID in all logs and outputs.
    """
    from stedi_client import check_eligibility_mock
    return check_eligibility_mock(
        payer=payer,
        member_id=member_id,
        patient_name=patient_name
    )


# ==============================================================================
# CENTRAL TOOL DISPATCHER (Shared between Vapi and Retell)
# ==============================================================================
def execute_tool(func_name: str, func_args: Dict[str, Any]) -> tuple[str, bool]:
    """
    Executes a requested tool by name and returns (result_text, is_error).
    Shared across both Vapi (/webhook) and Retell (/webhook/retell) endpoints.
    """
    try:
        if func_name == "check_availability":
            provider = func_args.get("provider", "")
            date_val = func_args.get("date", "")
            out = check_availability(provider=provider, date=date_val)
            return out.get("message", json.dumps(out)), (out.get("status") == "error")

        elif func_name == "book_appointment":
            out = book_appointment(
                patient_name=func_args.get("patient_name", ""),
                phone=func_args.get("phone", ""),
                provider=func_args.get("provider", ""),
                date=func_args.get("date", ""),
                time=func_args.get("time", ""),
                reason=func_args.get("reason", "")
            )
            return out.get("message", json.dumps(out)), (out.get("status") == "error")

        elif func_name == "find_clinic":
            out = find_clinic(
                area=func_args.get("area"),
                specialty=func_args.get("specialty"),
                name=func_args.get("name")
            )
            return out.get("message", json.dumps(out)), False

        elif func_name in ("prepare_warm_transfer", "warm_transfer"):
            out = prepare_warm_transfer(
                caller_issue=func_args.get("caller_issue", func_args.get("issue", ""))
            )
            return out.get("message", json.dumps(out)), False

        elif func_name == "check_insurance":
            payer = func_args.get("payer", "")
            member_id = func_args.get("member_id", "")
            patient_name = func_args.get("patient_name", func_args.get("name", ""))
            out = check_insurance(payer=payer, member_id=member_id, patient_name=patient_name)
            is_err = out.get("status") in ("error", "bad_key", "timeout")
            return out.get("message", json.dumps(out)), is_err

        else:
            return f"Function '{func_name}' is not recognized.", True

    except Exception as exc:
        return f"An unexpected error occurred while executing {func_name}: {str(exc)}", True


# ==============================================================================
# FASTAPI ROUTES: FRONTEND WEB CONSOLE, HEALTH, VAPI WEBHOOK, RETELL WEBHOOK
# ==============================================================================
class InsuranceCheckRequest(BaseModel):
    payer: str
    member_id: str
    patient_name: str


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    """Serves the interactive Hospital Voice Receptionist web control center."""
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if not os.path.exists(template_path):
        return HTMLResponse("<h1>Hospital Voice Receptionist Console</h1><p>Template not found.</p>")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    pub_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:3000").rstrip("/")
    vapi_pub_key = os.getenv("VAPI_PUBLIC_KEY", "")
    vapi_asst_id = os.getenv("VAPI_ASSISTANT_ID", "")

    html = html.replace("{{PUBLIC_BASE_URL}}", pub_url)
    html = html.replace("{{VAPI_PUBLIC_KEY}}", vapi_pub_key)
    html = html.replace("{{VAPI_ASSISTANT_ID}}", vapi_asst_id)
    return HTMLResponse(content=html, status_code=200)


@app.get("/api/appointments")
def api_get_appointments():
    """Returns booked appointments from storage."""
    return load_appointments()


@app.get("/api/availability")
def api_get_availability(provider: str = Query(...), date: str = Query(...)):
    """Checks availability for a provider on a specific date."""
    return check_availability(provider=provider, date=date)


@app.post("/api/check-insurance")
def api_check_insurance(req: InsuranceCheckRequest):
    """Executes Stedi insurance eligibility verification."""
    return check_insurance(payer=req.payer, member_id=req.member_id, patient_name=req.patient_name)


@app.get("/health")
def health_check():
    """Health check endpoint reporting backend mode, deployment mode, call mode, and greeting."""
    now_karachi = datetime.now(CLINIC_TZ)
    active_mode = get_active_call_mode(now_karachi)
    greeting = get_dynamic_greeting(now_karachi)

    return {
        "status": "healthy",
        "service": "hospital-voice-agent",
        "backend_mode": BACKEND_MODE,
        "mock_url": MOCK_URL if BACKEND_MODE == "mock" else None,
        "deployment_mode": DEPLOYMENT_MODE,
        "call_mode": CALL_MODE,
        "active_call_mode": active_mode,
        "timezone": TIMEZONE_STR,
        "current_time": now_karachi.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "greeting": greeting,
        "working_hours": f"{START_HOUR}:00 to {END_HOUR}:00 (Mon-Sat)"
    }


@app.post("/webhook")
async def vapi_webhook(
    request: Request,
    x_vapi_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None)
):
    """
    Main webhook endpoint for Vapi calls.
    - Authenticates requests against WEBHOOK_SECRET.
    - Handles 'assistant-request' server messages to dynamically set firstMessage and call_mode per call.
    - Handles 'tool-calls' and returns results strictly in Vapi schema:
      { "results": [ { "toolCallId": "...", "result": "..." } ] }
    - Logs event type, tool name, masked arguments, results, call mode, and scenario.
    """
    expected_secret = get_webhook_secret()
    if expected_secret:
        incoming_secret = x_vapi_secret or secret
        if incoming_secret != expected_secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing webhook secret"
            )

    try:
        body = await request.json()
    except Exception:
        return {"error": "Invalid JSON body"}

    active_mode = get_active_call_mode()
    scenario = get_scenario_label(active_mode, body)
    message = body.get("message", {})
    message_type = message.get("type", "unknown")

    logger.info(
        f"[Vapi Webhook] Event: {message_type} | Call Mode: {active_mode} | Telephony Scenario: {scenario}"
    )

    # DYNAMIC PER-CALL GREETING VIA VAPI ASSISTANT-REQUEST
    if message_type == "assistant-request":
        greeting = get_dynamic_greeting()
        logger.info(
            f"[Vapi assistant-request] Dynamic greeting: '{greeting}' | Mode: {active_mode} | Scenario: {scenario}"
        )
        return {
            "assistant": {
                "firstMessage": greeting,
                "variableValues": {
                    "call_mode": active_mode,
                    "greeting": greeting
                }
            }
        }

    # If non-tool-call event (status-update, end-of-call-report), acknowledge 200 OK
    if message_type != "tool-calls":
        return {"status": "received", "type": message_type}

    tool_calls = message.get("toolCalls") or message.get("toolCallList") or []
    results = []

    for call in tool_calls:
        tool_call_id = call.get("id")
        function_def = call.get("function", {})
        func_name = function_def.get("name")
        func_args = function_def.get("arguments", {})

        if isinstance(func_args, str):
            try:
                func_args = json.loads(func_args)
            except Exception:
                func_args = {}

        masked_args = mask_args_for_logging(func_args)
        logger.info(
            f"[Vapi Tool Call] Tool: {func_name} | Args: {masked_args} | Mode: {active_mode} | Scenario: {scenario}"
        )

        result_text, is_error = execute_tool(func_name, func_args)

        logger.info(
            f"[Vapi Tool Result] Tool: {func_name} | Error: {is_error} | Result: {result_text}"
        )

        if is_error:
            results.append({"toolCallId": tool_call_id, "error": result_text})
        else:
            results.append({"toolCallId": tool_call_id, "result": result_text})

    return {"results": results}


@app.post("/webhook/retell")
async def retell_webhook(
    request: Request,
    x_retell_signature: Optional[str] = Header(None),
    x_vapi_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None)
):
    """
    Dedicated webhook endpoint for Retell AI custom tool calls and inbound call handling.
    - Authenticates requests against WEBHOOK_SECRET.
    - For inbound/lifecycle calls: provides dynamic begin_message and call_mode.
    - For tool calls: executes shared tool logic and returns { "result": "..." }.
    - Logs event type, tool name, masked arguments, results, call mode, and scenario.
    """
    expected_secret = get_webhook_secret()
    if expected_secret:
        incoming_secret = x_retell_signature or x_vapi_secret or secret
        if incoming_secret and incoming_secret != expected_secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing webhook secret"
            )

    try:
        body = await request.json()
    except Exception:
        return {"error": "Invalid JSON body"}

    active_mode = get_active_call_mode()
    scenario = get_scenario_label(active_mode, body)

    func_name = (
        body.get("name")
        or body.get("tool_name")
        or body.get("function", {}).get("name")
    )
    func_args = (
        body.get("args")
        or body.get("arguments")
        or body.get("parameters")
        or body.get("function", {}).get("arguments")
        or {}
    )

    if isinstance(func_args, str):
        try:
            func_args = json.loads(func_args)
        except Exception:
            func_args = {}

    # DYNAMIC GREETING FOR RETELL INBOUND / LIFECYCLE EVENTS
    if not func_name:
        greeting = get_dynamic_greeting()
        logger.info(
            f"[Retell Inbound] Dynamic greeting: '{greeting}' | Mode: {active_mode} | Scenario: {scenario}"
        )
        return {
            "status": "ok",
            "override_agent": {
                "begin_message": greeting
            },
            "dynamic_variables": {
                "call_mode": active_mode,
                "greeting": greeting
            }
        }

    masked_args = mask_args_for_logging(func_args)
    logger.info(
        f"[Retell Tool Call] Tool: {func_name} | Args: {masked_args} | Mode: {active_mode} | Scenario: {scenario}"
    )

    result_text, is_error = execute_tool(func_name, func_args)

    logger.info(
        f"[Retell Tool Result] Tool: {func_name} | Error: {is_error} | Result: {result_text}"
    )

    tool_call_id = body.get("tool_call_id") or body.get("id")

    response_payload = {"result": result_text}
    if tool_call_id:
        response_payload["tool_call_id"] = tool_call_id
    return response_payload


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=3000, reload=True)
