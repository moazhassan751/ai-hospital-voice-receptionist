# AI Hospital Voice Receptionist (Voice-Only)

A lightweight, production-ready AI voice receptionist for healthcare clinics and multi-clinic networks, built with **Vapi**, **Retell AI**, and **FastAPI**. The receptionist speaks naturally over the phone, checks provider availability, books appointments, searches clinic marketplace directories, handles warm transfers, verifies insurance eligibility in test mode, and instantly escalates medical emergencies to the front desk.

---

## 1. Key Features

- **Voice-First Design:** Short sentences, single-question flow, no markdown or emojis spoken.
- **Dual Deployment Modes:**
  - **Single Hospital (Default):** Time-of-day greeting in `Asia/Karachi` time ("good morning", "good afternoon", "good evening") for Doctor Steve and Nurse Maha.
  - **Marketplace Mode:** Multi-clinic network greeting: *"Welcome to HealthNetwork AI, are you looking for a clinic in a specific area or a specific doctor?"* with `find_clinic` tool.
- **Multilingual Intelligence:** Automatically detects and converses fluently in French, Spanish, Urdu (with Roman Urdu), Arabic, and English via Deepgram multi-language transcription and GPT-4o.
- **Dual Backend Modes:**
  - **Local Mode (`BACKEND_MODE=local`):** Persists bookings in `data.json` and `appointments.json`.
  - **Mock Mode (`BACKEND_MODE=mock`):** Forwards availability and booking calls to Mockoon or Beeceptor. On 404 returns *"That time slot was just taken, would another time work?"*; on 500 stays calm and offers front desk.
- **Multi-Platform Webhooks:**
  - `POST /webhook` (Vapi `tool-calls` and `assistant-request` schema)
  - `POST /webhook/retell` (Retell AI custom tool and inbound schema)
- **Stedi Insurance Verification (Test Mode Only):** Pre-configured mock eligibility checks for Aetna, Cigna, UnitedHealthcare, and CMS (Medicare).
- **Warm Transfer with Medical Summary:** Prepares a 1-sentence handover summary before transferring caller to the front desk.
- **Operating Hours:** Mon to Sat, 9:00 AM to 5:00 PM (30-min slots). Closed Sundays.

---

## 2. File Structure

```
hospital-voice-agent/
├── server.py                # FastAPI webhook backend (Vapi and Retell + Local/Mock modes)
├── stedi_client.py          # Stedi healthcare insurance client (Test Mode Only)
├── try_stedi_mock.py        # Manual CLI test runner for Stedi mock eligibility checks
├── show_patient.py          # Inspect a patient intake record by reference ID
├── delete_patient.py        # Remove a patient record across all data stores
├── setup_telephony.py       # Automated CLI provisioning tool for Vapi, PBX, and BYOC
├── test_server.py           # Automated test suite (12 test suites verifying all flows)
├── LIVE_TESTING.md          # Manual testing checklist and step-by-step runbook
├── assistant_config.json    # Complete Vapi and Retell assistant definitions and schemas
├── mockoon_clinic.json      # Mockoon environment export (200, 404, and 500 routes)
├── data.json                # Sample clinics directory and appointment records
├── appointments.json        # Flat JSON appointment database (synchronized)
├── patients.json            # Patient records database (full intake records, gitignored)
├── requirements.txt         # Dependencies (fastapi, uvicorn, python-dotenv, httpx, tzdata)
├── .env.example             # Template for ports, modes, secrets, and carrier credentials
├── PROGRESS.md              # Living implementation progress tracker
└── README.md                # Documentation and architecture guide
```

---

## 3. Configuration (`.env`)

Configure your environment variables in `.env`:

```env
# Front desk phone number for emergency transfers (E.164 format)
FRONT_DESK_NUMBER=+1234567890

# Hospital timezone
TIMEZONE=Asia/Karachi

# Webhook secret to authenticate requests from Vapi/Retell
WEBHOOK_SECRET=hospital_secret_123

# Execution mode: 'local' (JSON storage) or 'mock' (forwards to Mockoon)
BACKEND_MODE=local

# URL of mock server when BACKEND_MODE=mock
MOCK_URL=http://localhost:3001

# Deployment mode: 'single_hospital' or 'marketplace'
DEPLOYMENT_MODE=single_hospital

# Call mode: 'auto', 'normal', 'after_hours', 'overflow', 'marketplace'
CALL_MODE=auto

# Stedi Test Mode API Key (Never use a production key)
STEDI_TEST_API_KEY=test_your_key_here
```

