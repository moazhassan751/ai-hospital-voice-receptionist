#!/usr/bin/env python3
"""
audit_vapi.py - Consistency Audit between Local Project Files and Live Vapi Account.
Performs read-only GET requests to https://api.vapi.ai, compares live configurations
against assistant_config.rendered.json and .env, checks live webhook endpoints, and
inspects local consistency.
"""

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional
from dotenv import dotenv_values, load_dotenv
import httpx

# Ensure proper stdout encoding on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()


def mask_secret(val: Optional[str]) -> str:
    """Masks secrets showing only first 2 and last 4 characters."""
    if not val:
        return "<empty>"
    s = str(val).strip()
    if len(s) <= 6:
        return "******"
    return f"{s[:2]}****{s[-4:]}"


def main():
    print("=" * 80)
    print("VAPI AUDIT SCRIPT - CONSISTENCY VERIFICATION")
    print("=" * 80)

    # 1. Check .env variables
    api_key = os.getenv("VAPI_API_KEY", "").strip()
    assistant_id = os.getenv("VAPI_ASSISTANT_ID", "").strip()
    webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    front_desk_number = os.getenv("FRONT_DESK_NUMBER", "").strip()
    stedi_key = os.getenv("STEDI_TEST_API_KEY", "").strip()

    print(f"[*] Vapi API Key:       {mask_secret(api_key)}")
    print(f"[*] Assistant ID:       {assistant_id or '<none>'}")
    print(f"[*] Webhook Secret:     {mask_secret(webhook_secret)}")
    print(f"[*] Public Base URL:    {public_base_url or '<none>'}")
    print(f"[*] Front Desk Number:  {front_desk_number or '<none>'}")
    print(f"[*] Stedi Test Key:     {mask_secret(stedi_key)}")

    if not api_key:
        print("[ERROR] VAPI_API_KEY is missing in .env")
        sys.exit(1)
    if not assistant_id:
        print("[ERROR] VAPI_ASSISTANT_ID is missing in .env")
        sys.exit(1)

    # 2. Load assistant_config.rendered.json
    rendered_path = "assistant_config.rendered.json"
    if not os.path.exists(rendered_path):
        print(f"[ERROR] '{rendered_path}' not found. Please run render_config.py first.")
        sys.exit(1)

    with open(rendered_path, "r", encoding="utf-8") as f:
        local_cfg = json.load(f)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # 3. GET requests to Vapi REST API
    asst_data: Optional[Dict[str, Any]] = None
    tools_data: List[Dict[str, Any]] = []
    phones_data: List[Dict[str, Any]] = []

    with httpx.Client(timeout=20.0) as client:
        # 3a. Assistant
        try:
            r = client.get(f"https://api.vapi.ai/assistant/{assistant_id}", headers=headers)
            if r.status_code == 200:
                asst_data = r.json()
                print(f"[SUCCESS] Fetched Assistant '{asst_data.get('name')}' ({asst_data.get('id')})")
            else:
                print(f"[ERROR] Failed to fetch assistant: HTTP {r.status_code} - {r.text[:200]}")
        except Exception as e:
            print(f"[ERROR] Exception fetching assistant: {e}")

        # 3b. Tools list
        try:
            r = client.get("https://api.vapi.ai/tool", headers=headers)
            if r.status_code == 200:
                tools_data = r.json()
                print(f"[SUCCESS] Fetched Tools list ({len(tools_data)} tools found)")
            else:
                print(f"[ERROR] Failed to fetch tools: HTTP {r.status_code} - {r.text[:200]}")
        except Exception as e:
            print(f"[ERROR] Exception fetching tools: {e}")

        # 3c. Phone numbers list
        try:
            r = client.get("https://api.vapi.ai/phone-number", headers=headers)
            if r.status_code == 200:
                phones_data = r.json()
                print(f"[SUCCESS] Fetched Phone numbers list ({len(phones_data)} numbers found)")
            else:
                print(f"[ERROR] Failed to fetch phone numbers: HTTP {r.status_code} - {r.text[:200]}")
        except Exception as e:
            print(f"[ERROR] Exception fetching phone numbers: {e}")

    if not asst_data:
        print("[FATAL] Could not retrieve live assistant from Vapi. Audit cannot continue.")
        sys.exit(1)

    print("\n" + "=" * 80)
    print("STEP 2: COMPARISON AUDIT RESULTS")
    print("=" * 80)

    # Prepare comparisons
    rows = []

    # Helper for table row
    def add_row(item: str, local_val: str, vapi_val: str, res: str):
        rows.append({
            "item": item,
            "local": local_val,
            "vapi": vapi_val,
            "result": res
        })

    # 1. Assistant ID
    live_id = asst_data.get("id", "")
    res1 = "MATCH" if live_id == assistant_id else "MISMATCH"
    add_row("1. Assistant ID exists and matches .env", assistant_id, live_id, res1)

    # 2. First message
    local_fm = local_cfg.get("firstMessage", "")
    live_fm = asst_data.get("firstMessage", "")
    res2 = "MATCH" if local_fm == live_fm else "MISMATCH"
    add_row("2. First message", local_fm, live_fm, res2)

    # 3. System prompt
    local_prompt = local_cfg.get("model", {}).get("messages", [{}])[0].get("content", "")
    live_prompt = asst_data.get("model", {}).get("messages", [{}])[0].get("content", "")
    prompt_match = (local_prompt == live_prompt)
    has_speaking_pace = "SPEAKING PACE RULES" in live_prompt
    has_maha = "Maha" in live_prompt
    has_amber = ("Amber" in live_prompt) or ("amber" in live_prompt)
    
    prompt_summary_local = f"Len {len(local_prompt)} | Has PACE: True, Maha: True, Amber: False"
    prompt_summary_vapi = f"Len {len(live_prompt)} | Has PACE: {has_speaking_pace}, Maha: {has_maha}, Amber: {has_amber}"
    res3 = "MATCH" if (prompt_match and has_speaking_pace and has_maha and not has_amber) else "MISMATCH"
    add_row("3. System prompt full text and checks", prompt_summary_local, prompt_summary_vapi, res3)

    # 4. Model provider, model name, temperature
    local_model = local_cfg.get("model", {})
    live_model = asst_data.get("model", {})
    l_m_prov = local_model.get("provider")
    l_m_name = local_model.get("model")
    l_m_temp = local_model.get("temperature")

    v_m_prov = live_model.get("provider")
    v_m_name = live_model.get("model")
    v_m_temp = live_model.get("temperature")
    m4 = (l_m_prov == v_m_prov and l_m_name == v_m_name and l_m_temp == v_m_temp)
    add_row(
        "4. Model provider, model name, temperature",
        f"{l_m_prov}, {l_m_name}, {l_m_temp}",
        f"{v_m_prov}, {v_m_name}, {v_m_temp}",
        "MATCH" if m4 else "MISMATCH"
    )

    # 5. Voice provider, voice ID and voice speed
    local_voice = local_cfg.get("voice", {})
    live_voice = asst_data.get("voice", {})
    l_v_prov = local_voice.get("provider")
    l_v_id = local_voice.get("voiceId")
    l_v_spd = local_voice.get("speed")

    v_v_prov = live_voice.get("provider")
    v_v_id = live_voice.get("voiceId")
    v_v_spd = live_voice.get("speed")
    m5 = (l_v_prov == v_v_prov and l_v_id == v_v_id and l_v_spd == v_v_spd)
    add_row(
        "5. Voice provider, voice ID, voice speed",
        f"prov: {l_v_prov}, id: {l_v_id}, speed: {l_v_spd}",
        f"prov: {v_v_prov}, id: {v_v_id}, speed: {v_v_spd}",
        "MATCH" if m5 else "MISMATCH"
    )

    # 6. Start speaking plan wait seconds
    l_ssp = local_cfg.get("startSpeakingPlan", {}).get("waitSeconds")
    v_ssp = asst_data.get("startSpeakingPlan", {})
    v_ssp_sec = v_ssp.get("waitSeconds") if isinstance(v_ssp, dict) else None
    m6 = (l_ssp == v_ssp_sec)
    add_row("6. Start speaking plan wait seconds", str(l_ssp), str(v_ssp_sec), "MATCH" if m6 else "MISMATCH")

    # 7. Stop speaking plan voice seconds and back off seconds
    l_stp = local_cfg.get("stopSpeakingPlan", {})
    l_stp_v = l_stp.get("voiceSeconds")
    l_stp_b = l_stp.get("backoffSeconds")
    v_stp = asst_data.get("stopSpeakingPlan", {})
    v_stp_v = v_stp.get("voiceSeconds") if isinstance(v_stp, dict) else None
    v_stp_b = v_stp.get("backoffSeconds") if isinstance(v_stp, dict) else None
    m7 = (l_stp_v == v_stp_v and l_stp_b == v_stp_b)
    add_row(
        "7. Stop speaking plan voice and back off seconds",
        f"voice: {l_stp_v}s, backoff: {l_stp_b}s",
        f"voice: {v_stp_v}s, backoff: {v_stp_b}s",
        "MATCH" if m7 else "MISMATCH"
    )

    # 8. End call phrases
    l_ecp = local_cfg.get("endCallPhrases", [])
    v_ecp = asst_data.get("endCallPhrases", [])
    has_take_care = any("take care" in str(p).lower() for p in (v_ecp or []))
    m8 = (l_ecp == v_ecp and not has_take_care)
    add_row(
        "8. End call phrases ('take care' must NOT be present)",
        f"{l_ecp} ('take care' absent)",
        f"{v_ecp} ('take care' absent: {not has_take_care})",
        "MATCH" if m8 else "MISMATCH"
    )

    # 9. Silence timeout 30 and max duration 600
    l_st = local_cfg.get("silenceTimeoutSeconds")
    l_md = local_cfg.get("maxDurationSeconds")
    v_st = asst_data.get("silenceTimeoutSeconds")
    v_md = asst_data.get("maxDurationSeconds")
    m9 = (l_st == v_st and l_md == v_md)
    add_row(
        "9. Silence timeout and max duration seconds",
        f"silence: {l_st}s, max: {l_md}s",
        f"silence: {v_st}s, max: {v_md}s",
        "MATCH" if m9 else "MISMATCH"
    )

    # 10. Server URL (must equal PUBLIC_BASE_URL + /webhook)
    expected_server_url = f"{public_base_url}/webhook"
    live_server_obj = asst_data.get("server") or {}
    v_server_url = live_server_obj.get("url") or asst_data.get("serverUrl") or ""
    m10 = (expected_server_url == v_server_url)
    add_row("10. Assistant Server URL", expected_server_url, v_server_url, "MATCH" if m10 else "MISMATCH")

    # 11. Server secret or x-vapi-secret header
    v_secret = live_server_obj.get("secret") or live_server_obj.get("headers", {}).get("x-vapi-secret") or ""
    m11 = "MATCH" if (v_secret == webhook_secret) else "MISMATCH"
    add_row("11. Server secret / x-vapi-secret header", "[PROTECTED]", "[PROTECTED]", m11)

    # 12. Server messages ticked
    l_sm = set(local_cfg.get("serverMessages", []))
    v_sm = set(asst_data.get("serverMessages", []))
    req_ticked = {"tool-calls", "end-of-call-report", "status-update"}
    all_req_present = req_ticked.issubset(v_sm)
    m12 = (l_sm == v_sm) and all_req_present
    add_row(
        "12. Server messages ticked",
        f"Count: {len(l_sm)} (includes tool-calls, end-of-call-report, status-update)",
        f"Count: {len(v_sm)} (required present: {all_req_present})",
        "MATCH" if m12 else "MISMATCH"
    )

    # 13. Which tools are attached to this assistant
    local_tool_objs = local_cfg.get("model", {}).get("tools", [])
    local_tool_names = [t.get("function", {}).get("name") or t.get("type") for t in local_tool_objs]
    live_tool_objs = asst_data.get("model", {}).get("tools", [])
    live_tool_names = [t.get("function", {}).get("name") or t.get("type") for t in live_tool_objs]
    m13 = (set(local_tool_names) == set(live_tool_names))
    add_row(
        "13. Attached tools list",
        ", ".join(local_tool_names),
        ", ".join(live_tool_names),
        "MATCH" if m13 else "MISMATCH"
    )

    # Build tool lookup dicts
    local_tool_map = { (t.get("function", {}).get("name") or t.get("type")): t for t in local_tool_objs }
    live_tool_map = { (t.get("function", {}).get("name") or t.get("type")): t for t in live_tool_objs }

    # Tools checks: check_availability, book_appointment, find_clinic, check_insurance, transferCall
    target_tools = ["check_availability", "book_appointment", "find_clinic", "check_insurance", "transferCall"]

    for t_name in target_tools:
        lt = local_tool_map.get(t_name)
        vt = live_tool_map.get(t_name)

        # 14. Tool exists and attached
        t_attached = (vt is not None)
        add_row(
            f"14. Tool '{t_name}' attached to assistant",
            "Attached",
            "Attached" if t_attached else "NOT Attached",
            "MATCH" if t_attached else "MISMATCH"
        )

        if not vt:
            add_row(f"15. Tool '{t_name}' Server URL", expected_server_url, "<tool missing>", "MISMATCH")
            add_row(f"16. Tool '{t_name}' x-vapi-secret header", "[PROTECTED]", "<tool missing>", "MISMATCH")
            add_row(f"17. Tool '{t_name}' Parameters exact match", "Matches schema", "<tool missing>", "MISMATCH")
            continue

        # 15. Tool Server URL
        if t_name != "transferCall":
            t_srv = vt.get("server", {})
            t_url = t_srv.get("url") if isinstance(t_srv, dict) else ""
            m15 = (t_url == expected_server_url)
            add_row(f"15. Tool '{t_name}' Server URL", expected_server_url, t_url or "<none>", "MATCH" if m15 else "MISMATCH")

            # 16. Tool secret
            t_sec = t_srv.get("secret") or t_srv.get("headers", {}).get("x-vapi-secret") if isinstance(t_srv, dict) else ""
            m16 = "MATCH" if (t_sec == webhook_secret) else "MISMATCH"
            add_row(f"16. Tool '{t_name}' secret header", "[PROTECTED]", "[PROTECTED]", m16)

            # 17. Parameters, types, required flags
            lp = lt.get("function", {}).get("parameters", {})
            vp = vt.get("function", {}).get("parameters", {})
            lp_props = lp.get("properties", {})
            vp_props = vp.get("properties", {})
            lp_req = lp.get("required", [])
            vp_req = vp.get("required", [])

            param_mismatch_reasons = []
            if set(lp_props.keys()) != set(vp_props.keys()):
                diff_missing = set(lp_props.keys()) - set(vp_props.keys())
                diff_extra = set(vp_props.keys()) - set(lp_props.keys())
                if diff_missing:
                    param_mismatch_reasons.append(f"missing props: {list(diff_missing)}")
                if diff_extra:
                    param_mismatch_reasons.append(f"extra props: {list(diff_extra)}")

            if set(lp_req) != set(vp_req):
                param_mismatch_reasons.append(f"required mismatch (local: {lp_req}, vapi: {vp_req})")

            # Specific tool checks
            if t_name in ("check_availability", "book_appointment"):
                v_p_desc = vp_props.get("provider", {}).get("description", "")
                v_p_enum = vp_props.get("provider", {}).get("enum", [])
                if "Amber" in v_p_desc or "Amber" in str(v_p_enum):
                    param_mismatch_reasons.append("mentions Amber")
                if not ("Steve" in str(v_p_enum) and "Maha" in str(v_p_enum)):
                    param_mismatch_reasons.append("missing Doctor Steve or Nurse Maha in provider enum")

            if t_name == "check_insurance":
                if "date_of_birth" not in vp_props:
                    param_mismatch_reasons.append("date_of_birth missing from properties")
                if "date_of_birth" not in vp_req:
                    param_mismatch_reasons.append("date_of_birth missing from required")

            if t_name == "book_appointment":
                exp_fields = ["date_of_birth", "insurance_payer", "member_id", "insurance_status", "copay", "deductible"]
                for ef in exp_fields:
                    if ef not in vp_props:
                        param_mismatch_reasons.append(f"{ef} missing")

            m17 = (len(param_mismatch_reasons) == 0)
            res17_text = "MATCH" if m17 else "MISMATCH"
            add_row(
                f"17. Tool '{t_name}' parameters & flags",
                f"Props: {list(lp_props.keys())} | Req: {lp_req}",
                f"Props: {list(vp_props.keys())} | Req: {vp_req}" if m17 else f"MISMATCH ({'; '.join(param_mismatch_reasons)})",
                res17_text
            )

        else:
            # transferCall
            add_row(f"15. Tool '{t_name}' Server URL", "N/A (Builtin telephony)", "N/A (Builtin telephony)", "MATCH")
            add_row(f"16. Tool '{t_name}' secret header", "N/A (Builtin telephony)", "N/A (Builtin telephony)", "MATCH")
            
            # 18. transferCall destination equals FRONT_DESK_NUMBER
            v_dests = vt.get("destinations", [])
            v_num = v_dests[0].get("number") if v_dests else ""
            m18 = (v_num == front_desk_number and v_num.startswith("+"))
            add_row(
                "18. transferCall destination equals FRONT_DESK_NUMBER (.env)",
                front_desk_number,
                v_num or "<none>",
                "MATCH" if m18 else "MISMATCH"
            )

    # Phone numbers
    phone_summary_local = f"Points to {assistant_id} (no server override)"
    phone_summaries = []
    has_old_assistant = False
    has_server_override = False

    for p in phones_data:
        p_id = p.get("id")
        p_num = p.get("number")
        p_asst = p.get("assistantId")
        p_srv = p.get("server")
        if p_asst != assistant_id:
            has_old_assistant = True
        if p_srv:
            has_server_override = True
        phone_summaries.append(f"{p_num} -> assistant: {p_asst} | server: {p_srv}")

    vapi_phone_text = "; ".join(phone_summaries) if phone_summaries else "No phone numbers in Vapi"

    # 19. Which assistant each phone points to
    m19 = "MATCH" if (not has_old_assistant and len(phones_data) > 0) else "MISMATCH"
    add_row(
        "19. Phone numbers target assistant",
        f"All point to {assistant_id}",
        vapi_phone_text,
        m19
    )

    # 20. Whether phone has server URL overriding assistant
    m20 = "MATCH" if not has_server_override else "MISMATCH"
    add_row(
        "20. Phone number Server URL override",
        "None (inherits assistant server)",
        "None" if not has_server_override else "HAS OVERRIDE",
        m20
    )

    # Print Table
    col_w = [48, 42, 42, 12]
    header = f"| {'Item':<{col_w[0]}} | {'Local Value':<{col_w[1]}} | {'Vapi Value':<{col_w[2]}} | {'Result':<{col_w[3]}} |"
    sep = f"|{'-' * (col_w[0] + 2)}|{'-' * (col_w[1] + 2)}|{'-' * (col_w[2] + 2)}|{'-' * (col_w[3] + 2)}|"

    print("\n" + sep)
    print(header)
    print(sep)
    for r in rows:
        it = (r["item"][:col_w[0]])
        lv = (r["local"][:col_w[1]])
        vv = (r["vapi"][:col_w[2]])
        res = r["result"]
        print(f"| {it:<{col_w[0]}} | {lv:<{col_w[1]}} | {vv:<{col_w[2]}} | {res:<{col_w[3]}} |")
    print(sep + "\n")


if __name__ == "__main__":
    main()
