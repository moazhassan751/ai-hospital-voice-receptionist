"""
test_server.py - Automated Verification Suite for AI Hospital Voice Receptionist.
Tests:
1. Health check endpoint & active mode reporting.
2. Auto call mode time resolution (weekday work hours, late evening, Sunday).
3. Dynamic per-call greetings for all modes (normal, after_hours, overflow, marketplace).
4. Marketplace greeting precedence over call modes.
5. Emergency transfer and warm handover in every call mode.
6. Doctor Steve & Nurse Maha availability rules & Sunday/past-date validation.
7. End-to-end booking & collision detection.
8. Vapi assistant-request dynamic greeting webhook.
9. Retell AI webhook support.
10. All four telephony scenarios simulated call tests & edge cases (Vapi and Retell payloads).
11. Stedi insurance eligibility verification in test mode (mocked responses, error recovery, masking).

No real phone APIs, carrier services, or external Stedi endpoints are called.
"""

import asyncio
from datetime import datetime, timedelta
import json
import os
import sys
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Import server components
import server
from server import (
    app,
    CLINIC_TZ,
    get_active_call_mode,
    get_dynamic_greeting,
    save_appointments,
    FRONT_DESK_NUMBER,
    execute_tool
)
import stedi_client


async def run_all_tests():
    print("=" * 70)
    print("STARTING COMPLETE TELEPHONY & BACKEND TEST SUITE")
    print("=" * 70)

    # Clean test appointments table
    save_appointments([])

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        # ----------------------------------------------------------------------
        # TEST 1: AUTO CALL MODE TIME RESOLUTION
        # ----------------------------------------------------------------------
        print("\n[Test 1] Auto Call Mode Time Resolution (Asia/Karachi)")
        orig_call_mode = server.CALL_MODE
        orig_dep_mode = server.DEPLOYMENT_MODE
        server.CALL_MODE = "auto"
        server.DEPLOYMENT_MODE = "single_hospital"

        # 1a: Weekday 11:00 AM (Open hours: 9:00 - 17:00) -> should be 'normal'
        wednesday_morning = datetime(2026, 10, 14, 11, 0, tzinfo=CLINIC_TZ)
        mode_1a = get_active_call_mode(wednesday_morning)
        assert mode_1a == "normal", f"Expected 'normal' for weekday 11 AM, got {mode_1a}"
        print("  [OK] Weekday 11:00 AM resolves to: normal")

        # 1b: Weekday 8:30 PM (20:30) (After hours) -> should be 'after_hours'
        wednesday_night = datetime(2026, 10, 14, 20, 30, tzinfo=CLINIC_TZ)
        mode_1b = get_active_call_mode(wednesday_night)
        assert mode_1b == "after_hours", f"Expected 'after_hours' for weekday 8:30 PM, got {mode_1b}"
        print("  [OK] Weekday 8:30 PM resolves to: after_hours")

        # 1c: Weekday 7:15 AM (Before hours) -> should be 'after_hours'
        wednesday_early = datetime(2026, 10, 14, 7, 15, tzinfo=CLINIC_TZ)
        mode_1c = get_active_call_mode(wednesday_early)
        assert mode_1c == "after_hours", f"Expected 'after_hours' for weekday 7:15 AM, got {mode_1c}"
        print("  [OK] Weekday 7:15 AM resolves to: after_hours")

        # 1d: Sunday 12:00 PM (Clinic closed all day Sunday) -> should be 'after_hours'
        sunday_noon = datetime(2026, 10, 18, 12, 0, tzinfo=CLINIC_TZ)
        mode_1d = get_active_call_mode(sunday_noon)
        assert mode_1d == "after_hours", f"Expected 'after_hours' for Sunday noon, got {mode_1d}"
        print("  [OK] Sunday 12:00 PM resolves to: after_hours")

        # ----------------------------------------------------------------------
        # TEST 2: GREETINGS FOR EACH CALL MODE
        # ----------------------------------------------------------------------
        print("\n[Test 2] Dynamic Greetings Verification")

        # 2a: Normal mode morning
        morning_dt = datetime(2026, 10, 14, 10, 0, tzinfo=CLINIC_TZ)
        greet_normal_morning = get_dynamic_greeting(morning_dt, mode="normal")
        assert "Hello, good morning! How can I help you today?" == greet_normal_morning
        print(f"  [OK] Normal Mode Morning: '{greet_normal_morning}'")

        # 2b: Normal mode afternoon
        afternoon_dt = datetime(2026, 10, 14, 14, 0, tzinfo=CLINIC_TZ)
        greet_normal_aft = get_dynamic_greeting(afternoon_dt, mode="normal")
        assert "Hello, good afternoon! How can I help you today?" == greet_normal_aft
        print(f"  [OK] Normal Mode Afternoon: '{greet_normal_aft}'")

        # 2c: After-hours mode (picks period word from actual time)
        evening_dt = datetime(2026, 10, 14, 21, 0, tzinfo=CLINIC_TZ)
        greet_after_hours = get_dynamic_greeting(evening_dt, mode="after_hours")
        assert "Hello, good evening, our clinic is closed right now, but I can book you an appointment, or connect you to our front desk if it's urgent." == greet_after_hours
        print(f"  [OK] After-Hours Evening: '{greet_after_hours}'")

        # 2d: Overflow mode
        greet_overflow = get_dynamic_greeting(morning_dt, mode="overflow")
        assert "Thank you for waiting, how can I help you today?" == greet_overflow
        print(f"  [OK] Overflow Mode: '{greet_overflow}'")

        # 2e: Marketplace mode
        greet_market = get_dynamic_greeting(morning_dt, mode="marketplace")
        assert "Welcome to HealthNetwork AI, are you looking for a clinic in a specific area or a specific doctor?" == greet_market
        print(f"  [OK] Marketplace Mode: '{greet_market}'")

        # ----------------------------------------------------------------------
        # TEST 3: MARKETPLACE PRECEDENCE
        # ----------------------------------------------------------------------
        print("\n[Test 3] Marketplace Precedence Rule")
        server.DEPLOYMENT_MODE = "marketplace"
        for test_mode in ["normal", "after_hours", "overflow", "auto"]:
            server.CALL_MODE = test_mode
            res_mode = get_active_call_mode(wednesday_morning)
            res_greet = get_dynamic_greeting(wednesday_morning)
            assert res_mode == "marketplace", f"Expected 'marketplace', got {res_mode} when CALL_MODE={test_mode}"
            assert "Welcome to HealthNetwork AI" in res_greet
        print("  [OK] Marketplace greeting always wins when DEPLOYMENT_MODE=marketplace")

        server.DEPLOYMENT_MODE = "single_hospital"
        server.CALL_MODE = "auto"

        # ----------------------------------------------------------------------
        # TEST 4: EMERGENCY TRANSFER IN EVERY CALL MODE
        # ----------------------------------------------------------------------
        print("\n[Test 4] Emergency Front Desk Transfer in Every Call Mode")
        emergency_issue = "Patient experiencing severe sudden chest pain and shortness of breath"

        for mode in ["normal", "after_hours", "overflow", "marketplace"]:
            server.CALL_MODE = mode
            msg_str, is_err = execute_tool("prepare_warm_transfer", {"caller_issue": emergency_issue})
            assert not is_err, f"Transfer tool failed in mode {mode}"
            assert "connecting you to our front desk" in msg_str.lower()

            transfer_dict = server.prepare_warm_transfer(emergency_issue)
            assert transfer_dict["status"] == "transfer_prepared"
            assert "chest pain" in transfer_dict["summary"].lower()
            assert FRONT_DESK_NUMBER, "FRONT_DESK_NUMBER must be configured"
            print(f"  [OK] Mode '{mode}': Emergency transferred to front desk ({FRONT_DESK_NUMBER})")

        server.CALL_MODE = "auto"

        # ----------------------------------------------------------------------
        # TEST 5: GET /health REPORTING ACTIVE MODE & GREETING
        # ----------------------------------------------------------------------
        print("\n[Test 5] GET /health Active Mode Reporting")
        resp = await client.get("/health")
        assert resp.status_code == 200
        health = resp.json()
        print("  Health output:", health)
        assert health["status"] == "healthy"
        assert health["timezone"] == "Asia/Karachi"
        assert "call_mode" in health
        assert "active_call_mode" in health
        assert "greeting" in health
        print("  [OK] /health correctly reports active_call_mode and dynamic greeting")

        # ----------------------------------------------------------------------
        # TEST 6: VAPI WEBHOOK ASSISTANT-REQUEST (DYNAMIC PER-CALL GREETING)
        # ----------------------------------------------------------------------
        print("\n[Test 6] Vapi Dynamic Per-Call assistant-request Event")
        headers = {"x-vapi-secret": server.WEBHOOK_SECRET}
        assistant_req_payload = {
            "message": {
                "type": "assistant-request",
                "call": {
                    "id": "test_call_vapi_1"
                }
            }
        }
        res_vapi = await client.post("/webhook", json=assistant_req_payload, headers=headers)
        assert res_vapi.status_code == 200
        data_vapi = res_vapi.json()
        print("  Vapi assistant-request response:", data_vapi)
        assert "assistant" in data_vapi
        assert "firstMessage" in data_vapi["assistant"]
        assert "variableValues" in data_vapi["assistant"]
        assert "call_mode" in data_vapi["assistant"]["variableValues"]
        print("  [OK] Vapi receives dynamic firstMessage and variableValues per call")

        # ----------------------------------------------------------------------
        # TEST 7: RETELL WEBHOOK INBOUND & DYNAMIC GREETING
        # ----------------------------------------------------------------------
        print("\n[Test 7] Retell AI Inbound Dynamic Greeting")
        res_retell = await client.post("/webhook/retell", json={}, headers=headers)
        assert res_retell.status_code == 200
        data_retell = res_retell.json()
        print("  Retell inbound response:", data_retell)
        assert data_retell["status"] == "ok"
        assert "begin_message" in data_retell["override_agent"]
        assert "call_mode" in data_retell["dynamic_variables"]
        print("  [OK] Retell receives dynamic begin_message and call_mode")

        # ----------------------------------------------------------------------
        # TEST 8: BOOKING FLOW, COLLISION & WORKING HOURS
        # ----------------------------------------------------------------------
        print("\n[Test 8] Booking Flow, Sunday Rejection & Collision Detection")
        now_karachi = datetime.now(CLINIC_TZ)
        days = 1
        valid_date = now_karachi + timedelta(days=days)
        while valid_date.weekday() == 6:
            days += 1
            valid_date = now_karachi + timedelta(days=days)
        valid_date_str = valid_date.strftime("%Y-%m-%d")

        days_to_sun = (6 - now_karachi.weekday()) % 7 or 7
        sun_date_str = (now_karachi + timedelta(days=days_to_sun)).strftime("%Y-%m-%d")

        sun_payload = {
            "message": {
                "type": "tool-calls",
                "toolCalls": [
                    {
                        "id": "c_sun",
                        "function": {
                            "name": "check_availability",
                            "arguments": {"provider": "Doctor Steve", "date": sun_date_str}
                        }
                    }
                ]
            }
        }
        res_sun = await client.post("/webhook", json=sun_payload, headers=headers)
        sun_res_obj = res_sun.json()["results"][0]
        sun_msg = sun_res_obj.get("error") or sun_res_obj.get("result", "")
        assert "closed on sundays" in sun_msg.lower()
        print("  [OK] Sunday correctly rejected")

        book_payload = {
            "message": {
                "type": "tool-calls",
                "toolCalls": [
                    {
                        "id": "c_book",
                        "function": {
                            "name": "book_appointment",
                            "arguments": {
                                "patient_name": "Sarah Connor",
                                "phone": "+923001234567",
                                "provider": "Doctor Steve",
                                "date": valid_date_str,
                                "time": "10:00 AM",
                                "reason": "General check-up"
                            }
                        }
                    }
                ]
            }
        }
        res_book = await client.post("/webhook", json=book_payload, headers=headers)
        assert res_book.status_code == 200
        book_res_obj = res_book.json()["results"][0]
        book_result = book_res_obj.get("result") or book_res_obj.get("error", "")
        assert "confirmed" in book_result.lower()
        print(f"  [OK] Booked 10:00 AM slot on {valid_date_str} for Sarah Connor")

        res_dup = await client.post("/webhook", json=book_payload, headers=headers)
        dup_res_obj = res_dup.json()["results"][0]
        dup_result = dup_res_obj.get("error") or dup_res_obj.get("result", "")
        assert "just taken" in dup_result.lower() or "already booked" in dup_result.lower() or "not available" in dup_result.lower()
        print("  [OK] Collision detection confirmed: second attempt on same slot rejected")

        # ----------------------------------------------------------------------
        # TEST 9: MOCK MODE FORWARDING (200 CONFIRMED, 404 SLOT TAKEN, 500 SERVER ERROR)
        # ----------------------------------------------------------------------
        print("\n[Test 9] Mock Mode Forwarding (Mockoon / Beeceptor / Mockbin)")
        server.BACKEND_MODE = "mock"
        server.MOCK_URL = "http://localhost:3001"

        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.json.return_value = {"status": "confirmed", "appointment_id": "98765"}

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp_200
            res_mock_200 = server.book_appointment("Jane Doe", "+1234567890", "Doctor Steve", "2026-10-15", "10:00 AM", "Follow-up")
            assert res_mock_200["status"] == "confirmed"
            assert res_mock_200["appointment_id"] == "98765"
            assert "98765" in res_mock_200["message"]
            print("  [OK] Mock 200: Confirmed appointment with reference 98765")

        mock_resp_404 = MagicMock()
        mock_resp_404.status_code = 404

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp_404
            res_mock_404 = server.book_appointment("Jane Doe", "+1234567890", "Doctor Steve", "2026-10-15", "10:00 AM", "Follow-up")
            assert res_mock_404["status"] == "collision"
            assert "That time slot was just taken, would another time work?" == res_mock_404["message"]
            print("  [OK] Mock 404: Returns 'That time slot was just taken, would another time work?'")

        mock_resp_500 = MagicMock()
        mock_resp_500.status_code = 500

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp_500
            res_mock_500 = server.book_appointment("Jane Doe", "+1234567890", "Doctor Steve", "2026-10-15", "10:00 AM", "Follow-up")
            assert res_mock_500["status"] == "error"
            assert "trouble accessing our booking system right now" in res_mock_500["message"]
            assert "connect you directly to our front desk" in res_mock_500["message"]
            print("  [OK] Mock 500: Stays calm and offers front desk connection")

        server.BACKEND_MODE = "local"

        # ----------------------------------------------------------------------
        # TEST 10: ALL FOUR TELEPHONY SCENARIOS SIMULATED CALL TESTS & EDGE CASES
        # ----------------------------------------------------------------------
        print("\n[Test 10] All Four Telephony Scenarios Simulated Call Tests (Vapi & Retell)")

        # 10.1 Scenario 1: Marketplace Number
        print("  --- Scenario 1: Marketplace Concierge ---")
        server.DEPLOYMENT_MODE = "marketplace"
        server.CALL_MODE = "marketplace"

        # 10.1a Greeting check
        res_mkt_greet = await client.post("/webhook", json={"message": {"type": "assistant-request"}}, headers=headers)
        assert res_mkt_greet.status_code == 200
        mkt_greet_text = res_mkt_greet.json()["assistant"]["firstMessage"]
        assert "Welcome to HealthNetwork AI" in mkt_greet_text
        print("    [OK] Scenario 1 Greeting: 'Welcome to HealthNetwork AI...'")

        # 10.1b find_clinic by area, specialty, and doctor name
        for q_type, q_args in [
            ("area", {"area": "Downtown"}),
            ("specialty", {"specialty": "Routine Care"}),
            ("doctor", {"name": "Doctor Steve"})
        ]:
            mkt_find_payload = {
                "message": {
                    "type": "tool-calls",
                    "toolCalls": [
                        {
                            "id": f"c_find_{q_type}",
                            "function": {"name": "find_clinic", "arguments": q_args}
                        }
                    ]
                }
            }
            res_find = await client.post("/webhook", json=mkt_find_payload, headers=headers)
            assert res_find.status_code == 200
            find_res = res_find.json()["results"][0]["result"]
            assert "available clinics" in find_res.lower()
            print(f"    [OK] find_clinic by {q_type}: returned directory recommendations")

        # 10.1c Book appointment via Vapi in marketplace mode
        book_mkt_payload = {
            "message": {
                "type": "tool-calls",
                "toolCalls": [
                    {
                        "id": "c_book_mkt",
                        "function": {
                            "name": "book_appointment",
                            "arguments": {
                                "patient_name": "Alice Walker",
                                "phone": "+923211112233",
                                "provider": "Doctor Steve",
                                "date": valid_date_str,
                                "time": "11:00 AM",
                                "reason": "General consultation"
                            }
                        }
                    }
                ]
            }
        }
        res_b_mkt = await client.post("/webhook", json=book_mkt_payload, headers=headers)
        assert res_b_mkt.status_code == 200
        assert "confirmed" in res_b_mkt.json()["results"][0]["result"].lower()
        print("    [OK] Marketplace booking via Vapi confirmed")

        # 10.1d Retell marketplace tool calls
        retell_find_res = await client.post(
            "/webhook/retell",
            json={"name": "find_clinic", "args": {"area": "Gulshan"}, "tool_call_id": "retell_find_1"},
            headers=headers
        )
        assert retell_find_res.status_code == 200
        assert "result" in retell_find_res.json()
        assert retell_find_res.json()["tool_call_id"] == "retell_find_1"
        print("    [OK] Marketplace find_clinic via Retell payload succeeded")

        server.DEPLOYMENT_MODE = "single_hospital"

        # 10.2 Scenario 2: Call Forwarding (Overflow, After-Hours, Full Forwarding)
        print("  --- Scenario 2: Carrier Call Forwarding ---")

        # 10.2a Overflow mode (after 4 rings)
        server.CALL_MODE = "overflow"
        res_of_greet = await client.post("/webhook", json={"message": {"type": "assistant-request"}}, headers=headers)
        assert "Thank you for waiting, how can I help you today?" in res_of_greet.json()["assistant"]["firstMessage"]
        book_of_payload = {
            "message": {
                "type": "tool-calls",
                "toolCalls": [{
                    "id": "c_book_of",
                    "function": {
                        "name": "book_appointment",
                        "arguments": {
                            "patient_name": "Bob Vance",
                            "phone": "+923334445566",
                            "provider": "Doctor Steve",
                            "date": valid_date_str,
                            "time": "11:30 AM",
                            "reason": "Follow-up"
                        }
                    }
                }]
            }
        }
        res_b_of = await client.post("/webhook", json=book_of_payload, headers=headers)
        assert "confirmed" in res_b_of.json()["results"][0]["result"].lower()
        print("    [OK] Overflow Mode Greeting & Booking confirmed")

        # 10.2b After-hours mode
        server.CALL_MODE = "after_hours"
        res_ah_greet = await client.post("/webhook", json={"message": {"type": "assistant-request"}}, headers=headers)
        assert "our clinic is closed right now" in res_ah_greet.json()["assistant"]["firstMessage"]
        book_ah_payload = {
            "name": "book_appointment",
            "args": {
                "patient_name": "Carol Danvers",
                "phone": "+923445556677",
                "provider": "Nurse Maha",
                "date": valid_date_str,
                "time": "09:30 AM",
                "reason": "Blood pressure check"
            },
            "tool_call_id": "retell_ah_1"
        }
        res_b_ah = await client.post("/webhook/retell", json=book_ah_payload, headers=headers)
        assert "confirmed" in res_b_ah.json()["result"].lower()
        print("    [OK] After-Hours Mode Greeting & Retell Booking confirmed")

        # 10.2c Full forwarding / normal mode
        server.CALL_MODE = "normal"
        res_norm_greet = await client.post("/webhook", json={"message": {"type": "assistant-request"}}, headers=headers)
        assert "How can I help you today?" in res_norm_greet.json()["assistant"]["firstMessage"]
        print("    [OK] Full Forwarding (Normal Mode) Greeting confirmed")

        # 10.3 Scenario 3: Cloud PBX / SIP Trunk
        print("  --- Scenario 3: Cloud PBX / SIP Trunk ---")
        pbx_payload = {
            "message": {
                "type": "tool-calls",
                "call": {
                    "id": "pbx_call_101",
                    "sipHeaders": {"X-PBX-Extension": "101", "X-GateWay": "198.51.100.10"}
                },
                "toolCalls": [
                    {
                        "id": "c_pbx_transfer",
                        "function": {
                            "name": "prepare_warm_transfer",
                            "arguments": {"caller_issue": "Caller requests transfer to internal reception desk"}
                        }
                    }
                ]
            }
        }
        res_pbx = await client.post("/webhook", json=pbx_payload, headers=headers)
        assert res_pbx.status_code == 200
        pbx_res = res_pbx.json()["results"][0]["result"]
        assert "connecting you to our front desk" in pbx_res.lower()

        # Human escalation request via Retell
        human_req_payload = {
            "name": "prepare_warm_transfer",
            "args": {"caller_issue": "Caller explicitly requested to speak to a human representative"},
            "tool_call_id": "retell_human_transfer"
        }
        res_retell_human = await client.post("/webhook/retell", json=human_req_payload, headers=headers)
        assert res_retell_human.status_code == 200
        assert "connecting you to our front desk" in res_retell_human.json()["result"].lower()
        print("    [OK] Cloud PBX Warm Transfer & Human Escalation verified")

        # 10.4 Scenario 4: BYOC (Twilio / Telnyx / Plivo)
        print("  --- Scenario 4: BYOC Ingress ---")
        byoc_payload = {
            "message": {
                "type": "tool-calls",
                "call": {
                    "id": "byoc_call_twilio",
                    "provider": "twilio",
                    "from": "+14155550188"
                },
                "toolCalls": [
                    {
                        "id": "c_byoc_check",
                        "function": {
                            "name": "check_availability",
                            "arguments": {"provider": "Doctor Steve", "date": valid_date_str}
                        }
                    }
                ]
            }
        }
        res_byoc = await client.post("/webhook", json=byoc_payload, headers=headers)
        assert res_byoc.status_code == 200
        byoc_check_res = res_byoc.json()["results"][0]["result"]
        assert "doctor steve has openings" in byoc_check_res.lower()
        print("    [OK] BYOC Ingress payload processed identically to native calls")

        # 10.5 Edge Cases
        print("  --- Edge Cases & Guardrails ---")

        # Edge Case 1: Bad secret rejection
        bad_headers = {"x-vapi-secret": "wrong_secret_unauthorized"}
        res_bad_sec_vapi = await client.post("/webhook", json={}, headers=bad_headers)
        assert res_bad_sec_vapi.status_code == 401
        res_bad_sec_retell = await client.post("/webhook/retell", json={}, headers=bad_headers)
        assert res_bad_sec_retell.status_code == 401
        print("    [OK] Bad Webhook Secret correctly rejected with HTTP 401 Unauthorized")

        # Edge Case 2: Missing field in booking
        missing_payload = {
            "name": "book_appointment",
            "args": {"patient_name": "No Date Patient", "phone": "+923001112233", "provider": "Doctor Steve"},
            "tool_call_id": "missing_1"
        }
        res_missing = await client.post("/webhook/retell", json=missing_payload, headers=headers)
        assert res_missing.status_code == 200
        assert "date" in res_missing.json()["result"].lower()
        print("    [OK] Missing booking field handled with clear guidance")

        # Edge Case 3: Sunday date rejection
        res_sun_check = server.check_availability("Doctor Steve", sun_date_str)
        assert res_sun_check["status"] == "closed"
        assert "closed on sundays" in res_sun_check["message"].lower()
        print("    [OK] Sunday date check returns clinic closed message")

        # Edge Case 4: Past date rejection
        res_past_book = server.book_appointment("Old Patient", "+923001112233", "Doctor Steve", "2020-01-01", "10:00 AM", "Old visit")
        assert res_past_book["status"] == "error"
        assert "past date" in res_past_book["message"].lower()
        print("    [OK] Past date booking rejected")

        # Edge Case 5: Nurse Maha scope guardrail
        res_maha_scope = server.book_appointment(
            "Cardiac Patient",
            "+923001112233",
            "Nurse Maha",
            valid_date_str,
            "14:00",
            "Severe chest pain and complex medical consultation"
        )
        assert res_maha_scope["status"] == "error"
        assert "doctor steve" in res_maha_scope["message"].lower()
        print("    [OK] Nurse Maha clinical scope guardrail redirected complex consultation to Doctor Steve")

        # Edge Case 6: Multilingual provider normalization (Urdu, Arabic, French, Spanish)
        assert server.normalize_provider("نرس ماہا") == "Nurse Maha"
        assert server.normalize_provider("ڈاکٹر اسٹیو") == "Doctor Steve"
        assert server.normalize_provider("الممرضة مها") == "Nurse Maha"
        assert server.normalize_provider("الدكتور ستيف") == "Doctor Steve"
        assert server.normalize_provider("l'infirmière Maha") == "Nurse Maha"
        assert server.normalize_provider("Docteur Steve") == "Doctor Steve"
        assert server.normalize_provider("enfermera Maha") == "Nurse Maha"
        assert server.normalize_provider("Médico Steve") == "Doctor Steve"
        print("    [OK] Multilingual provider normalization verified across Urdu, Arabic, French, and Spanish")

        # Edge Case 7: Multilingual Nurse Maha scope guardrail (Urdu & Arabic symptoms)
        res_urdu_scope = server.book_appointment("Ali", "+923001112233", "نرس ماہا", valid_date_str, "14:30", "تیز بخار اور ڈاکٹر سے مشورہ")
        assert res_urdu_scope["status"] == "error"
        assert "doctor steve" in res_urdu_scope["message"].lower()
        print("    [OK] Multilingual scope guardrail correctly caught Urdu illness/consultation for Nurse Maha")

        # ----------------------------------------------------------------------
        # TEST 11: STEDI INSURANCE CHECKS (TEST MODE ONLY - MOCKED RESPONSES)
        # ----------------------------------------------------------------------
        print("\n[Test 11] Stedi Insurance Eligibility Verification (Test Mode)")

        # 11a: Success 200 OK (Active Coverage, Copay $25, Deductible $500)
        mock_stedi_200 = MagicMock()
        mock_stedi_200.status_code = 200
        mock_stedi_200.json.return_value = {
            "plans": [
                {
                    "benefits": {
                        "statuses": [{"status": "ACTIVE_COVERAGE"}],
                        "coPayment": [{"amount": 25.0}],
                        "deductible": [{"amount": 500.0}]
                    }
                }
            ]
        }

        with patch("httpx.Client") as mock_http:
            mock_http.return_value.__enter__.return_value.post.return_value = mock_stedi_200
            res_ins_200 = stedi_client.check_eligibility_mock(
                payer="Aetna",
                member_id="AETNA9wcSu",
                patient_name="John Doe",
                api_key="test_mock_valid_key"
            )
            assert res_ins_200["status"] == "active"
            assert res_ins_200["payer"] == "Aetna"
            assert res_ins_200["masked_member_id"] == "******wcSu"
            assert res_ins_200["copay"] == 25.0
            assert res_ins_200["deductible"] == 500.0
            assert "Your coverage with Aetna is active" in res_ins_200["message"]
            assert "$25" in res_ins_200["message"]
            assert "$500" in res_ins_200["message"]
            print("  [OK] Mock 200: Active coverage parsed with copay $25 and deductible $500")

        # 11b: Subscriber Not Found (AAA 75 rejectReasonCode)
        mock_stedi_400 = MagicMock()
        mock_stedi_400.status_code = 400
        mock_stedi_400.json.return_value = {
            "aaa": [{"rejectReasonCode": "75", "followupAction": "Subscriber/Insured Not Found"}]
        }

        with patch("httpx.Client") as mock_http:
            mock_http.return_value.__enter__.return_value.post.return_value = mock_stedi_400
            res_ins_notfound = stedi_client.check_eligibility_mock(
                payer="UnitedHealthcare",
                member_id="UHCAAA75",
                patient_name="Unknown Patient",
                api_key="test_mock_valid_key"
            )
            assert res_ins_notfound["status"] == "not_found"
            assert "could not verify that member id" in res_ins_notfound["message"].lower()
            assert "front desk" in res_ins_notfound["message"].lower()
            print("  [OK] Mock AAA 75: Subscriber Not Found handled calmly with front desk offer")

        # 11c: Network Timeout
        with patch("httpx.Client") as mock_http:
            mock_http.return_value.__enter__.return_value.post.side_effect = httpx.TimeoutException("Connection timed out")
            res_ins_timeout = stedi_client.check_eligibility_mock(
                payer="Cigna",
                member_id="CIGNAJTUxNm",
                patient_name="Jordan Doe",
                api_key="test_mock_valid_key"
            )
            assert res_ins_timeout["status"] == "timeout"
            assert "trouble reaching the insurance verification service" in res_ins_timeout["message"].lower()
            assert "front desk" in res_ins_timeout["message"].lower()
            print("  [OK] Timeout Exception: Caught gracefully and escalated to front desk")

        # 11d: Invalid / Bad API Key (401 Unauthorized)
        mock_stedi_401 = MagicMock()
        mock_stedi_401.status_code = 401
        mock_stedi_401.json.return_value = {"message": "Invalid API Key"}

        with patch("httpx.Client") as mock_http:
            mock_http.return_value.__enter__.return_value.post.return_value = mock_stedi_401
            res_ins_badkey = stedi_client.check_eligibility_mock(
                payer="Aetna",
                member_id="AETNA9wcSu",
                patient_name="John Doe",
                api_key="test_bad_key"
            )
            assert res_ins_badkey["status"] == "bad_key"
            assert "trouble validating your insurance details" in res_ins_badkey["message"].lower()
            print("  [OK] Bad API Key: Caught gracefully with front desk offer")

        # 11e: Unsupported Payer
        res_ins_unsupported = stedi_client.check_eligibility_mock(
            payer="UnknownRegionalInsurance",
            member_id="12345678",
            patient_name="Jane Doe",
            api_key="test_mock_valid_key"
        )
        assert res_ins_unsupported["status"] == "unsupported_payer"
        assert "Aetna, Cigna, UnitedHealthcare, and Medicare" in res_ins_unsupported["message"]
        print("  [OK] Unsupported Payer: Returns supported list and offers front desk")

        # 11f: Member ID Masking Verification
        assert stedi_client.mask_member_id("AETNA9wcSu") == "******wcSu"
        assert stedi_client.mask_member_id("UHC202649") == "*****2649"
        assert stedi_client.mask_member_id("123") == "****"
        print("  [OK] Member ID Masking verified (only last 4 characters preserved)")

        # 11g: End-to-End check_insurance tool via Vapi & Retell Webhooks
        with patch("stedi_client.check_eligibility_mock") as mock_check:
            mock_check.return_value = {
                "status": "active",
                "payer": "Aetna",
                "masked_member_id": "******wcSu",
                "copay": 25.0,
                "deductible": 500.0,
                "message": "Your coverage with Aetna is active. Your copay is $25 and your remaining deductible is $500."
            }

            # Vapi webhook
            ins_vapi_payload = {
                "message": {
                    "type": "tool-calls",
                    "toolCalls": [
                        {
                            "id": "c_ins_1",
                            "function": {
                                "name": "check_insurance",
                                "arguments": {
                                    "payer": "Aetna",
                                    "member_id": "AETNA9wcSu",
                                    "patient_name": "John Doe"
                                }
                            }
                        }
                    ]
                }
            }
            res_vapi_ins = await client.post("/webhook", json=ins_vapi_payload, headers=headers)
            assert res_vapi_ins.status_code == 200
            vapi_ins_res = res_vapi_ins.json()["results"][0]["result"]
            assert "coverage with aetna is active" in vapi_ins_res.lower()
            print("  [OK] Vapi Webhook check_insurance tool call verified")

            # Retell webhook
            ins_retell_payload = {
                "name": "check_insurance",
                "args": {
                    "payer": "Aetna",
                    "member_id": "AETNA9wcSu",
                    "patient_name": "John Doe"
                },
                "tool_call_id": "retell_ins_1"
            }
            res_retell_ins = await client.post("/webhook/retell", json=ins_retell_payload, headers=headers)
            assert res_retell_ins.status_code == 200
            assert "coverage with aetna is active" in res_retell_ins.json()["result"].lower()
            print("  [OK] Retell Webhook check_insurance tool call verified")

    # Clean up test appointments
    save_appointments([])
    server.CALL_MODE = orig_call_mode
    server.DEPLOYMENT_MODE = orig_dep_mode

    print("\n" + "=" * 70)
    print("ALL 11 TEST SUITES PASSED SUCCESSFULLY! (100% PASS RATE)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