---

## 4. Telephony Integration Scenarios

> **Important Architecture Principle:** The Python agent backend code (`server.py`) is **100% identical** across all four scenarios. Only the phone ingress and carrier configuration changes!

| Scenario | How It Works | Best Used For | Setup Effort |
|---|---|---|---|
| **Scenario 1: Marketplace Number** | Branded virtual number in Vapi/Retell routes across clinics | Digital healthcare directories and regional clinic networks | **Low:** Virtual number purchased directly in dashboard |
| **Scenario 2: Call Forwarding** | Existing clinic phone conditionally forwards after-hours/busy calls to AI | Small practices and solo clinics needing zero phone disruption | **Lowest:** 5 mins via carrier dialing code (e.g. `*71` / `*72`) |
| **Scenario 3: SIP Trunk / Cloud PBX** | AI registers as an internal PBX extension (e.g. Ext 101) in 3CX / FreePBX | Large hospitals with internal call queues and PBX routing | **Medium:** SIP trunk credentials configured via `setup_telephony.py` |
| **Scenario 4: BYOC (Twilio / Telnyx / Plivo)** | Hospital keeps existing carrier contract; media bridged via SIP | Enterprise healthcare networks with negotiated volume rates | **Medium:** Automated carrier import via `setup_telephony.py byoc` |

---

### Scenario 1: Marketplace Number (Aggregator / Clinic Directory)
- **Concept:** One public telephone number acts as a healthcare concierge across multiple clinics.
- **Environment Settings (`.env`):**
  ```env
  DEPLOYMENT_MODE=marketplace
  CALL_MODE=marketplace
  ```
- **What the Caller Hears:**
  *"Welcome to HealthNetwork AI, are you looking for a clinic in a specific area or a specific doctor?"*
- **Exact Steps:**
  1. Allocate an inbound phone number in Vapi or Retell dashboard.
  2. Point the Webhook URL to: `https://<your-domain>/webhook`.
  3. When callers state their location or needed care, the AI invokes `find_clinic` and assists with scheduling.

---

### Scenario 2: Call Forwarding (Small Clinic / Overflow / After-Hours)
- **Concept:** The clinic retains its existing advertised phone number. Calls forward to the AI's virtual number based on rules.
- **Environment Settings (`.env`):**
  ```env
  DEPLOYMENT_MODE=single_hospital
  CALL_MODE=auto  # Or 'normal', 'after_hours', 'overflow'
  ```
- **Forwarding Rules and What Callers Hear:**
  - **Rule A: Overflow Forwarding (Busy or 4 Rings No-Answer):**
    - Dial on clinic phone: `*71<vapi_number>` (or carrier conditional forward).
    - If clinic staff are occupied or do not pick up after 4 rings, the AI answers.
    - Caller hears: *"Thank you for waiting, how can I help you today?"*
  - **Rule B: After-Hours Forwarding (Nights and Sundays):**
    - At 5:00 PM closing, activate forward (`*72<vapi_number>` or carrier schedule).
    - Caller hears: *"Hello, [good morning/afternoon/evening], our clinic is closed right now, but I can book you an appointment, or connect you to our front desk if it's urgent."*
  - **Rule C: 24/7 AI Receptionist:**
    - Unconditional forwarding (`*72<vapi_number>`). AI answers all incoming calls.
    - Caller hears time-appropriate greeting during working hours (9 AM to 5 PM Mon to Sat) and closed notice after hours.
- **Exact Steps:**
  1. Run `python setup_telephony.py vapi-number --dry-run` to preview, then run without `--dry-run` to provision.
  2. Activate forwarding on your clinic landline or carrier dashboard.

---

### Scenario 3: Cloud PBX / SIP Trunk (3CX, FreePBX, Asterisk, RingCentral)
- **Concept:** The AI receptionist registers as an internal PBX extension (e.g. Extension `101`).
- **Environment Settings (`.env`):**
  ```env
  DEPLOYMENT_MODE=single_hospital
  CALL_MODE=auto
  SIP_GATEWAY_IP=198.51.100.10
  SIP_AUTH_USERNAME=trunk_user
  SIP_AUTH_PASSWORD=trunk_secret
  SIP_EXTENSION=101
  FRONT_DESK_NUMBER=100  # PBX extension of human reception
  ```
