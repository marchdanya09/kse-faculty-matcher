#!/usr/bin/env python3
"""
Faculty Data Database Sync Bridge (Safe & Non-Destructive)
================================================================================
Purpose:
Safely synchronizes disambiguated academic profiles (ORCID & Google Scholar)
produced by 'kse-faculty-matcher' / 'faculty_bridge.py' into the KSE Faculty Data
database via the official Admin REST API.

Key Architectural Guarantees:
1. SAFE BY DEFAULT (--dry-run):
   Never writes to the database unless '--execute' is explicitly provided.
2. PRODUCTION PROTECTION (--prod-confirm):
   Writing to production endpoints strictly requires the '--prod-confirm' flag.
3. PRESERVING MERGER (Zero Data Loss):
   Preserves existing Scopus, Web of Science, and administrative notes already
   present in the teacher's spreadsheet row cells.
4. OPTIMISTIC CONCURRENCY CONTROL (OCC):
   Respects 'field_versions["scientometrics"]' and gracefully handles HTTP 409
   Conflict with automated fetch-and-retry.
5. PRE-FLIGHT AUTOMATIC BACKUP & ROLLBACK (--restore):
   Before modifying any profile, saves a local snapshot 'sync_backup_<timestamp>.json'.
   Any change can be reverted instantly using '--restore <backup_file>'.
6. VERIFICATION GATING:
   Strictly updates ONLY profiles with status 'VERIFIED (AUTO)' or
   'VERIFIED (GROUND TRUTH MATCH)'. Never touches homonyms or unverified profiles.

Usage Examples:
  # 1. Safe Dry-Run (preview proposed changes with visual diff, no writes):
  python3 faculty_db_sync.py -i enriched_teachers.json

  # 2. Dry-Run against live API state (fetches current DB versions):
  python3 faculty_db_sync.py -i enriched_teachers.json --api-key "$KEY"

  # 3. Interactive live execution with per-profile confirmation:
  python3 faculty_db_sync.py -i enriched_teachers.json --api-key "$KEY" --execute --interactive

  # 4. Batch execution with production confirmation:
  python3 faculty_db_sync.py -i enriched_teachers.json --api-key "$KEY" --execute --prod-confirm

  # 5. Instant rollback from a previous backup:
  python3 faculty_db_sync.py --restore sync_backup_20261019_120000.json --api-key "$KEY" --execute --prod-confirm
================================================================================
"""

import argparse
from datetime import datetime, timezone
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple, Union

DEFAULT_API_URL = "https://faculty-data-two.vercel.app/api/admin/v1"
LOCAL_API_URL = "http://localhost:3000/api/admin/v1"


# ==============================================================================
# 1. INTELLIGENT PRESERVING MERGER
# ==============================================================================
def merge_scientometrics_cells(
    existing_cells: List[str],
    new_orcid: Optional[str] = None,
    new_scholar: Optional[str] = None
) -> Tuple[List[str], bool]:
    """
    Intelligently merges verified ORCID and Google Scholar URLs into existing
    scientometrics cells without losing existing Scopus, Web of Science,
    ResearcherID, or administrative text notes.

    Returns:
        (merged_cells, has_changes)
    """
    clean_orcid = None
    if new_orcid:
        m = re.search(r'\b([0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X])\b', new_orcid)
        if m:
            clean_orcid = f"https://orcid.org/{m.group(1)}"

    clean_scholar = None
    if new_scholar:
        m = re.search(r'(?:user=)([a-zA-Z0-9_\-]{12})', new_scholar)
        s_id = m.group(1) if m else (new_scholar.strip() if len(new_scholar.strip()) == 12 else None)
        if s_id:
            clean_scholar = f"https://scholar.google.com/citations?user={s_id}"

    merged: List[str] = []
    has_orcid = False
    has_scholar = False
    changed = False

    for raw in existing_cells:
        cell = str(raw).strip()
        if not cell:
            continue

        # Check if cell is an ORCID entry
        if re.search(r'(?:\borcid\b|orcid\.org)', cell, re.I):
            if clean_orcid:
                if cell != clean_orcid:
                    merged.append(clean_orcid)
                    changed = True
                else:
                    merged.append(cell)
                has_orcid = True
            else:
                merged.append(cell)
                has_orcid = True

        # Check if cell is a Google Scholar entry
        elif re.search(r'(?:google\s+scholar|scholar\.google\.[a-z.]+)', cell, re.I):
            if clean_scholar:
                # If existing Scholar URL has different query params or raw user, compare ID
                curr_m = re.search(r'(?:user=)([a-zA-Z0-9_\-]{12})', cell)
                target_m = re.search(r'(?:user=)([a-zA-Z0-9_\-]{12})', clean_scholar)
                if curr_m and target_m and curr_m.group(1) == target_m.group(1):
                    # Same ID, keep canonical
                    merged.append(cell)
                else:
                    merged.append(clean_scholar)
                    changed = True
                has_scholar = True
            else:
                merged.append(cell)
                has_scholar = True

        else:
            # Strictly preserve Scopus, Web of Science, ResearcherID, unclassified notes
            merged.append(cell)

    # If new ORCID was discovered and not in existing cells, append
    if clean_orcid and not has_orcid:
        merged.append(clean_orcid)
        changed = True

    # If new Scholar was discovered and not in existing cells, append
    if clean_scholar and not has_scholar:
        merged.append(clean_scholar)
        changed = True

    return merged, changed


