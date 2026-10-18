#!/usr/bin/env python3
"""
Faculty Data Sanitizer & Privacy Filter
================================================================================
Purpose:
Safely exports and redacts sensitive personal data (PII: passport data, tax IDs,
diploma numbers) from 'faculty-data' records while strictly PRESERVING all useful
scientometric, bibliographic, institutional, and research data.

Usage Modes:
1. Direct API Ingestion & Sanitization (Safe single-command fetch):
   python3 sanitize_faculty_data.py --api-key <KEY> --faculty all -l 20 -o sanitized_teachers.json
   python3 sanitize_faculty_data.py --api-key <KEY> --faculty social-sciences -o sanitized_social.json
   python3 sanitize_faculty_data.py --api-key <KEY> -n "Прізвище" -o sanitized_teacher.json

2. Local File Sanitization (Sanitize an existing raw JSON export):
   python3 sanitize_faculty_data.py -i raw_input.json -o sanitized_output.json

What is REDACTED (Strict PII):
- passport_data (Passport series, number, issuing authority, address, tax ID / РНОКПП)
- education_documents (Diploma series, numbers, certificates)
- Any standalone 10-digit tax IDs (\b\d{10}\b) or passport patterns in text

What is PRESERVED (Research & Scientometrics):
- name, profile_id, faculty_id
- scientometrics & scientometric_details (Google Scholar, ORCID, Scopus, WoS)
- indexed_publications (DOIs, publication titles, journals, authors)
- ukrainian_fach_publications (Ukrainian journal papers)
- textbooks_and_monographs (Books, monographs)
- professional_development (Foreign universities, IM PAN, habilitation info)
- international_projects_and_expertise (Collaborators, international grants)
- dissertation_councils, doctoral_supervision, research_and_editorial_roles
- academic_degree, academic_title, position, taught_disciplines
================================================================================
"""

import argparse
import copy
import json
import os
import re
import sys
import urllib.request
from typing import Dict, List, Optional, Tuple, Union

DEFAULT_FACULTY_DATA_URL = "https://faculty-data-two.vercel.app/api/admin/v1"
ALL_FACULTIES = [
    "social-sciences",
    "mathematics",
    "computer-science",
    "economics",
    "engineering",
    "business"
]

STRICT_PII_KEYS = {
    "passport_data",
    "education_documents"
}

REDACTION_PLACEHOLDER = "[REDACTED_FOR_PRIVACY]"


def scrub_pii_patterns(text: str) -> str:
    """Scans and scrubs accidental passport numbers or tax codes from freeform text."""
    if not isinstance(text, str) or not text:
        return text
    # 1. Ukrainian 10-digit tax ID (РНОКПП / ІПН)
    text = re.sub(r'\b\d{10}\b', '[REDACTED_TAX_ID]', text)
    # 2. Ukrainian passport series & number (e.g. СН 123456 or AA 123456)
    text = re.sub(r'\b[А-ЯA-Z]{2}\s*\d{6}\b', '[REDACTED_PASSPORT]', text)
    return text


def sanitize_teacher_record(teacher: Dict) -> Dict:
    """
    Returns a deep-cleaned copy of a teacher record where all sensitive PII is
    scrubbed, while keeping all scientometric, institutional, and research fields.
    """
    clean_t = copy.deepcopy(teacher)

    # 1. Sanitize 'profile' dictionary
    if "profile" in clean_t and isinstance(clean_t["profile"], dict):
        prof = clean_t["profile"]
        for key in list(prof.keys()):
            if key in STRICT_PII_KEYS:
                prof[key] = REDACTION_PLACEHOLDER
            elif isinstance(prof[key], str):
                prof[key] = scrub_pii_patterns(prof[key])

    # 2. Sanitize 'fields' array (raw form entries)
    if "fields" in clean_t and isinstance(clean_t["fields"], list):
        for field in clean_t["fields"]:
            if not isinstance(field, dict):
                continue
            f_key = field.get("key")
            if f_key in STRICT_PII_KEYS:
                field["data"] = REDACTION_PLACEHOLDER
                if "values" in field and isinstance(field["values"], list):
                    field["values"] = [REDACTION_PLACEHOLDER for _ in field["values"]]
            else:
                if "data" in field and isinstance(field["data"], str):
                    field["data"] = scrub_pii_patterns(field["data"])
                if "values" in field and isinstance(field["values"], list):
                    field["values"] = [
                        scrub_pii_patterns(v) if isinstance(v, str) else v
                        for v in field["values"]
                    ]

    return clean_t