- **How AI Appears and Transfers:**
  - The AI operates as Extension `101`.
  - In PBX Inbound Rules: Route incoming calls or IVR Option ("Press 1 for Appointments") to Extension `101`.
  - When an emergency or human assistance is requested, the AI triggers `transferCall` directly to PBX Extension `100` (Front Desk) with a 1-sentence handover summary.
- **Exact Steps:**
  1. Add PBX credentials to `.env`.
  2. Run `python setup_telephony.py sip-trunk --dry-run` to verify payload, then deploy.
  3. In your PBX admin portal, add a SIP Trunk targeting `sip.vapi.ai:5060` and route to Extension `101`.

---

### Scenario 4: BYOC (Bring Your Own Carrier - Twilio, Telnyx, Plivo)
- **Concept:** Hospital keeps its existing carrier contract and wholesale per-minute billing.
- **Environment Settings (`.env`):**
  ```env
  DEPLOYMENT_MODE=single_hospital
  CALL_MODE=auto
  TWILIO_ACCOUNT_SID=your_twilio_account_sid_here
  TWILIO_AUTH_TOKEN=your_auth_token
  TWILIO_PHONE_NUMBER=+1234567890
  ```
- **What the Caller Hears:**
  Same dynamic greeting based on `CALL_MODE` (normal daytime greeting, after-hours notice, or overflow).
- **Exact Steps:**
  1. Add carrier credentials to `.env`.
  2. Run `python setup_telephony.py byoc --provider twilio --dry-run` to inspect API request.
  3. Run without `--dry-run` to link to your Vapi account.

---

### Dashboard Assistant Synchronization (`sync-assistant`)
To synchronize your rendered assistant configuration, system prompt, multilingual standards (Urdu, English, French, Spanish, Arabic), medical scopes (Doctor Steve & Nurse Maha), and live webhook endpoints directly to your Vapi dashboard:
1. Preview changes with masked credentials:
   ```bash
   python setup_telephony.py sync-assistant --dry-run
   ```
2. Apply live updates directly to the Vapi dashboard:
   ```bash
   python setup_telephony.py sync-assistant
   ```

---

## 5. Stedi Insurance Checks (Test Mode Limitations)

The integration includes real-time mock eligibility checking through Stedi Test Mode.

### Supported Mock Payers
- **Aetna** (Payer ID `60054`, test member ID: `AETNA9wcSu`)
- **Cigna** (Payer ID `62308`, test member ID: `CIGNAJTUxNm`)
- **UnitedHealthcare** (Payer ID `87726`, test member ID: `UHC202649`)
- **CMS / Medicare** (Payer ID `CMS`, test member ID: `1AA2CC3DD45`)
- **Subscriber Not Found Test:** Use member ID `UHCAAA75` to test the standard clearinghouse AAA 75 rejection flow.

### What Stedi Test Mode Does NOT Support
1. **No Custom Mock Data:** You cannot specify custom patient benefits, custom copay amounts, or custom deductibles in test mode. The response returns pre-canned data defined by Stedi's mock repository.
2. **No Arbitrary Payer Selection:** Only the specific mock payers listed above are supported in test mode. Unlisted payers will return an error.
3. **No Coordination of Benefits (COB):** Secondary and tertiary insurance checks are not simulated in test mode.
4. **No Claim Status (276/277):** Test mode does not support claim status inquiries or remittance advice.
5. **Test Claims Need Production Account:** Submitting test insurance claims (837) requires a production Stedi clearinghouse agreement and payer enrollment.

---

## 6. Privacy and Compliance

> [!WARNING]
> This repository is a technical demonstration and prototype. It is NOT certified for production HIPAA compliance, GDPR compliance, or medical practice deployment without formal security review, legal agreements, and infrastructural hardening.

### 1. Call Recording Consent
- In many jurisdictions (including two-party consent states in the United States), recording telephone conversations requires explicit caller consent.
- If call audio recording or automated transcription is enabled in Vapi or Retell dashboards, you must update the initial greeting to inform the caller: *"This call may be recorded for quality and training purposes."*

