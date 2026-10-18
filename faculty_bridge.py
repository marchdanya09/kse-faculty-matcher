#!/usr/bin/env python3
"""
Faculty Data Bridge (One-Way Ingestion & Disambiguation)
================================================================================
Bridges KSE's internal 'faculty-data' application with the 'kse-faculty-matcher'
disambiguation pipeline.

Workflow:
1. Ingests teacher profiles from 'faculty-data' (via local JSON mock/export or live API).
   - Allows targeted single-teacher lookup via `--teacher-name / -n`.
   - Supports `--fetch-only` to dump raw teacher JSON without sending queries.
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
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from rapidfuzz import fuzz

# Import the core matching engine
try:
    from faculty_matcher import (
        process_faculty_member,
        DEFAULT_SERPAPI_KEY,
        PATRONYMIC_ENDINGS,
        transliterate_ukr,
        transliterate_ru,
        CitationParser
    )
except ImportError:
    print("Error: Could not import 'faculty_matcher'. Ensure it is in the same directory.", file=sys.stderr)
    sys.exit(1)

DEFAULT_FACULTY_DATA_URL = "https://faculty-data-two.vercel.app/api/admin/v1"
ALL_FACULTIES = [
    "social-sciences",
    "mathematics",
    "computer-science",
    "economics",
    "engineering",
    "business"
]


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
    raw_works: List[str] = []

    # Prefer raw cell array in fields if available (lossless)
    for field in fields:
        if field.get("key") in ("indexed_publications", "ukrainian_fach_publications"):
            for val in field.get("values") or []:
                clean_val = str(val).strip()
                if clean_val and len(clean_val) >= 10:
                    raw_works.append(clean_val)

    # Fallback to comma-joined profile string if fields was empty
    if not raw_works:
        raw_indexed = profile.get("indexed_publications") or ""
        raw_fach = profile.get("ukrainian_fach_publications") or ""
        for raw in (raw_indexed, raw_fach):
            if raw:
                raw_works.append(str(raw).strip())

    # Parse and split citations robustly (handles list numbering, glued DOIs/years, APA, DSTU)
    works: List[str] = []
    seen = set()
    for raw in raw_works:
        for chunk in CitationParser.split_citations(raw):
            c_clean = chunk.strip()
            if c_clean and len(c_clean) >= 10 and c_clean not in seen:
                seen.add(c_clean)
                works.append(c_clean)

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
def fetch_faculty_teachers_api(
    base_url: str,
    api_key: str,
    faculty_id: str,
    teacher_name_filter: Optional[str] = None
) -> List[Dict]:
    """Fetches teachers from faculty-data API, supporting pagination."""
    teachers: List[Dict] = []
    offset = 0
    limit = 100
    headers = {"X-Faculty-Data-Key": api_key, "User-Agent": "KSE-Faculty-Matcher-Bridge/1.0"}

    while True:
        endpoint = f"{base_url}/faculties/{faculty_id}/teachers?limit={limit}&offset={offset}"
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
        if not pagination.get("has_more") or len(batch) < limit:
            break
        offset += limit

    return teachers


def strip_patronymic_tokens(tokens: List[str]) -> List[str]:
    """Strips patronymic endings ONLY if >= 3 tokens."""
    if len(tokens) >= 3:
        if tokens[1].lower().endswith(PATRONYMIC_ENDINGS):
            return [tokens[0]] + tokens[2:]
        elif tokens[-1].lower().endswith(PATRONYMIC_ENDINGS):
            return tokens[:-1]
    return tokens


def match_teacher_name(target_query: str, candidate_name: str) -> bool:
    """
    Accurately matches a target query (e.g. 'Власенко' or 'Власенко Марія Олександрівна')
    against a candidate teacher name. Protects against false homonym matches where two
    people share first name and patronymic (e.g. 'Чаїнська Марія Олександрівна' vs 'Власенко Марія Олександрівна').
    """
    if not target_query or not candidate_name:
        return False

    t_clean = re.sub(r'[\’\ʼ\`\‘\´\ʻ]', "'", target_query.strip().lower())
    c_clean = re.sub(r'[\’\ʼ\`\‘\´\ʻ]', "'", candidate_name.strip().lower())

    if t_clean == c_clean:
        return True

    t_tokens = [t for t in re.split(r'\s+', t_clean) if t]
    c_tokens = [t for t in re.split(r'\s+', c_clean) if t]

    if not t_tokens or not c_tokens:
        return False

    t_core = strip_patronymic_tokens(t_tokens)
    c_core = strip_patronymic_tokens(c_tokens)

    # 1. Single-word target (e.g. user passed just the surname "Власенко")
    if len(t_core) == 1:
        target_word = t_core[0]
        tr_t_u = transliterate_ukr(target_word).lower()
        tr_t_r = transliterate_ru(target_word).lower()
        for c_word in c_core:
            if target_word == c_word or fuzz.ratio(target_word, c_word) >= 85:
                return True
            tr_c_u = transliterate_ukr(c_word).lower()
            tr_c_r = transliterate_ru(c_word).lower()
            if tr_t_u in (tr_c_u, tr_c_r) or tr_t_r in (tr_c_u, tr_c_r):
                return True
            if fuzz.ratio(tr_t_u, tr_c_u) >= 85 or fuzz.ratio(tr_t_r, tr_c_r) >= 85:
                return True
        return False

    # 2. Multi-word target (e.g. "Власенко Марія" or full 3-token name)
    # Every core token of the target query MUST match a token in the candidate name.
    # This strictly prevents "Чаїнська" from matching "Власенко" even if both share "Марія Олександрівна".
    for t_word in t_core:
        matched_token = False
        tr_t_u = transliterate_ukr(t_word).lower()
        tr_t_r = transliterate_ru(t_word).lower()
        for c_word in c_core:
            if t_word == c_word or fuzz.ratio(t_word, c_word) >= 85:
                matched_token = True
                break
            tr_c_u = transliterate_ukr(c_word).lower()
            tr_c_r = transliterate_ru(c_word).lower()
            if tr_t_u in (tr_c_u, tr_c_r) or tr_t_r in (tr_c_u, tr_c_r):
                matched_token = True
                break
            if fuzz.ratio(tr_t_u, tr_c_u) >= 85 or fuzz.ratio(tr_t_r, tr_c_r) >= 85:
                matched_token = True
                break
        if not matched_token:
            return False

    return True


def load_teachers_from_source(
    file_path: Optional[str] = None,
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    faculty_id: str = "social-sciences",
    teacher_name_filter: Optional[str] = None
) -> Tuple[str, List[Dict]]:
    """
    Loads teacher profiles either from a local JSON file or the live faculty-data API.
    Returns (faculty_id, teachers_list).
    """
    teachers_list: List[Dict] = []
    effective_faculty = faculty_id

    # 1. Local file ingestion
    if file_path:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Input file '{file_path}' not found.")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            effective_faculty = data.get("faculty_id") or faculty_id
            if "teachers" in data and isinstance(data["teachers"], list):
                teachers_list = data["teachers"]
            elif "teacher" in data and isinstance(data["teacher"], dict):
                teachers_list = [data["teacher"]]
            else:
                teachers_list = [data]
        elif isinstance(data, list):
            teachers_list = data
        else:
            raise ValueError("Unsupported JSON format in input file.")

    # 2. Live API Ingestion
    elif api_key or api_url:
        api_key = api_key or os.getenv("FACULTY_DATA_API_KEY")
        if not api_key:
            raise ValueError("Live API ingestion requires an API key (pass --api-key or set FACULTY_DATA_API_KEY).")

        base = (api_url or DEFAULT_FACULTY_DATA_URL).rstrip("/")
        if not base.endswith("/api/admin/v1") and not base.endswith("/api"):
            base = f"{base}/api/admin/v1"

        # If faculty is specified and not 'all', query only that faculty
        if faculty_id and faculty_id != "all":
            teachers_list = fetch_faculty_teachers_api(base, api_key, faculty_id)
            effective_faculty = faculty_id
        else:
            # Query across all faculties
            effective_faculty = "all"
            for f_id in ALL_FACULTIES:
                try:
                    f_teachers = fetch_faculty_teachers_api(base, api_key, f_id)
                    teachers_list.extend(f_teachers)
                except Exception as e:
                    print(f"Warning: Faculty '{f_id}' fetch failed at {base}: {e}", file=sys.stderr)
                    continue

    # 3. Default fallback: mock data
    else:
        default_mock = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_faculty_data.json")
        if os.path.exists(default_mock):
            return load_teachers_from_source(file_path=default_mock, faculty_id=faculty_id, teacher_name_filter=teacher_name_filter)
        raise ValueError("No input source provided. Specify --file <path>, --api-key <key>, or use --mock.")

    # Filter by teacher name if requested
    if teacher_name_filter:
        matched = []
        for t in teachers_list:
            t_name = t.get("name") or ""
            if match_teacher_name(teacher_name_filter, t_name):
                matched.append(t)
        return effective_faculty, matched

    return effective_faculty, teachers_list


# ==============================================================================
# INCREMENTAL SYNC & STATE MANAGER (WATERMARK + CONTENT HASHING)
# ==============================================================================
class SyncStateManager:
    """
    Manages incremental synchronization state (.matcher_state.json) using
    watermarks, TTL audit windows, and deterministic SHA-256 content hashing.
    """
    DEFAULT_STATE_FILE = ".matcher_state.json"

    def __init__(self, state_file: Optional[str] = None, enabled: bool = True):
        self.state_file = state_file or self.DEFAULT_STATE_FILE
        self.enabled = enabled
        self.state: Dict = {
            "version": "1.0",
            "updated_at": None,
            "teachers": {}
        }
        if self.enabled:
            self.load()

    def load(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.state = data
                    if "teachers" not in self.state or not isinstance(self.state["teachers"], dict):
                        self.state["teachers"] = {}
            except Exception as e:
                print(f"Warning: Could not read state file '{self.state_file}': {e}. Starting with fresh state.", file=sys.stderr)
                self.state = {"version": "1.0", "updated_at": None, "teachers": {}}

    def save(self):
        if not self.enabled:
            return
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp_file = f"{self.state_file}.tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, self.state_file)
        except Exception:
            try:
                with open(self.state_file, "w", encoding="utf-8") as f:
                    json.dump(self.state, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Warning: Could not save state file '{self.state_file}': {e}", file=sys.stderr)

    @staticmethod
    def compute_content_hash(name: str, anchors: Dict) -> str:
        """
        Computes deterministic SHA-256 hash from teacher's name, publications,
        and scientometric identifiers.
        """
        clean_name = re.sub(r'\s+', ' ', (name or "").strip().lower())
        works_sorted = sorted([w.strip().lower() for w in (anchors.get("known_works") or []) if w and w.strip()])
        orcid_val = (anchors.get("known_orcid") or "").strip().lower()
        scholar_val = (anchors.get("known_scholar") or "").strip().lower()
        scopus_val = (anchors.get("known_scopus") or "").strip().lower()

        hash_payload = json.dumps({
            "name": clean_name,
            "works": works_sorted,
            "orcid": orcid_val,
            "scholar": scholar_val,
            "scopus": scopus_val
        }, sort_keys=True, ensure_ascii=False)

        return hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()

    def should_process(
        self,
        profile_id: str,
        name: str,
        content_hash: str,
        anchors: Dict,
        mode: str = "incremental",
        ttl_days: int = 30
    ) -> Tuple[bool, Optional[Dict], str]:
        """
        Determines whether a teacher profile needs re-processing.
        Returns: (should_run, cached_enriched_item, reason)
        """
        if not self.enabled or mode == "force-all":
            return True, None, "force-all / state disabled"

        # Lookup in state by profile_id or name
        record = self.state.get("teachers", {}).get(profile_id)
        if not record and name:
            for p_id, rec in self.state.get("teachers", {}).items():
                if rec.get("name") == name:
                    record = rec
                    break

        # Mode: new-only
        if mode == "new-only":
            has_existing_id = bool(anchors.get("known_orcid") or anchors.get("known_scholar"))
            if record or has_existing_id:
                cached = record.get("enriched_item") if record else None
                return False, cached, "new-only mode: already has scientometrics or state record"
            return True, None, "new-only mode: unpopulated profile"

        # Mode: incremental (default)
        if not record:
            return True, None, "New teacher (not in state)"

        # Check if content changed
        if record.get("content_hash") != content_hash:
            return True, None, "Data modified (publications or identifiers changed)"

        status = record.get("status") or ""
        # If previous status was unresolved, re-check
        if status.startswith("NEEDS REVIEW") or status.startswith("MISSING") or "ERROR" in status:
            return True, None, f"Retrying unresolved status ({status})"

        # If previous status was verified (AUTO or GROUND TRUTH)
        if status.startswith("VERIFIED") or "VERIFIED" in status:
            # Check TTL
            last_checked_str = record.get("last_checked")
            if last_checked_str:
                try:
                    last_checked = datetime.fromisoformat(last_checked_str)
                    if last_checked.tzinfo is None:
                        last_checked = last_checked.replace(tzinfo=timezone.utc)
                    age_days = (datetime.now(timezone.utc) - last_checked).total_seconds() / 86400.0
                    if age_days > ttl_days:
                        return True, None, f"TTL audit expired ({age_days:.1f} days > {ttl_days}d limit)"
                except Exception:
                    pass

            cached_item = record.get("enriched_item")
            return False, cached_item, f"Verified cache hit (hash unchanged, age < {ttl_days}d)"

        return True, None, "Uncertain status"

    def record_result(
        self,
        profile_id: str,
        name: str,
        content_hash: str,
        enriched_item: Dict
    ):
        """Stores the resolution result in the state dictionary."""
        if not self.enabled:
            return

        res = enriched_item.get("resolution", {})
        self.state.setdefault("teachers", {})[profile_id] = {
            "name": name,
            "content_hash": content_hash,
            "status": res.get("status"),
            "confidence_score": res.get("confidence_score"),
            "orcid": (res.get("orcid") or {}).get("orcid_id"),
            "scholar": (res.get("scholar") or {}).get("scholar_id"),
            "discovery_path": res.get("discovery_path"),
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "enriched_item": enriched_item
        }


# ==============================================================================
# BRIDGE RUNNER & ENRICHMENT
# ==============================================================================
def run_bridge(
    teachers: List[Dict],
    faculty_id: str = "social-sciences",
    verbose: bool = True,
    serpapi_key: Optional[str] = None,
    serper_key: Optional[str] = None,
    limit: Optional[int] = None,
    mode: str = "incremental",
    state_file: Optional[str] = None,
    ttl_days: int = 30,
    use_state: bool = True
) -> List[Dict]:
    """
    Iterates through faculty-data teachers, extracts anchors, dispatches to
    faculty_matcher, and returns enriched profiles.
    Supports incremental synchronization via SyncStateManager.
    """
    enriched_results = []
    to_process = teachers[:limit] if limit else teachers
    state_mgr = SyncStateManager(state_file=state_file, enabled=use_state)

    if verbose:
        print("=" * 80)
        mode_desc = f"Mode: {mode}" + (f", TTL: {ttl_days}d" if mode == 'incremental' else "")
        print(f"🌉 KSE FACULTY DATA BRIDGE: Processing {len(to_process)} teacher(s) from '{faculty_id}' [{mode_desc}]")
        print("=" * 80)

    processed_count = 0
    skipped_count = 0

    for idx, teacher in enumerate(to_process, 1):
        anchors = extract_teacher_anchors(teacher)
        name = anchors["name"]
        clean_name_slug = re.sub(r'\s+', '_', name.lower()) if name else ""
        clean_fallback_id = f"name_{clean_name_slug}" if clean_name_slug else f"unknown_{idx}"
        profile_id = anchors["profile_id"] or clean_fallback_id
        works = anchors["known_works"]
        orcid = anchors["known_orcid"]
        scholar = anchors["known_scholar"]
        t_faculty = teacher.get("faculty_id") or faculty_id

        content_hash = SyncStateManager.compute_content_hash(name, anchors)

        should_run, cached_item, decision_reason = state_mgr.should_process(
            profile_id=profile_id,
            name=name,
            content_hash=content_hash,
            anchors=anchors,
            mode=mode,
            ttl_days=ttl_days
        )

        if not should_run and cached_item:
            skipped_count += 1
            if verbose:
                c_res = cached_item.get("resolution", {})
                print(f"\n[{idx}/{len(to_process)}] ⏩ [SKIP (CACHED)]: {name}")
                print(f"  🏢 Profile ID: {profile_id} (Faculty: {t_faculty})")
                print(f"  💡 Reason: {decision_reason}")
                print(f"  [STATUS]: {c_res.get('status')} (Score: {c_res.get('confidence_score')}/100)")
                if c_res.get('discovery_path'):
                    print(f"  📌 Маршрут пошуку: {c_res.get('discovery_path')}")
            enriched_results.append(cached_item)
            continue

        processed_count += 1

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
            print(f"\n[{idx}/{len(to_process)}] 🔍 [PROCESS]: {name}")
            print(f"  🏢 Profile ID: {profile_id} (Faculty: {t_faculty})")
            print(f"  💡 Reason: {decision_reason}")
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
            serper_key=serper_key,
            known_works=works,
            known_orcid=orcid,
            known_scholar=scholar
        )

        resolved_orcid = (match_res.get("orcid") or {}).get("orcid_id")
        resolved_scholar = (match_res.get("scholar") or {}).get("scholar_id")
        status = match_res.get("status")
        confidence = match_res.get("confidence_score")
        discovery_path = match_res.get("discovery_path")

        if verbose:
            print(f"  📌 Маршрут пошуку: {discovery_path}")

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

        # Propose PATCH only when verified (strictly prevents auto-patching homonym risks)
        is_safe_to_patch = (status.startswith("VERIFIED") or "ORCID VERIFIED" in status or "SCHOLAR VERIFIED" in status) and not status.startswith("NEEDS REVIEW")

        proposed_patch = {
            "profile": {
                "scientometrics": "\n".join(new_sciento_lines)
            },
            "versions": {
                "scientometrics": anchors["field_versions"].get("scientometrics") or 1
            }
        } if (discovered_orcid or discovered_scholar) and is_safe_to_patch else None

        enriched_item = {
            "profile_id": profile_id,
            "faculty_id": t_faculty,
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
                "discovery_path": discovery_path,
                "discovery_steps": match_res.get("discovery_steps", []),
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
        state_mgr.record_result(profile_id, name, content_hash, enriched_item)
        enriched_results.append(enriched_item)

    state_mgr.save()

    if verbose and use_state:
        print(f"\n⚡ State sync summary: {processed_count} processed, {skipped_count} skipped (cached). State saved to '{state_mgr.state_file}'.")

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
    parser.add_argument("-n", "--teacher-name", dest="teacher_name", help="Query a specific teacher by name.")
    parser.add_argument("--fetch-only", action="store_true", help="Only fetch and save the teacher JSON without running matching.")
    parser.add_argument("--api-url", default=DEFAULT_FACULTY_DATA_URL, help=f"Base URL of faculty-data API (default: {DEFAULT_FACULTY_DATA_URL}).")
    parser.add_argument("--api-key", help="X-Faculty-Data-Key for live API authentication.")
    parser.add_argument("--faculty", default="social-sciences", help="Faculty ID to process ('all' to search all faculties; default: social-sciences).")
    parser.add_argument("--serpapi-key", help="SerpAPI key for Scholar lookups (defaults to SERPAPI_API_KEY from .env).")
    parser.add_argument("--serper-key", help="Serper.dev key for Scholar lookups (defaults to SERPER_API_KEY from .env).")
    parser.add_argument("-o", "--output", help="File path to save enriched results JSON.")
    parser.add_argument("-l", "--limit", type=int, help="Limit number of teachers to process.")
    parser.add_argument(
        "--mode",
        choices=["incremental", "new-only", "force-all"],
        default="incremental",
        help="Sync mode: 'incremental' (process new/modified or expired TTL; default), 'new-only' (only unpopulated profiles), 'force-all' (re-verify all)."
    )
    parser.add_argument(
        "--state-file",
        default=".matcher_state.json",
        help="Path to JSON state file tracking hashes and timestamps (default: .matcher_state.json)."
    )
    parser.add_argument(
        "--ttl-days",
        type=int,
        default=30,
        help="Number of days before a verified profile is re-audited in incremental mode (default: 30)."
    )
    parser.add_argument(
        "--no-state",
        action="store_true",
        help="Disable state management and caching entirely."
    )
    parser.add_argument("--json", action="store_true", help="Output pure JSON to stdout.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress verbose processing logs.")

    args = parser.parse_args()

    input_file = args.file
    if args.mock and not input_file:
        input_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_faculty_data.json")

    # Key Auto-detection: If serpapi_key has 40 chars, treat as serper_key
    serper_k = args.serper_key or os.getenv("SERPER_API_KEY")
    serpapi_k = args.serpapi_key or os.getenv("SERPAPI_API_KEY")
    if serpapi_k and len(serpapi_k.strip()) == 40 and not serper_k:
        serper_k = serpapi_k
        serpapi_k = None

    try:
        faculty_id, teachers = load_teachers_from_source(
            file_path=input_file,
            api_url=args.api_url if (args.api_key or os.getenv("FACULTY_DATA_API_KEY")) else None,
            api_key=args.api_key,
            faculty_id=args.faculty,
            teacher_name_filter=args.teacher_name
        )
    except Exception as e:
        print(f"Error loading faculty data: {e}", file=sys.stderr)
        sys.exit(1)

    if not teachers:
        if args.teacher_name:
            print(f"No teacher matching '{args.teacher_name}' found in faculty '{faculty_id}'.", file=sys.stderr)
        else:
            print(f"No teachers found in '{faculty_id}'.", file=sys.stderr)
        sys.exit(1)

    # If --fetch-only was requested: just output the raw teacher JSON and exit
    if args.fetch_only:
        payload = teachers[0] if len(teachers) == 1 else teachers
        if args.output and args.output != "-":
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            if not args.quiet:
                print(f"Successfully fetched and saved {len(teachers)} teacher record(s) to '{args.output}'.")
        else:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        sys.exit(0)

    verbose = not (args.json or args.quiet)

    results = run_bridge(
        teachers=teachers,
        faculty_id=faculty_id,
        verbose=verbose,
        serpapi_key=serpapi_k,
        serper_key=serper_k,
        limit=args.limit,
        mode=args.mode,
        state_file=args.state_file,
        ttl_days=args.ttl_days,
        use_state=not args.no_state
    )

    if args.json or args.output == "-":
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
        print(f"Total processed: {len(results)} faculty member(s).")

    if args.output and args.output != "-":
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        if not args.json and not args.quiet:
            print(f"Enriched results successfully saved to '{args.output}'.")


if __name__ == "__main__":
    main()
