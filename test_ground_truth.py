import json
import time
from faculty_matcher import process_faculty_member

test_faculty = [
    {
        "name": "Mykola Trehub",
        "work": "Determining and determinable factors influencing the size of zone of land-use restriction",
        "expected_orcid": "0000-0002-2205-5622",
        "expected_scholar": "QnhQqygAAAAJ"
    },
    {
        "name": "Sergiy Kozerenko",
        "work": "Graphs with small triameters",
        "expected_orcid": "0000-0002-5716-3084",
        "expected_scholar": "_lmN4FkAAAAJ"
    },
    {
        "name": "Kateryna Antoshyna",
        "work": "Graphs with parity conditions on distances between cut and noncut vertices",
        "expected_orcid": "0009-0008-0933-6893",
        "expected_scholar": "FYN91ucAAAAJ"
    },
    {
        "name": "Oleksandra Konopatska",
        "work": "Artificial Intelligence in the Functioning of HR Processes",
        "expected_orcid": "0000-0003-1867-9894",
        "expected_scholar": "W82UtxcAAAAJ"
    },
    {
        "name": "Тимофій Брік",
        "work": "Witnessing Racial Discrimination Mobilizes Intra‐Minority Allyship",
        "expected_orcid": "0000-0002-5542-1019",
        "expected_scholar": "NWO5_WwAAAAJ"
    },
    {
        "name": "Максим Обрізан",
        "work": "Mental health in Germany before, during and after the COVID-19 pandemic",
        "expected_orcid": "0000-0002-0924-0671",
        "expected_scholar": "pIv8OrkAAAAJ"
    },
    {
        "name": "Ігор Сердюк",
        "work": "Causes of Death in 19th-Century Ukraine",
        "expected_orcid": "0000-0002-8930-1410",
        "expected_scholar": "vMd6FToAAAAJ"
    }
]

def run_tests():
    print("=" * 80)
    print("RUNNING GROUND-TRUTH ANCHORED MATCHING BENCHMARK")
    print("=" * 80)

    results = []
    passed = 0
    total = len(test_faculty)

    for i, item in enumerate(test_faculty, 1):
        name = item["name"]
        work = item["work"]
        exp_orcid = item["expected_orcid"]
        exp_scholar = item["expected_scholar"]

        print(f"\n[{i}/{total}] Testing Ground Truth for: {name}")
        print(f"  Supplied work: '{work}'")

        res = process_faculty_member(name, verbose=False, known_works=[work])
        results.append(res)

        actual_status = res.get("status")
        actual_orcid = (res.get("orcid") or {}).get("orcid_id")
        actual_scholar = (res.get("scholar") or {}).get("scholar_id")

        orcid_ok = (actual_orcid == exp_orcid)
        scholar_ok = (actual_scholar == exp_scholar)
        status_ok = (actual_status == "VERIFIED (GROUND TRUTH MATCH)")

        success = orcid_ok and scholar_ok and status_ok
        if success:
            passed += 1
            print(f"  ✅ SUCCESS: Status: {actual_status}")
            print(f"     ORCID: {actual_orcid} | Scholar: {actual_scholar}")
        else:
            print(f"  ❌ FAILED:")
            print(f"     Expected ORCID: {exp_orcid}, got: {actual_orcid} (Match: {orcid_ok})")
            print(f"     Expected Scholar: {exp_scholar}, got: {actual_scholar} (Match: {scholar_ok})")
            print(f"     Expected Status: VERIFIED (GROUND TRUTH MATCH), got: {actual_status}")

        time.sleep(1)

    print("\n" + "=" * 80)
    print(f"BENCHMARK COMPLETE: {passed}/{total} Passed ({passed/total*100:.1f}%)")
    print("=" * 80)

    with open("ground_truth_test_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    run_tests()