def fetch_api_teachers(
    base_url: str,
    api_key: str,
    faculty_id: str,
    limit_per_call: int = 100
) -> List[Dict]:
    """Fetches teachers from faculty-data API, supporting pagination."""
    teachers: List[Dict] = []
    offset = 0
    headers = {
        "X-Faculty-Data-Key": api_key,
        "User-Agent": "KSE-Faculty-Sanitizer/1.0"
    }

    while True:
        endpoint = f"{base_url}/faculties/{faculty_id}/teachers?limit={limit_per_call}&offset={offset}"
        req = urllib.request.Request(endpoint, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            raise

        batch = data.get("teachers", [])
        if not batch:
            break

        for t in batch:
            t["faculty_id"] = faculty_id
            teachers.append(t)

        pagination = data.get("pagination", {})
        if not pagination.get("has_more") or len(batch) < limit_per_call:
            break
        offset += limit_per_call

    return teachers


def main():
    parser = argparse.ArgumentParser(
        description="Safely exports and sanitizes teacher records from faculty-data (removes PII, keeps research/publications)."
    )
    parser.add_argument("-i", "--input", help="Path to raw JSON file to sanitize.")
    parser.add_argument("-o", "--output", required=True, help="Path to write clean sanitized JSON.")
    parser.add_argument("--api-key", help="X-Faculty-Data-Key (or set FACULTY_DATA_API_KEY).")
    parser.add_argument("--api-url", default=DEFAULT_FACULTY_DATA_URL, help=f"Base URL (default: {DEFAULT_FACULTY_DATA_URL}).")
    parser.add_argument("--faculty", default="all", help="Faculty ID ('all' to search all faculties; default: all).")
    parser.add_argument("-n", "--name", help="Filter for a specific teacher by name or surname.")
    parser.add_argument("-l", "--limit", type=int, help="Limit total number of teachers exported.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress verbose console summary.")

    args = parser.parse_args()

    raw_teachers: List[Dict] = []

    # 1. Local File Ingestion
    if args.input:
        if not os.path.exists(args.input):
            print(f"Error: Input file '{args.input}' not found.", file=sys.stderr)
            sys.exit(1)
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            raw_teachers = data
        elif isinstance(data, dict):
            if "teachers" in data and isinstance(data["teachers"], list):
                raw_teachers = data["teachers"]
            elif "teacher" in data and isinstance(data["teacher"], dict):
                raw_teachers = [data["teacher"]]
            else:
                raw_teachers = [data]

    # 2. Live API Ingestion
    else:
        api_key = args.api_key or os.getenv("FACULTY_DATA_API_KEY")
        if not api_key:
            print("Error: Specify either --input <file> or provide --api-key (or set FACULTY_DATA_API_KEY).", file=sys.stderr)
            sys.exit(1)

        base = args.api_url.rstrip("/")
        faculties_to_query = ALL_FACULTIES if args.faculty == "all" else [args.faculty]

        if not args.quiet:
            print(f"Connecting to {base} (Querying {len(faculties_to_query)} faculty group(s))...")

        for f_id in faculties_to_query:
            try:
                batch = fetch_api_teachers(base, api_key, f_id)
                raw_teachers.extend(batch)
            except Exception as e:
                if not args.quiet:
                    print(f"  Warning: Faculty '{f_id}' fetch failed: {e}", file=sys.stderr)

    # Filter by name if requested
    if args.name:
        clean_target = args.name.strip().lower()
        filtered = []
        for t in raw_teachers:
            t_name = (t.get("name") or "").lower()
            if clean_target in t_name:
                filtered.append(t)
        raw_teachers = filtered

    if args.limit:
        raw_teachers = raw_teachers[:args.limit]

    if not raw_teachers:
        print("No teacher records found to sanitize.", file=sys.stderr)
        sys.exit(1)

    # Perform Sanitization
    sanitized_teachers = [sanitize_teacher_record(t) for t in raw_teachers]

    # Save to output file
    output_path = os.path.abspath(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sanitized_teachers, f, indent=2, ensure_ascii=False)

    if not args.quiet:
        print("=" * 80)
        print("🔒 FACULTY DATA SANITIZER: SUCCESS")
        print("=" * 80)
        print(f"Processed & Sanitized: {len(sanitized_teachers)} teacher record(s).")
        print(f"Output saved to:       {output_path}")
        print("\nPrivacy Verification Summary:")
        print("  ✅ passport_data:       Scrubbed -> [REDACTED_FOR_PRIVACY]")
        print("  ✅ education_documents: Scrubbed -> [REDACTED_FOR_PRIVACY]")
        print("  ✅ Standalone tax IDs:  Regex scrubbed")
        print("  ✅ Scientometrics:      Preserved (Scholar, ORCID, Scopus)")
        print("  ✅ Publications & DOIs: Preserved (indexed_publications, etc.)")
        print("  ✅ Institutions:        Preserved (professional_development, councils)")
        print("=" * 80)


if __name__ == "__main__":
    main()