### 2. What Patient Data is Stored
- The backend stores appointments in flat JSON files: `appointments.json` and `data.json`.
- Each appointment record contains: `appointment_id`, `patient_name`, `phone`, `provider`, `date`, `time`, `reason`, and `created_at`.
- Full patient intake records are stored in `patients.json` with appointment reference, full name, date of birth, phone, reason, provider, date, time, insurance payer, member ID, insurance status, coverage active, copay, deductible, Stedi check timestamp, creation timestamp, and call mode.
- IMPORTANT PRIVACY WARNING: The saved patient record in `patients.json` keeps the full member ID because the clinic front desk needs it. Only fake test data is allowed until a proper privacy review is done. Never use real patient data with this demo.
- Server logs and webhook request logs always mask phone numbers and member IDs, showing only the last 4 characters (e.g. `***-***-7890` and `******wcSu`).

### 3. How to View and Delete Patient Data
- View a patient record:
  - Run `python show_patient.py <appointment_reference>` (for example, `python show_patient.py APT-A1B2C3`).
- Delete a single patient record:
  - Run `python delete_patient.py <appointment_reference>`. This removes the record from `patients.json`, `appointments.json`, and `data.json` at the same time.
- To delete all stored records:
  - Stop the server.
  - Reset `appointments.json` to an empty array: `[]`.
  - Reset `patients.json` to an empty array: `[]`.
  - In `data.json`, set `"appointments": []`.

### 4. Stedi Test Mode Must Never Receive Real PHI
- Stedi test mode endpoints are strictly for testing and integration validation.
- Never submit real patient names, social security numbers, or real member IDs to the Stedi test mode endpoint.
- Always use synthetic names (e.g. "John Doe", "Jane Doe") and official Stedi mock member IDs.

### 5. HIPAA and Local Data Regulations Notice
- Real healthcare operations handling Protected Health Information (PHI) must execute a Business Associate Agreement (BAA) with all cloud vendors, including the voice platforms (Vapi, Retell AI), hosting providers, and Stedi.
- Audio logs and transcription pipelines must be configured with HIPAA data retention rules and end-to-end encryption.
- Consult with a qualified healthcare compliance officer and legal counsel before using this software in clinical settings.

---

## 7. Zero-Cost Testing Workflow

Test the complete voice agent end-to-end for **$0** using browser playgrounds, local tunneling, and mock APIs, without paying for phone numbers, PBX servers, or carrier minutes.

### Free Tier & Trial Credit Limits
- **Vapi:** Provides **~$10 in free starting credits** upon signup, sufficient for hundreds of browser playground test calls.
- **Retell AI:** Provides free trial credits for sandbox testing.
- **Mockoon & ngrok:** 100% free locally; no credit card required.
- **Beeceptor:** Free tier includes **50 requests/day per endpoint** with zero signup needed.
- **Stedi Test Mode:** Free with zero transaction fees for mock checks.

### Step-by-Step Zero-Cost Testing Loop
1. **Step 1: Start Mock Clinic Calendar (Optional Chaos Test)**
   - Open Mockoon, import `mockoon_clinic.json`, and click the green Play button on port 3001.
   - In `.env`, set `BACKEND_MODE=mock`.
2. **Step 2: Start the FastAPI Backend**
   ```bash
   python -m uvicorn server:app --reload --port 3000
   ```
3. **Step 3: Start ngrok Tunnel**
   ```bash
   ngrok http 3000
   ```
4. **Step 4: Update Webhook URLs in Voice Dashboard**
   - Vapi Server URL: `https://<your-ngrok-domain>/webhook`
   - Retell Tool URLs: `https://<your-ngrok-domain>/webhook/retell`
5. **Step 5: Talk to the Agent in Web Playground**
   - Click **Test Agent** / **Web Call** in the Vapi dashboard.
   - Speak with the agent through your computer microphone.
6. **Step 6: Test Failure Edge Cases (Mockoon 404 & 500)**
   - Switch Mockoon route `POST /book` to 404 or 500 and verify graceful spoken error handling.

---

## 8. Automated Testing Suite

Run the full automated test suite containing 11 comprehensive suites:
```bash
python test_server.py
```
All 11 test suites execute locally in seconds with zero external API calls or telephony costs.
See [`LIVE_TESTING.md`](LIVE_TESTING.md) for the live manual test runbook and verification matrix.
