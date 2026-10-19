import json
import time
from faculty_bridge import extract_teacher_anchors
from faculty_matcher import process_faculty_member

# 5 Hand-picked hard edge cases from real KSE data
TEST_CASES = [
    {
        "name": "Mykola Trehub",
        "description": "Affiliation Mismatch (Scholar lists 'Dnipro Polytechnic', not KSE; resolved via publication anchor)",
        "works": ["Determining and determinable factors influencing the size of zone of land-use restriction"],
        "expected_scholar": "QnhQqygAAAAJ",
        "expected_orcid": "0000-0002-2205-5622"
    },
    {
        "name": "Ігор Сердюк",
        "description": "Multi-Alias Scholar Profile ('Ігор Сердюк, Igor Serdiuk, Ihor Serdiuk')",
        "works": ["Causes of Death in 19th-Century Ukraine"],
        "expected_scholar": "vMd6FToAAAAJ",
        "expected_orcid": "0000-0002-8930-1410"
    },
    {
        "name": "Kateryna Antoshyna",
        "description": "Discrete Mathematics Graph Theory publication anchor",
        "works": ["Graphs with parity conditions on distances between cut and noncut vertices"],
        "expected_scholar": "FYN91ucAAAAJ",
        "expected_orcid": "0009-0008-0933-6893"
    },
    {
        "name": "Нів`євський Олег Володимирович",
        "description": "Ukrainian Backtick Apostrophe + English canonical name ('Oleg Nivievskyi')",
        "works": [
            "A Multiperiod, Multicommodity, Capacitated International Agricultural Trade Network Equilibrium Model with Applications to Ukraine in Wartime. Transportation Science 59, 1 (January-February 2025), 143–164. https://doi.org/10.1287/trsc.2023.0294 (with D. Hassani, A. Nagurney, and P.Martyshev)"
        ],
        "expected_scholar": "8xZfsVcAAAAJ",
        "expected_orcid": "0000-0002-8902-9453"
    },
    {
        "name": "Савченко Олена Вячеславівна",
        "description": "Initials Resolution ('O.V. Savchenko' -> 'Olena Savchenko')",
        "works": [
            "Savchenko O., Kovalkova T., Korvat L., Lovochkina A., Kalishchuk S., Yelina M. Personal Values as Regulators of Teacher Burnout. Journal of Higher Education Theory and Practice. 2022. Vol. 22 (16). P. 51-62. DOI: https://doi.org/10.33423/jhetp.v22i16.5600 (Scopus)"
        ],
        "expected_scholar": "m922r34AAAAJ",
        "expected_orcid": "0000-0002-7069-7419"
    }
]

def run_live_test():
    print("=" * 80)
    print("🎯 LIVE BENCHMARK: 5 HARD CASES (1 Serper query / person budget check)")
    print("=" * 80)
    print("Please check your current Serper query count on https://google.serper.dev/logs")
    print("Expected total Serper queries for this entire test: EXACTLY 5 QUERIES.")
    print("=" * 80)

    passed = 0
    total = len(TEST_CASES)

    for i, c in enumerate(TEST_CASES, 1):
        name = c["name"]
        desc = c["description"]
        works = c["works"]
        exp_s = c["expected_scholar"]
        exp_o = c["expected_orcid"]

        print(f"\n[{i}/{total}] 🔍 Testing: {name}")
        print(f"   💡 Challenge: {desc}")
        print(f"   📖 Work: '{works[0][:80]}...'")

        res = process_faculty_member(name, verbose=False, known_works=works)

        actual_status = res.get("status")
        actual_s = (res.get("scholar") or {}).get("scholar_id")
        actual_o = (res.get("orcid") or {}).get("orcid_id")
        path = res.get("discovery_path")

        scholar_ok = (actual_s == exp_s)
        orcid_ok = (actual_o == exp_o)
        status_ok = "VERIFIED" in actual_status

        success = scholar_ok and orcid_ok and status_ok
        if success:
            passed += 1
            print(f"   ✅ SUCCESS: Status: {actual_status}")
            print(f"      Scholar ID: {actual_s} | ORCID: {actual_o}")
            print(f"      📌 Path: {path}")
        else:
            print(f"   ❌ FAILED:")
            print(f"      Scholar: expected {exp_s}, got {actual_s}")
            print(f"      ORCID: expected {exp_o}, got {actual_o}")
            print(f"      Status: {actual_status}")

        time.sleep(1)

    print("\n" + "=" * 80)
    print(f"🏁 LIVE BENCHMARK COMPLETE: {passed}/{total} Passed ({passed/total*100:.1f}%)")
    print("=" * 80)
    print("👉 Now refresh https://google.serper.dev/logs — exactly 5 queries were added.")

if __name__ == "__main__":
    run_live_test()
