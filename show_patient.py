#!/usr/bin/env python3
"""
show_patient.py - Display a patient record by appointment reference.

Usage:
    python show_patient.py APT-XXXXXX
"""

import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()

PATIENTS_FILE = os.getenv("PATIENTS_FILE", "patients.json")


def show_patient(ref_id: str) -> None:
    """Prints the patient record matching the given appointment reference."""
    if not os.path.exists(PATIENTS_FILE):
        print(f"No patients file found at '{PATIENTS_FILE}'.")
        sys.exit(1)

    with open(PATIENTS_FILE, "r", encoding="utf-8") as f:
        patients = json.load(f)

    for p in patients:
        if p.get("appointment_reference") == ref_id:
            print(json.dumps(p, indent=2, ensure_ascii=False))
            return

    print(f"No patient record found for reference '{ref_id}'.")
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python show_patient.py <appointment_reference>")
        print("Example: python show_patient.py APT-A1B2C3")
        sys.exit(1)
    show_patient(sys.argv[1])
