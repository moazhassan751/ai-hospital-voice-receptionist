#!/usr/bin/env python3
"""
delete_patient.py - Remove a patient record by appointment reference.

Deletes the record from patients.json, appointments.json, and data.json
so all three files stay synchronized.

Usage:
    python delete_patient.py APT-XXXXXX
"""

import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()

PATIENTS_FILE = os.getenv("PATIENTS_FILE", "patients.json")
APPOINTMENTS_FILE = "appointments.json"
DATA_FILE = "data.json"


def delete_patient(ref_id: str) -> None:
    """Removes the patient record with the given appointment reference from all files."""
    found = False

    # 1. Remove from patients.json
    if os.path.exists(PATIENTS_FILE):
        with open(PATIENTS_FILE, "r", encoding="utf-8") as f:
            patients = json.load(f)
        before = len(patients)
        patients = [p for p in patients if p.get("appointment_reference") != ref_id]
        if len(patients) < before:
            found = True
            with open(PATIENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(patients, f, indent=2, ensure_ascii=False)
            print(f"Removed from {PATIENTS_FILE}.")

    # 2. Remove from appointments.json
    if os.path.exists(APPOINTMENTS_FILE):
        with open(APPOINTMENTS_FILE, "r", encoding="utf-8") as f:
            appointments = json.load(f)
        before = len(appointments)
        appointments = [a for a in appointments if a.get("appointment_id") != ref_id]
        if len(appointments) < before:
            found = True
            with open(APPOINTMENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(appointments, f, indent=2, ensure_ascii=False)
            print(f"Removed from {APPOINTMENTS_FILE}.")

    # 3. Remove from data.json appointments array
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "appointments" in data:
            before = len(data["appointments"])
            data["appointments"] = [
                a for a in data["appointments"] if a.get("appointment_id") != ref_id
            ]
            if len(data["appointments"]) < before:
                found = True
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                print(f"Removed from {DATA_FILE}.")

    if found:
        print(f"Patient record '{ref_id}' deleted from all files.")
    else:
        print(f"No record found for reference '{ref_id}'.")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python delete_patient.py <appointment_reference>")
        print("Example: python delete_patient.py APT-A1B2C3")
        sys.exit(1)
    delete_patient(sys.argv[1])
