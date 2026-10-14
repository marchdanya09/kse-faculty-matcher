#!/usr/bin/env python3
"""
Faculty Data Bridge (One-Way Ingestion & Disambiguation)
================================================================================
Bridges KSE's internal 'faculty-data' application with the 'kse-faculty-matcher'
disambiguation pipeline.

Workflow:
1. Ingests teacher profiles from 'faculty-data' (via local JSON mock/export or live API).
2. Extracts available ground-truth anchors:
   - Known publication titles ('indexed_publications' / 'ukrainian_fach_publications')
   - Existing ORCID IDs ('scientometric_details.orcid' or 'scientometrics')
   - Existing Scholar IDs ('scientometric_details.google_scholar' or 'scientometrics')
3. Dispatches each faculty member to 'faculty_matcher.process_faculty_member'.
4. Discovers missing profiles, resolves cross-links, validates identities.
5. Formats enriched output with verification statuses, metrics, and pre-computed
   PATCH payloads ready for future database update.

Strict Rule:
Does NOT modify or touch the 'faculty-data/' repository. Operates purely as an
independent bridge within 'kse-faculty-matcher'.
================================================================================
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

# Import the core matching engine
try:
    from faculty_matcher import process_faculty_member, DEFAULT_SERPAPI_KEY
except ImportError:
    print("Error: Could not import 'faculty_matcher'. Ensure it is in the same directory.", file=sys.stderr)
    sys.exit(1)


# ==============================================================================
# ANCHOR EXTRACTION FROM FACULTY-DATA SCHEMA
# ==============================================================================
def extract_teacher_anchors(teacher: Dict) -> Dict:
    """
    Extracts name, publication titles, and scientometric identifiers from
    a teacher record adhering to the faculty-data contract.
    """
    name = (teacher.get("name") or "").strip()
    profile = teacher.get("profile") or {}
    scientometric_details = teacher.get("scientometric_details") or {}
    fields = teacher.get("fields") or []

    # 1. Extract Publications (Works)
    works: List[str] = []

    # Prefer raw cell array in fields if available (lossless)
    for field in fields:
        if field.get("key") in ("indexed_publications", "ukrainian_fach_publications"):
            for val in field.get("values") or []:
                clean_val = str(val).strip()
                if clean_val and len(clean_val) >= 10:
                    works.append(clean_val)

    # Fallback to comma-joined profile string if fields was empty
    if not works:
        raw_indexed = profile.get("indexed_publications") or ""
        raw_fach = profile.get("ukrainian_fach_publications") or ""
        for raw in (raw_indexed, raw_fach):
            if raw:
                # Split on common delimiters while preserving quoted or full titles
                for chunk in re.split(r'[\r\n]+', raw):
                    chunk = chunk.strip().strip(',;"')
                    if chunk and len(chunk) >= 10:
                        works.append(chunk)

    # 2. Extract ORCID
    known_orcid = None
    orcid_raw = scientometric_details.get("orcid") or profile.get("scientometrics") or ""
    orcid_match = re.search(r'\b([0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X])\b', orcid_raw)
    if orcid_match:
        known_orcid = orcid_match.group(1)

    # 3. Extract Google Scholar
    known_scholar = None
    scholar_raw = scientometric_details.get("google_scholar") or profile.get("scientometrics") or ""
    scholar_match = re.search(r'(?:citations\?user=|user=)([a-zA-Z0-9_\-]{12})', scholar_raw)
    if scholar_match:
        known_scholar = scholar_match.group(1)
    else:
        # Check for standalone 12-char alphanumeric ID
        scholar_id_match = re.search(r'\b([a-zA-Z0-9_\-]{12})\b', scholar_raw)
        if scholar_id_match and not any(k in scholar_raw.lower() for k in ("orcid", "scopus")):
            known_scholar = scholar_id_match.group(1)

    # 4. Extract Scopus
    known_scopus = None
    scopus_raw = scientometric_details.get("scopus") or profile.get("scientometrics") or ""
    scopus_match = re.search(r'(?:authorId=|author/cite\.uri\?authorId=)?(\d{10,11})', scopus_raw)
    if scopus_match:
        known_scopus = scopus_match.group(1)

    return {
        "profile_id": teacher.get("profile_id"),
        "name": name,
        "known_works": works,
        "known_orcid": known_orcid,
        "known_scholar": known_scholar,
        "known_scopus": known_scopus,
        "field_versions": teacher.get("field_versions") or {}
    }


# ==============================================================================
# INGESTION: LOAD TEACHERS FROM FILE OR LIVE REST API
# ==============================================================================
def load_teachers_from_source(
    file_path: Optional[str] = None,
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    faculty_id: str = "social-sciences"
) -> Tuple[str, List[Dict]]:
    """
    Loads teacher profiles either from a local JSON file or the live faculty-data API.
    Returns (faculty_id, teachers_list).
    """
    if file_path:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Input file '{file_path}' not found.")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            ret_faculty = data.get("faculty_id") or faculty_id
            if "teachers" in data and isinstance(data["teachers"], list):
                return ret_faculty, data["teachers"]
            elif "teacher" in data and isinstance(data["teacher"], dict):
                return ret_faculty, [data["teacher"]]
            else:
                return ret_faculty, [data]
        elif isinstance(data, list):
            return faculty_id, data
        else:
            raise ValueError("Unsupported JSON format in input file.")

    # Live API Ingestion
    if api_url:
        api_key = api_key or os.getenv("FACULTY_DATA_API_KEY")
        if not api_key:
            raise ValueError("Live API ingestion requires an API key (pass --api-key or set FACULTY_DATA_API_KEY).")

        base = api_url.rstrip("/")
        endpoint = f"{base}/faculties/{faculty_id}/teachers?limit=100&offset=0"
        headers = {"X-Faculty-Data-Key": api_key, "User-Agent": "KSE-Faculty-Matcher-Bridge/1.0"}

        req = urllib.request.Request(endpoint, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        return data.get("faculty_id", faculty_id), data.get("teachers", [])

    # Default fallback: mock data
    default_mock = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_faculty_data.json")
    if os.path.exists(default_mock):
        return load_teachers_from_source(file_path=default_mock, faculty_id=faculty_id)

    raise ValueError("No input source provided. Specify --file <path> or use --mock.")


# ==============================================================================
# BRIDGE RUNNER & ENRICHMENT
# ==============================================================================
def run_bridge(
    teachers: List[Dict],
    faculty_id: str = "social-sciences",
    verbose: bool = True,
    serpapi_key: Optional[str] = None,
    limit: Optional[int] = None
) -> List[Dict]:
    """
    Iterates through faculty-data teachers, extracts anchors, dispatches to
    faculty_matcher, and returns enriched profiles.
    """
    enriched_results = []
    to_process = teachers[:limit] if limit else teachers

    if verbose:
        print("=" * 80)
        print(f"🌉 KSE FACULTY DATA BRIDGE: Processing {len(to_process)} teachers from '{faculty_id}'")
        print("=" * 80)

    for idx, teacher in enumerate(to_process, 1):
        anchors = extract_teacher_anchors(teacher)
        name = anchors["name"]
        profile_id = anchors["profile_id"]
        works = anchors["known_works"]
        orcid = anchors["known_orcid"]
        scholar = anchors["known_scholar"]

        # Classification of supplied anchors for display
        anchor_tags = []
        if works:
            anchor_tags.append(f"{len(works)} work(s)")
        if orcid:
            anchor_tags.append("ORCID")
        if scholar:
            anchor_tags.append("Scholar")
        anchor_desc = ", ".join(anchor_tags) if anchor_tags else "Name only"

        if verbose:
            print(f"\n[{idx}/{len(to_process)}] {name}")
            print(f"  🏢 Profile ID: {profile_id}")
            print(f"  ⚓ Supplied Anchors: [{anchor_desc}]")
            if works:
                print(f"  📖 Sample Work: \"{works[0][:75]}...\"" if len(works[0]) > 75 else f"  📖 Sample Work: \"{works[0]}\"")
            if orcid:
                print(f"  🆔 Known ORCID: {orcid}")
            if scholar:
                print(f"  🎓 Known Scholar ID: {scholar}")

        # Run Core Matching Pipeline
        match_res = process_faculty_member(
            input_name=name,
            verbose=verbose,
            serpapi_key=serpapi_key,
            known_works=works,
            known_orcid=orcid,
            known_scholar=scholar
        )

        resolved_orcid = (match_res.get("orcid") or {}).get("orcid_id")
        resolved_scholar = (match_res.get("scholar") or {}).get("scholar_id")
        status = match_res.get("status")
        confidence = match_res.get("confidence_score")

        # Discoveries (items found by matcher that were missing in original teacher record)
        discovered_orcid = bool(resolved_orcid and not orcid)
        discovered_scholar = bool(resolved_scholar and not scholar)

        # Prepare proposed PATCH payload for faculty-data
        new_sciento_lines = []
        if resolved_orcid:
            new_sciento_lines.append(f"ORCID: {resolved_orcid}")
        if resolved_scholar:
            new_sciento_lines.append(f"Google Scholar: {resolved_scholar}")
        if anchors["known_scopus"]:
            new_sciento_lines.append(f"Scopus: {anchors['known_scopus']}")

        proposed_patch = {
            "profile": {
                "scientometrics": "\n".join(new_sciento_lines)
            },
            "versions": {
                "scientometrics": anchors["field_versions"].get("scientometrics", 1)
            }
        } if (discovered_orcid or discovered_scholar) else None

        enriched_item = {
            "profile_id": profile_id,
            "faculty_id": faculty_id,
            "name": name,
            "initial_state": {
                "had_works": len(works) > 0,
                "had_orcid": bool(orcid),
                "had_scholar": bool(scholar),
                "works_count": len(works)
            },
            "resolution": {
                "status": status,
                "confidence_score": confidence,
                "reasons": match_res.get("reasons", []),
                "orcid": match_res.get("orcid"),
                "scholar": match_res.get("scholar"),
                "metrics": match_res.get("metrics", {})
            },
            "discoveries": {
                "new_orcid_discovered": discovered_orcid,
                "new_scholar_discovered": discovered_scholar,
                "resolved_orcid_id": resolved_orcid,
                "resolved_scholar_id": resolved_scholar
            },
            "proposed_patch": proposed_patch
        }
        enriched_results.append(enriched_item)

    return enriched_results


# ==============================================================================
# CLI INTERFACE
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="KSE Faculty Data Bridge: Disambiguates and enriches faculty-data profiles using kse-faculty-matcher."
    )
    parser.add_argument("-f", "--file", help="Path to faculty-data JSON export file.")
    parser.add_argument("--mock", action="store_true", help="Run using built-in mock_faculty_data.json.")
    parser.add_argument("--api-url", help="Base URL of live faculty-data instance (e.g. https://faculty-data-two.vercel.app/api/admin/v1).")
    parser.add_argument("--api-key", help="X-Faculty-Data-Key for live API authentication.")
    parser.add_argument("--faculty", default="social-sciences", help="Faculty ID to process (default: social-sciences).")
    parser.add_argument("--serpapi-key", help="SerpAPI key for Scholar lookups (defaults to SERPAPI_API_KEY from .env).")
    parser.add_argument("-o", "--output", help="File path to save enriched results JSON.")
    parser.add_argument("-l", "--limit", type=int, help="Limit number of teachers to process.")
    parser.add_argument("--json", action="store_true", help="Output pure JSON to stdout.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress verbose processing logs.")

    args = parser.parse_args()

    input_file = args.file
    if args.mock and not input_file:
        input_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_faculty_data.json")

    try:
        faculty_id, teachers = load_teachers_from_source(
            file_path=input_file,
            api_url=args.api_url,
            api_key=args.api_key,
            faculty_id=args.faculty
        )
    except Exception as e:
        print(f"Error loading faculty data: {e}", file=sys.stderr)
        sys.exit(1)

    verbose = not (args.json or args.quiet)

    results = run_bridge(
        teachers=teachers,
        faculty_id=faculty_id,
        verbose=verbose,
        serpapi_key=args.serpapi_key,
        limit=args.limit
    )

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    elif not args.quiet:
        print("\n" + "=" * 80)
        print("📊 BRIDGE DISCOVERY SUMMARY")
        print("=" * 80)
        print(f"{'Faculty Member':<25} | {'Status':<28} | {'ORCID':<19} | {'Scholar ID':<12} | {'New Discoveries'}")
        print("-" * 105)
        for r in results:
            name = r["name"][:25]
            st = r["resolution"]["status"][:28]
            orcid = (r["resolution"]["orcid"] or {}).get("orcid_id") or "—"
            scholar = (r["resolution"]["scholar"] or {}).get("scholar_id") or "—"
            disc = []
            if r["discoveries"]["new_orcid_discovered"]:
                disc.append("+ORCID")
            if r["discoveries"]["new_scholar_discovered"]:
                disc.append("+Scholar")
            disc_str = ", ".join(disc) if disc else "Verified existing"
            print(f"{name:<25} | {st:<28} | {orcid:<19} | {scholar:<12} | {disc_str}")

        print("=" * 80)
        print(f"Total processed: {len(results)} faculty members.")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        if not args.json and not args.quiet:
            print(f"Enriched results successfully saved to '{args.output}'.")


if __name__ == "__main__":
    main()