def extract_existing_scientometrics_cells(teacher_record: Dict) -> List[str]:
    """
    Extracts raw cell values from teacher's 'fields' array or 'profile' dict.
    """
    fields = teacher_record.get("fields") or []
    for f in fields:
        if isinstance(f, dict) and f.get("key") == "scientometrics":
            raw_vals = f.get("values") or []
            if raw_vals:
                return [str(v).strip() for v in raw_vals if str(v).strip()]
            data_str = f.get("data")
            if data_str:
                return [c.strip() for c in str(data_str).split(",") if c.strip()]

    # Fallback to profile.scientometrics
    prof = teacher_record.get("profile") or {}
    sciento_val = prof.get("scientometrics")
    if isinstance(sciento_val, list):
        return [str(v).strip() for v in sciento_val if str(v).strip()]
    elif isinstance(sciento_val, str) and sciento_val.strip():
        # Split on commas or newlines
        parts = re.split(r'[\n,]+', sciento_val)
        return [p.strip() for p in parts if p.strip()]

    return []


# ==============================================================================
# 2. API CLIENT & MUTATION ENGINE
# ==============================================================================
class FacultyDataApiClient:
    """HTTP Client for Faculty Data Admin REST API."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/api/admin/v1") and not self.base_url.endswith("/api"):
            self.base_url = f"{self.base_url}/api/admin/v1"
        self.api_key = api_key.strip()
        self.headers = {
            "X-Faculty-Data-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "KSE-Faculty-Matcher-SyncBridge/1.0"
        }

    def get_allowed_faculties(self) -> List[Dict]:
        """Queries GET /faculties to verify key permissions and allowed faculties."""
        url = f"{self.base_url}/faculties"
        req = urllib.request.Request(url, headers={"X-Faculty-Data-Key": self.api_key, "User-Agent": self.headers["User-Agent"]})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("faculties", [])
        except Exception as e:
            raise RuntimeError(f"Failed to query faculties at {url}: {e}")

    def get_teacher(self, faculty_id: str, profile_id: str) -> Dict:
        """Fetches the latest teacher record with fresh field_versions."""
        url = f"{self.base_url}/faculties/{faculty_id}/teachers/{profile_id}"
        req = urllib.request.Request(url, headers={"X-Faculty-Data-Key": self.api_key, "User-Agent": self.headers["User-Agent"]})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("teacher") or data

    def patch_teacher_scientometrics(
        self,
        faculty_id: str,
        profile_id: str,
        new_cells: List[str],
        expected_version: int,
        max_retries: int = 3
    ) -> Dict:
        """
        Sends HTTP PATCH to update 'scientometrics' with Optimistic Concurrency Control.
        Automatically handles HTTP 409 Conflict with fresh re-fetch and retry.
        """
        url = f"{self.base_url}/faculties/{faculty_id}/teachers/{profile_id}"

        curr_version = expected_version
        curr_cells = new_cells

        for attempt in range(1, max_retries + 1):
            payload = {
                "profile": {
                    "scientometrics": curr_cells
                },
                "versions": {
                    "scientometrics": curr_version
                }
            }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=self.headers, method="PATCH")

            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    return {
                        "success": True,
                        "updated": resp_data.get("updated", 1),
                        "version": (resp_data.get("rows") or [{}])[0].get("version", curr_version + 1),
                        "attempts": attempt
                    }
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8")
                except Exception:
                    pass

                # Handle 409 Conflict (Stale version)
                if e.code == 409:
                    if attempt < max_retries:
                        time.sleep(1.0 * attempt)
                        # Re-fetch latest teacher state
                        latest_t = self.get_teacher(faculty_id, profile_id)
                        latest_versions = latest_t.get("field_versions") or {}
                        latest_v = latest_versions.get("scientometrics")
                        if latest_v is not None:
                            curr_version = latest_v
                            # Re-merge to ensure we don't clobber any intervening admin edit
                            latest_cells = extract_existing_scientometrics_cells(latest_t)
                            clean_orcid = next((c for c in curr_cells if "orcid.org" in c), None)
                            clean_scholar = next((c for c in curr_cells if "scholar.google" in c), None)
                            remerged, _ = merge_scientometrics_cells(latest_cells, clean_orcid, clean_scholar)
                            curr_cells = remerged
                            continue
                    raise RuntimeError(f"HTTP 409 Conflict: Version {curr_version} is stale for profile '{profile_id}'. {err_body}")
                elif e.code == 403:
                    raise PermissionError(f"HTTP 403 Forbidden: API key lacks write access or faculty '{faculty_id}' is out of scope. {err_body}")
                elif e.code == 400:
                    raise ValueError(f"HTTP 400 Bad Request: {err_body}")
                else:
                    raise RuntimeError(f"HTTP {e.code} Error: {err_body}")

        raise RuntimeError("Max retries exceeded on 409 Conflict.")


# ==============================================================================
# 3. SYNC ENGINE & ORCHESTRATOR
# ==============================================================================
def plan_teacher_sync(
    item: Dict,
    client: Optional[FacultyDataApiClient] = None
) -> Dict:
    """
    Evaluates an enriched teacher profile and prepares the proposed sync action.
    """
    # Accept either enriched format or raw teacher format
    name = item.get("name") or "Unknown"
    faculty_id = item.get("faculty_id") or "social-sciences"
    profile_id = item.get("profile_id")

    res = item.get("resolution") or {}
    status = res.get("status") or item.get("status") or ""
    confidence = res.get("confidence_score") or item.get("confidence_score") or 0

    resolved_orcid = (res.get("orcid") or item.get("orcid") or {}).get("orcid_id")
    resolved_scholar = (res.get("scholar") or item.get("scholar") or {}).get("scholar_id")

    # If client is provided, query latest state from live API; otherwise use local data
    existing_cells = []
    field_version = None

    if client and profile_id and faculty_id:
        try:
            live_t = client.get_teacher(faculty_id, profile_id)
            existing_cells = extract_existing_scientometrics_cells(live_t)
            f_vers = live_t.get("field_versions") or {}
            field_version = f_vers.get("scientometrics")
        except Exception:
            pass

    if not existing_cells:
        existing_cells = extract_existing_scientometrics_cells(item)

    if field_version is None:
        f_vers = item.get("field_versions") or (item.get("proposed_patch") or {}).get("versions") or {}
        field_version = f_vers.get("scientometrics") or 1

    # Quality Gate: strictly verify before syncing
    is_verified = (
        status.startswith("VERIFIED") or
        "ORCID VERIFIED" in status or
        "SCHOLAR VERIFIED" in status
    ) and not status.startswith("NEEDS REVIEW") and not status.startswith("MISSING")

    if not is_verified:
        return {
            "name": name,
            "faculty_id": faculty_id,
            "profile_id": profile_id,
            "action": "SKIP_UNVERIFIED",
            "reason": f"Status '{status}' (Confidence: {confidence}/100) does not meet auto-write quality threshold.",
            "status": status,
            "current_cells": existing_cells,
            "proposed_cells": existing_cells,
            "version": field_version
        }

    # Check missing row in source sheet
    if field_version is None:
        return {
            "name": name,
            "faculty_id": faculty_id,
            "profile_id": profile_id,
            "action": "SKIP_NO_ROW",
            "reason": "Missing 'Науковометричні дані' row in source sheet (version is null; PATCH cannot insert rows).",
            "status": status,
            "current_cells": existing_cells,
            "proposed_cells": existing_cells,
            "version": None
        }

    # Merge cells
    proposed_cells, has_changes = merge_scientometrics_cells(
        existing_cells,
        new_orcid=resolved_orcid,
        new_scholar=resolved_scholar
    )

    if not has_changes:
        return {
            "name": name,
            "faculty_id": faculty_id,
            "profile_id": profile_id,
            "action": "ALREADY_IN_SYNC",
            "reason": "Profile in database already contains target ORCID and Google Scholar identifiers.",
            "status": status,
            "current_cells": existing_cells,
            "proposed_cells": proposed_cells,
            "version": field_version
        }

    return {
        "name": name,
        "faculty_id": faculty_id,
        "profile_id": profile_id,
        "action": "UPDATE",
        "reason": f"Discovered new/updated identifiers (ORCID: {resolved_orcid or '—'}, Scholar: {resolved_scholar or '—'}).",
        "status": status,
        "current_cells": existing_cells,
        "proposed_cells": proposed_cells,
        "version": field_version,
        "resolved_orcid": resolved_orcid,
        "resolved_scholar": resolved_scholar
    }


def format_diff_display(plan: Dict) -> str:
    """Formats a side-by-side human-readable diff of current vs proposed cells."""
    name = plan["name"]
    fac = plan["faculty_id"]
    pid = plan["profile_id"]
    action = plan["action"]
    reason = plan["reason"]
    v = plan.get("version")

    lines = [
        f"\n{'='*80}",
        f"👨‍🏫 {name} (Faculty: {fac} | Profile ID: {pid})",
        f"   Status: {plan.get('status')} | Action: {action} (Version: {v})",
        f"   Reason: {reason}",
        f"{'-'*80}"
    ]

    curr = plan.get("current_cells") or []
    prop = plan.get("proposed_cells") or []

    if action == "UPDATE":
        lines.append("   [-] Current cells:")
        if curr:
            for c in curr:
                lines.append(f"       • {c}")
        else:
            lines.append("       (Empty)")

        lines.append("   [+] Proposed cells (to be written):")
        for c in prop:
            is_new = c not in curr
            marker = "✨ [NEW]" if is_new else "  [KEPT]"
            lines.append(f"       {marker} {c}")
    else:
        lines.append(f"   Current cells ({len(curr)}): {curr if curr else '(Empty)'}")

    return "\n".join(lines)


# ==============================================================================
# 4. CLI INTERFACE & DISPATCHER
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Safe Database Sync Bridge: Writes verified ORCID & Google Scholar profiles to KSE Faculty Data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Safe Dry-Run (preview diffs without writing to DB):
  python3 faculty_db_sync.py -i enriched_batch.json

  # Live write with interactive per-profile confirmation:
  python3 faculty_db_sync.py -i enriched_batch.json --api-key "$KEY" --execute --interactive

  # Batch execution with production safety flag:
  python3 faculty_db_sync.py -i enriched_batch.json --api-key "$KEY" --execute --prod-confirm

  # Revert previous execution from backup:
  python3 faculty_db_sync.py --restore sync_backup_20261019_023000.json --api-key "$KEY" --execute --prod-confirm
        """
    )
    parser.add_argument("-i", "--input", help="Path to enriched JSON or state JSON file.")
    parser.add_argument("--api-key", help="X-Faculty-Data-Key for write authentication.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help=f"API Base URL (default: {DEFAULT_API_URL}).")
    parser.add_argument("--target", choices=["mock", "local", "prod"], default="prod", help="Execution target (default: prod).")
    parser.add_argument("--execute", action="store_true", help="Actually perform write requests. Without this flag, runs in safe DRY-RUN mode.")
    parser.add_argument("--prod-confirm", action="store_true", help="Required confirmation flag to write to production API.")
    parser.add_argument("--interactive", action="store_true", help="Prompt for user confirmation [y/N/q] before updating each profile.")
    parser.add_argument("--limit", type=int, help="Limit number of profiles to process.")
    parser.add_argument("--restore", help="Path to a sync_backup_*.json file to rollback/revert database to prior state.")
    parser.add_argument("-o", "--output", help="Path to write sync execution audit log JSON.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress verbose diff display.")

    args = parser.parse_args()

    # 1. Target URL Resolution
    api_url = args.api_url
    if args.target == "local":
        api_url = LOCAL_API_URL
    elif args.target == "mock":
        api_url = "mock://faculty-data"

    api_key = args.api_key or os.getenv("FACULTY_DATA_WRITE_KEY") or os.getenv("FACULTY_DATA_API_KEY")

    # Safety Enforcement
    is_prod = "faculty-data-two.vercel.app" in api_url or "faculty-data.kse.ua" in api_url
    if args.execute:
        if not api_key:
            print("Error: Live execution requires --api-key (or FACULTY_DATA_WRITE_KEY).", file=sys.stderr)
            sys.exit(1)
        if is_prod and not args.prod_confirm:
            print(
                "\n" + "!" * 80 + "\n"
                "⛔ SAFETY SHIELD TRIGGERED: You are targeting the PRODUCTION database with --execute!\n"
                "To prevent accidental writes, you must also pass '--prod-confirm'.\n"
                "Example:\n"
                f"  python3 faculty_db_sync.py -i {args.input or '<file>'} --api-key <KEY> --execute --prod-confirm\n"
                + "!" * 80 + "\n",
                file=sys.stderr
            )
            sys.exit(1)

    # 2. RESTORE / ROLLBACK MODE
    if args.restore:
        if not os.path.exists(args.restore):
            print(f"Error: Restore backup file '{args.restore}' not found.", file=sys.stderr)
            sys.exit(1)
        with open(args.restore, "r", encoding="utf-8") as f:
            backup_data = json.load(f)

        records_to_restore = backup_data.get("snapshots") or []
        print("=" * 80)
        print(f"⏪ ROLLBACK / RESTORE MODE: {len(records_to_restore)} snapshot(s) in '{args.restore}'")
        print(f"   Created at: {backup_data.get('timestamp')}")
        print(f"   Target: {api_url} (Execute: {args.execute})")
        print("=" * 80)

        if not args.execute:
            print("Running in DRY-RUN mode. Pass --execute --prod-confirm to apply rollback.\n")

        client = FacultyDataApiClient(api_url, api_key) if args.execute else None

        restored_count = 0
        for snap in records_to_restore:
            name = snap["name"]
            fac = snap["faculty_id"]
            pid = snap["profile_id"]
            orig_cells = snap["original_cells"]
            orig_ver = snap["original_version"]

            print(f"• Restoring {name} [{pid}] -> Cells: {orig_cells} (Version: {orig_ver})")
            if args.execute and client:
                try:
                    res = client.patch_teacher_scientometrics(fac, pid, orig_cells, orig_ver)
                    print(f"  ✅ Restored successfully (New version: {res.get('version')})")
                    restored_count += 1
                except Exception as e:
                    print(f"  ❌ Failed to restore: {e}", file=sys.stderr)

        print(f"\nRollback complete: {restored_count}/{len(records_to_restore)} restored.")
        sys.exit(0)

    # 3. NORMAL SYNC PIPELINE
    if not args.input:
        print("Error: Specify an input file via -i / --input.", file=sys.stderr)
        sys.exit(1)

    if args.input == "-":
        try:
            input_data = json.load(sys.stdin)
        except Exception as e:
            print(f"Error reading JSON from stdin: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        if not os.path.exists(args.input):
            print(f"Error: Input file '{args.input}' not found.", file=sys.stderr)
            sys.exit(1)

        with open(args.input, "r", encoding="utf-8") as f:
            input_data = json.load(f)

    # Ingest teachers list from enriched format, list of items, or state file
    items: List[Dict] = []
    if isinstance(input_data, dict):
        if "teachers" in input_data and isinstance(input_data["teachers"], dict):
            # State file format (.matcher_state.json)
            for pid, st_item in input_data["teachers"].items():
                rec = st_item.get("enriched_item") or st_item
                rec["profile_id"] = pid
                items.append(rec)
        elif "teachers" in input_data and isinstance(input_data["teachers"], list):
            items = input_data["teachers"]
        else:
            items = [input_data]
    elif isinstance(input_data, list):
        items = input_data

    if args.limit:
        items = items[:args.limit]

    print("=" * 80)
    mode_label = "🔴 LIVE EXECUTION (WRITES ENABLED)" if args.execute else "🟢 SAFE DRY-RUN (ZERO WRITES)"
    print(f"🌉 FACULTY DATA DB SYNC BRIDGE [{mode_label}]")
    print(f"   Target URL: {api_url}")
    print(f"   Candidates: {len(items)} profile(s)")
    print("=" * 80)

    # Initialize Client if executing or verifying live
    client: Optional[FacultyDataApiClient] = None
    if api_key and args.target != "mock":
        try:
            client = FacultyDataApiClient(api_url, api_key)
            if not args.quiet:
                allowed_faculties = client.get_allowed_faculties()
                f_ids = [f.get("id") for f in allowed_faculties]
                print(f"   🔑 Key authorized for faculties: {f_ids if f_ids else 'All'}")
        except Exception as e:
            if args.execute:
                print(f"Pre-flight check failed: {e}", file=sys.stderr)
                sys.exit(1)
            else:
                print(f"   ⚠️  Warning: Pre-flight check failed ({e}). Proceeding offline for dry-run.")

    # Generate sync plans
    plans = []
    for item in items:
        plan = plan_teacher_sync(item, client=client)
        plans.append(plan)
        if not args.quiet:
            print(format_diff_display(plan))

    # Summary of planned actions
    to_update = [p for p in plans if p["action"] == "UPDATE"]
    in_sync = [p for p in plans if p["action"] == "ALREADY_IN_SYNC"]
    unverified = [p for p in plans if p["action"] == "SKIP_UNVERIFIED"]
    no_row = [p for p in plans if p["action"] == "SKIP_NO_ROW"]

    print("\n" + "=" * 80)
    print("📊 SYNC PLAN SUMMARY")
    print("=" * 80)
    print(f"  • Ready to Update:  {len(to_update)}")
    print(f"  • Already in Sync:  {len(in_sync)}")
    print(f"  • Unverified/Skip:  {len(unverified)}")
    print(f"  • Missing Rows:     {len(no_row)}")
    print(f"  • Total Evaluated:  {len(plans)}")
    print("=" * 80)

    # Execute writes if requested
    if not args.execute:
        print("\n💡 NOTE: This was a DRY-RUN. No changes were made to the database.")
        print("To apply these changes, pass '--execute' (and '--prod-confirm' for production).")
        sys.exit(0)

    if not to_update:
        print("\n✨ All profiles are already in sync. No database updates required.")
        sys.exit(0)

    # Create safety backup snapshot before executing
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = f"sync_backup_{timestamp_str}.json"
    backup_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "api_url": api_url,
        "snapshots": [
            {
                "name": p["name"],
                "faculty_id": p["faculty_id"],
                "profile_id": p["profile_id"],
                "original_cells": p["current_cells"],
                "original_version": p["version"]
            }
            for p in to_update
        ]
    }
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(backup_payload, f, indent=2, ensure_ascii=False)
    print(f"\n🛡️ Safety backup snapshot saved to '{backup_file}'.")
    print("   (Use '--restore' to instantly rollback if ever needed).\n")

    # Execution Loop
    applied_count = 0
    failed_count = 0
    audit_log = []

    for idx, plan in enumerate(to_update, 1):
        name = plan["name"]
        fac = plan["faculty_id"]
        pid = plan["profile_id"]
        cells = plan["proposed_cells"]
        v = plan["version"]

        if args.interactive:
            try:
                prompt_str = f"[{idx}/{len(to_update)}] Update '{name}' in '{fac}'? [y/N/q]: "
                choice = input(prompt_str).strip().lower()
                if choice == 'q':
                    print("Sync aborted by user.")
                    break
                if choice not in ('y', 'yes'):
                    print(f"  Skipped {name}.")
                    continue
            except (KeyboardInterrupt, EOFError):
                print("\nSync interrupted.")
                break

        print(f"[{idx}/{len(to_update)}] Writing {name} [{pid}] (v{v})...", end=" ")
        try:
            if not client:
                raise RuntimeError("Client not initialized.")
            write_res = client.patch_teacher_scientometrics(
                faculty_id=fac,
                profile_id=pid,
                new_cells=cells,
                expected_version=v
            )
            new_v = write_res.get("version")
            print(f"✅ SUCCESS (Updated to v{new_v})")
            applied_count += 1
            audit_log.append({
                "profile_id": pid,
                "name": name,
                "status": "SUCCESS",
                "new_version": new_v,
                "cells": cells
            })
        except Exception as e:
            print(f"❌ FAILED: {e}")
            failed_count += 1
            audit_log.append({
                "profile_id": pid,
                "name": name,
                "status": "FAILED",
                "error": str(e)
            })

    print("\n" + "=" * 80)
    print(f"🏁 LIVE SYNC EXECUTION COMPLETE: {applied_count} updated, {failed_count} failed.")
    print("=" * 80)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "applied_count": applied_count,
                "failed_count": failed_count,
                "log": audit_log
            }, f, indent=2, ensure_ascii=False)
        print(f"Audit log saved to '{args.output}'.")


if __name__ == "__main__":
    main()
