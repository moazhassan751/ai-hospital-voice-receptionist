#!/usr/bin/env python3
"""
try_stedi_mock.py - Manual Stedi Eligibility Test Runner (Test Mode Only)

Sends one mock eligibility check to the Stedi test mode endpoint.
Uses STEDI_TEST_API_KEY from .env.
Safe to run manually with zero charges and zero real patient data.

Usage:
  python try_stedi_mock.py
  python try_stedi_mock.py --payer Aetna --member-id AETNA9wcSu --name "John Doe"
  python try_stedi_mock.py --payer UnitedHealthcare --member-id UHCAAA75 --name "Jane Doe"
"""

import argparse
import json
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from stedi_client import (
    check_eligibility_mock,
    mask_member_id,
    validate_test_api_key,
    SUPPORTED_PAYERS
)


def main():
    parser = argparse.ArgumentParser(
        description="Manual CLI tester for Stedi Test Mode insurance eligibility checks."
    )
    parser.add_argument(
        "--payer",
        default="Aetna",
        help="Insurance payer name (Aetna, Cigna, UnitedHealthcare, Medicare). Default: Aetna"
    )
    parser.add_argument(
        "--member-id",
        default="AETNA9wcSu",
        help="Test member ID (e.g. AETNA9wcSu, UHCAAA75). Default: AETNA9wcSu"
    )
    parser.add_argument(
        "--name",
        default="John Doe",
        help="Patient test name. Default: John Doe"
    )
    parser.add_argument(
        "--dob",
        default=None,
        help="Optional date of birth in YYYY-MM-DD format."
    )

    args = parser.parse_args()

    api_key = os.getenv("STEDI_TEST_API_KEY", "").strip()

    print("=" * 65)
    print("STEDI HEALTHCARE ELIGIBILITY TEST MODE RUNNER")
    print("=" * 65)
    print(f"Target Payer:       {args.payer}")
    print(f"Test Member ID:     {mask_member_id(args.member_id)}")
    print(f"Test Patient Name:  {args.name}")
    if args.dob:
        print(f"Date of Birth:      {args.dob}")

    if not api_key:
        print("\n[WARNING] STEDI_TEST_API_KEY is not set in your .env file.")
        print("To run a live test against Stedi test mode:")
        print("1. Sign up for a free Stedi account at https://portal.stedi.com")
        print("2. Generate a test API key under API Keys (named e.g. 'test_key').")
        print("3. Add it to .env: STEDI_TEST_API_KEY=test_your_key_here")
        print("\nRunning offline validation check instead...")
    else:
        try:
            validate_test_api_key(api_key)
            masked_key = f"{api_key[:4]}****{api_key[-4:]}" if len(api_key) > 8 else "****"
            print(f"Stedi Test Key:     {masked_key}")
        except ValueError as err:
            print(f"\n[ERROR] Key validation failed: {err}")
            sys.exit(1)

    print("\n[*] Sending request to Stedi test mode...")
    result = check_eligibility_mock(
        payer=args.payer,
        member_id=args.member_id,
        patient_name=args.name,
        date_of_birth=args.dob,
        api_key=api_key
    )

    print("\n" + "-" * 65)
    print("STEDI RESPONSE SUMMARY")
    print("-" * 65)
    print(f"Status:             {result.get('status')}")
    print(f"Payer:              {result.get('payer')}")
    print(f"Masked Member ID:   {result.get('masked_member_id')}")
    if result.get("copay") is not None:
        print(f"Copay:              ${result.get('copay')}")
    if result.get("deductible") is not None:
        print(f"Deductible:         ${result.get('deductible')}")
    print("\nVoice Receptionist Spoken Output:")
    print(f"\"{result.get('message')}\"")
    print("-" * 65)


if __name__ == "__main__":
    main()
