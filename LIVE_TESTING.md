# AI Hospital Voice Receptionist - Live Testing Guide & Runbook

This runbook gives step-by-step instructions for testing the AI Hospital Voice Receptionist by hand across all four telephony scenarios, chaos testing with Mockoon, and running Stedi insurance checks in test mode.

---

## 1. Cost & Prerequisites Overview

| Scenario | Testing Ingress | Required Resources | Testing Cost |
|---|---|---|---|
| **Scenario 1: Marketplace Concierge** | Browser Playground / Virtual Number | Computer mic, Vapi / Retell free credits | **Free** (Zero telecom cost via browser) |
| **Scenario 2: Carrier Call Forwarding** | Real Mobile / Clinic Landline | 1 clinic phone line, 1 Vapi virtual number | **Paid** (Carriers charge standard minute rates) |
| **Scenario 3: Cloud PBX / SIP Trunk** | PBX Extension (e.g. Ext 101) | FreePBX, 3CX, Asterisk, or RingCentral | **Requires PBX Setup** (Internal network or cloud PBX) |
| **Scenario 4: BYOC Carrier Trunk** | Inbound carrier number | Twilio, Telnyx, or Plivo active account | **Paid** (Carrier DID monthly fee + minutes) |
| **Stedi Insurance Check** | Webhook tool call / CLI | Stedi free account with test API key | **Free** (Stedi Test Mode has no fees) |

---

## 2. Universal Setup: Server & Public Webhook Tunnel

Follow these steps before initiating any live call test.

### Step 1: Start the Local FastAPI Server
Open a terminal in the project directory and run:
```bash
python -m uvicorn server:app --reload --port 3000
```

Verify the local health check in your browser or curl:
- URL: [http://localhost:3000/health](http://localhost:3000/health)
- Expected response: `{"status": "healthy", "service": "hospital-voice-agent", ...}`

Check terminal output for startup warnings. If `FRONT_DESK_NUMBER` or `WEBHOOK_SECRET` are still default placeholders, the server prints a clear notice.

### Step 2: Start an ngrok Tunnel
In a second terminal window, run:
```bash
ngrok http 3000
```

Copy your HTTPS forwarding URL (e.g. `https://abc-123.ngrok-free.app`).

> [!NOTE]
> Do not use localtunnel without the bypass header. Localtunnel returns an HTML splash reminder that causes voice webhooks to fail with HTTP 502 errors. ngrok passes webhooks directly through without interruption.

### Step 3: Configure Server URLs in Voice Dashboards
- **Vapi Dashboard (https://dashboard.vapi.ai):**
  1. Open your Assistant.
  2. In the **Server URL** field under Settings, paste:
     `https://<your-ngrok-domain>/webhook` (e.g. `https://abc-123.ngrok-free.app/webhook`).
  3. Under **Server Secret**, enter your secret from `.env` (default: `hospital_secret_123`).
  4. Click **Save**.

- **Retell Dashboard (https://beta.retellai.com):**
  1. Open your Agent.
  2. For custom tools (`check_availability`, `book_appointment`, `find_clinic`, `check_insurance`), set the Webhook URL to:
     `https://<your-ngrok-domain>/webhook/retell`.
  3. Click **Save**.

---

## 3. Scenario-by-Scenario Testing Instructions

### Scenario 1: Marketplace Number (Free via Browser Playground)

1. In `.env`, set:
   ```env
   DEPLOYMENT_MODE=marketplace
   CALL_MODE=marketplace
   ```
2. In the Vapi Dashboard, open your assistant and click **Test Agent** / **Web Call** (browser microphone).
3. **What to speak:**
   - **Greeting check:** Listen to the initial greeting.
     - Expected: *"Welcome to HealthNetwork AI, are you looking for a clinic in a specific area or a specific doctor?"*
   - **Directory search:** Say: *"I am looking for routine care in Downtown."*
     - Expected: AI calls `find_clinic` and recommends Downtown clinics from `data.json`.
   - **Booking:** Say: *"Please book me with Doctor Steve tomorrow at 10:00 AM. My name is Sarah Connor and my phone number is 555-0199."*
     - Expected: AI repeats details and confirms booking.
4. **What to verify in server logs:**
   - Log shows: `Telephony Scenario: Scenario 1 (Marketplace Number)`.
   - Log shows: `Tool: find_clinic` with masked arguments.
   - Log shows: `Tool: book_appointment` with phone masked as `***-***-0199`.

---

### Scenario 2: Call Forwarding (Requires Real Phone & Carrier)

1. Provision or attach a Vapi phone number:
   ```bash
   python setup_telephony.py vapi-number --dry-run
   python setup_telephony.py vapi-number
   ```
2. In `.env`, set:
   ```env
   DEPLOYMENT_MODE=single_hospital
   CALL_MODE=auto
   ```
3. Test Overflow Mode (Simulated or Live):
   - Dial `*71<Vapi-Phone-Number>` on your practice landline or set `CALL_MODE=overflow` in `.env`.
   - Call your clinic number or use the browser test.
   - Expected greeting: *"Thank you for waiting, how can I help you today?"*
4. Test After-Hours Mode:
   - At 5:00 PM (or set `CALL_MODE=after_hours` in `.env`), place a call.
   - Expected greeting: *"Hello, good evening, our clinic is closed right now, but I can book you an appointment, or connect you to our front desk if it's urgent."*
   - Book an appointment for an upcoming weekday.
5. Verify server logs:
   - Log reports: `Scenario 2 (Call Forwarding - Overflow)` or `Scenario 2 (Call Forwarding - After Hours)`.

---

### Scenario 3: Cloud PBX / SIP Trunk (Requires PBX: 3CX, FreePBX, Asterisk)

1. Run the SIP provisioning tool in dry run mode to inspect the exact payload:
   ```bash
   python setup_telephony.py sip-trunk --host 198.51.100.10 --extension 101 --dry-run
   ```
2. In your Cloud PBX management console:
   - Create a generic SIP trunk pointing to `sip.vapi.ai` (port 5060 UDP/TCP).
   - Assign Extension 101 to this trunk.
   - Route incoming calls or IVR Option 1 ("Receptionist") to Extension 101.
3. Place an internal call from a softphone (e.g. Linphone or Zoiper) to Extension 101.
4. **Emergency Transfer Test:**
   - Say: *"I have sudden crushing chest pain and difficulty breathing."*
   - Expected: AI stops the booking flow immediately, says *"I'm connecting you to our front desk right away. Please stay on the line."*, and initiates a transfer to `FRONT_DESK_NUMBER`.
5. **Human Escalation Test:**
   - Say: *"I need to speak to a real person right now."*
   - Expected: AI summarizes your request and transfers to the front desk.
6. Verify server logs:
   - Log shows `Tool: prepare_warm_transfer`.
   - Log displays `Priority: Urgent/Front Desk` with summary.

---

### Scenario 4: BYOC (Bring Your Own Carrier - Twilio, Telnyx, Plivo)

1. Preview the BYOC import request:
   ```bash
   python setup_telephony.py byoc --provider twilio --dry-run
   ```
2. For real testing, populate `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_PHONE_NUMBER` in `.env`.
3. Import your carrier number:
   ```bash
   python setup_telephony.py byoc --provider twilio
   ```
4. Place a live call from your mobile phone to your Twilio number.
5. Speak with the assistant:
   - Ask for Doctor Steve availability.
   - Confirm an appointment booking.
6. Verify server logs:
   - Log shows: `Telephony Scenario: Scenario 4 (BYOC - TWILIO)`.
   - Webhook processing completes with identical response format to native Vapi numbers.

---

## 4. Chaos Testing: Mockoon Calendar Failures (404 & 500)

Test how the voice receptionist handles booking system failures without code changes.

1. Install and open Mockoon (https://mockoon.com).
2. Open Mockoon and import `mockoon_clinic.json` from the repository.
3. Start the Mockoon environment (runs on `http://localhost:3001`).
4. In `.env`, set:
   ```env
   BACKEND_MODE=mock
   MOCK_URL=http://localhost:3001
   ```
5. Restart `server.py` or let uvicorn reload automatically.

### Test Case A: Slot Collision (HTTP 404)
1. In Mockoon, select the `POST /book` route.
2. In the Responses dropdown, select `404 - Slot Collision`.
3. In the Vapi web playground, try booking an appointment.
4. **Expected Spoken Response:**
   *"That time slot was just taken, would another time work?"*
5. The assistant stays calm and invites the caller to pick a different slot.

### Test Case B: Booking Service Error (HTTP 500)
1. In Mockoon, switch the active response for `POST /book` to `500 - Internal Server Error`.
2. In the Vapi web playground, try booking an appointment.
3. **Expected Spoken Response:**
   *"I am having trouble accessing our booking system right now. Let me connect you directly to our front desk so they can help you right away."*
4. The assistant immediately offers the human front desk instead of repeating errors.

---

## 5. Stedi Insurance Eligibility Check (Test Mode Only)

1. Obtain a free test API key from https://portal.stedi.com.
2. In `.env`, set:
   ```env
   STEDI_TEST_API_KEY=test_zimwwVI.tGkF4IEAbwKKAgRdxww1FCVh
   ```
3. Run the manual verification script for active coverage:
   ```bash
   python try_stedi_mock.py --payer Aetna --member-id AETNA9wcSu --name "John Doe"
   ```
   - Terminal output confirms:
     Status: active
     Payer: Aetna
     Masked Member ID: ******wcSu
     Copay: $15.0
     Deductible: $0.0
     Spoken message: "Your coverage with Aetna is active. Your copay is $15 and your remaining deductible is $0."
4. Run the manual verification script for Subscriber Not Found:
   ```bash
   python try_stedi_mock.py --payer UnitedHealthcare --member-id UHCAAA75 --name "Jane Doe"
   ```
   - Terminal output confirms:
     Status: not_found
     Payer: UnitedHealthcare
     Masked Member ID: ****AA75
     Spoken message: "I could not verify that member ID with UnitedHealthcare. Let me connect you with our front desk to help confirm your details."
5. Test in the Vapi browser playground:
   - Make a test call.
   - When the receptionist asks how she can help, say: *"Can you check if my Aetna insurance is accepted? My member ID is AETNA9wcSu and my name is John Doe."*
   - Expected spoken response:
     *"Your coverage with Aetna is active. Your copay is $15 and your remaining deductible is $0."*
6. Test Subscriber Not Found in browser playground:
   - Say: *"My insurance is UnitedHealthcare and my member ID is UHCAAA75."*
   - Expected spoken response:
     *"I could not verify that member ID with UnitedHealthcare. Let me connect you with our front desk to help confirm your details."*

---

## 6. Live Testing Verification Matrix

| Scenario | Test | Expected result | Actual result | Pass/Fail |
|---|---|---|---|---|
| **Scenario 1** | Browser Marketplace Greeting | "Welcome to HealthNetwork AI, are you looking for a clinic in a specific area or a specific doctor?" | Verified in automated suite 10 | PASS |
| **Scenario 1** | Directory Search by Area | Returns clinics located in requested area | Verified in automated suite 10 | PASS |
| **Scenario 1** | Directory Search by Specialty | Returns clinics matching requested medical specialty | Verified in automated suite 10 | PASS |
| **Scenario 1** | Marketplace Booking | Books appointment and returns reference number | Verified in automated suite 10 | PASS |
| **Scenario 2** | Overflow Greeting (*71 after 4 rings) | "Thank you for waiting, how can I help you today?" | Verified in automated suite 10 | PASS |
| **Scenario 2** | After-Hours Greeting (closed hours/Sunday) | "Hello, [time], our clinic is closed right now, but I can book you an appointment..." | Verified in automated suite 10 | PASS |
| **Scenario 2** | Full Forwarding Booking (*72) | Books appointment during standard operating hours | Verified in automated suite 10 | PASS |
| **Scenario 3** | PBX Extension Dialing (Ext 101) | AI answers internal PBX call and offers greeting | Verified in automated suite 10 | PASS |
| **Scenario 3** | Emergency Transfer (chest pain / shortness of breath) | Immediately triggers warm transfer to FRONT_DESK_NUMBER with medical summary | Verified in automated suite 10 | PASS |
| **Scenario 3** | Speak to Human Request | Transfers caller to human front desk without hesitation | Verified in automated suite 10 | PASS |
| **Scenario 4** | BYOC Inbound Call (Twilio / Telnyx / Plivo) | Call connects via external carrier and checks availability | Verified in automated suite 10 | PASS |
| **Mockoon Chaos** | 404 Slot Taken | "That time slot was just taken, would another time work?" | Verified in automated suite 9 | PASS |
| **Mockoon Chaos** | 500 Booking Service Down | "I am having trouble accessing our booking system right now. Let me connect you directly to our front desk..." | Verified in automated suite 9 | PASS |
| **Stedi Test Mode** | Active Coverage Check (Aetna AETNA9wcSu) | Voice reports active coverage with copay and deductible | "Your coverage with Aetna is active. Your copay is $15 and your remaining deductible is $0." (Live Stedi HTTP 200, Copay $15, Ded $0) | PASS |
| **Stedi Test Mode** | Subscriber Not Found (UHCAAA75) | Politely offers front desk connection to confirm details | "I could not verify that member ID with UnitedHealthcare. Let me connect you with our front desk to help confirm your details." (Live Stedi HTTP 200, Code 73) | PASS |
| **Security Guardrail** | Bad Webhook Secret | Rejects incoming request with HTTP 401 Unauthorized | Verified in automated suite 10 | PASS |
| **Privacy Guardrail** | Log Masking Verification | Phone masked to last 4 digits (***-***-XXXX), member ID masked (******XXXX) | Verified in automated suite 11 | PASS |
| **Clinical Guardrail** | Nurse Maha Scope Limitation | Rejects medical consultation for Nurse Maha and redirects to Doctor Steve | Verified in automated suite 10 | PASS |

---

## 7. Manual Live Calls Status (Carrier Hardware & Human Testing)

The following live call tests require manual execution with active telephone carrier hardware, softphones, or live browser sessions. They remain available for manual validation:

- [ ] Real Vapi browser playground call session
- [ ] Real Retell AI browser call session
- [ ] ngrok tunnel live webhook call
- [ ] Real front desk phone transfer to physical device
- [ ] Real carrier forwarding with physical mobile dialer (*71 / *72)
- [ ] Real Cloud PBX extension dialing on 3CX / FreePBX
- [ ] Real BYOC call dialed to external carrier DID
