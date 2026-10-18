# KSE Faculty Matcher — Hardened Anchor-First Pipeline Architecture
> **Comprehensive Specification, Adversarial Audit ("Roast"), and Implementation Plan**  
> Location: `PIPELINE_UPGRADE_PLAN.md`  
> Status: Fully Audited & Hardened — Awaiting User Approval to Implement  
> Strictly Enforced: Zero changes to `faculty-data/` repository.

---

## 🎯 1. Conceptual Shift: Anchor-First Inverted Pipeline

### The Core Problem with Name-First Search
The previous architecture followed a **Name-First Forward Search**:
1. Took a faculty member's Ukrainian name (e.g. `Власенко Марія Олександрівна` or `Чаїнська Марія Олександрівна`).
2. Generated transliterations (`Mariia Vlasenko`, `Serhii Kozerenko`).
3. Searched OpenAlex and ORCID by name via fuzzy author searches.
4. Compared search results against works as a secondary check.

**Why this failed in production:**
* **Entropy Gap:** Ukrainian faculty publish under international pen-names (e.g. `Masha Vlasenko`, `María Chayinska`, `Ganna Vakhitova`, `Nikolay Tregub`). An author's name has high entropy and dozens of homonyms across universities.
* In contrast, a **DOI** (`10.1093/imrn/rnaa119`) or a **scientific title** has near-zero entropy: it belongs to exactly **one paper worldwide**.
* Searching by paper instantly yielded Masha Vlasenko's canonical name, OpenAlex author ID (`A5064040555`), and real ORCID (`0000-0001-7938-9992`) with **0 Serper API queries** and 0 homonym risk.

---

## ⚔️ 2. Adversarial Logic Audit ("Roast") & Empirical Discoveries

To prevent regressions, the proposed logic was stress-tested by independent subagents against real KSE faculty records (`teacher_raw.json`, `mock_faculty_data.json`, `teachers_sanitized_batch.json`) and live APIs. Key vulnerabilities discovered and their concrete defenses:

### 1. Co-Author Same-Surname Collision (Empirical Proof: Mykola & Yuliia Trehub)
* **The Vulnerability:** On paper `10.33271/mining14.01.107` (*Determining and determinable factors...*), **both Mykola Trehub AND Yuliia Trehub are co-authors** with distinct ORCIDs. Naive surname matching randomly assigns Yuliia's ORCID (`0000-0002-8706-0377`) to Mykola Trehub.
* **Hardened Defense:** In `authorships`, enforce **two-token verification**: matching surname AND verifying given name / initial. If two co-authors share the surname and target initial cannot disambiguate them, flag as ambiguous and never auto-attribute.

### 2. The 1-Shot Serper Co-Citation Failure on Recent Papers
* **The Vulnerability:** Querying `site:scholar.google.com/citations "{name}" {title}` failed 100% of the time on recent papers (e.g. *Maria Chayinska* and *Sergiy Kozerenko* returned 0 results). Google Scholar profile index snippets **only index the top 1–2 most-cited papers**.
* **Hardened Defense:**
  - Query Serper with canonical name: `site:scholar.google.com/citations "{canonical_name}"` (without title).
  - Filter out bot/junk links where URL contains `view_op=list_works` or title is literally `"Title"` with `"No information is available for this page"`.
  - The second organic result reliably contains the author's real profile, affiliation, and verified email (`kse.org.ua`, `unime.it`).
  - Terminate immediately on the first high-confidence KSE/confirmed profile (Early Exit: strictly 1 query spent).

### 3. OpenAlex Rate Limits & Crossref Fallback Limits
* **The Vulnerability:** Unauthenticated OpenAlex requests are capped at $0.10/day per IP, triggering `HTTP 429: Too Many Requests` (with 2.5-hour retry lockout). Crossref fallback does not return ORCIDs in 67% of cases and has no citation metrics.
* **Hardened Defense:**
  - Support `OPENALEX_API_KEY` from `.env`.
  - Use `mailto:grant@kse.org.ua` polite pool headers.
  - Implement graceful exponential backoff: if `Retry-After > 60s`, do not hang; log alert and route directly to ORCID API and Serper.

### 4. Ukrainian Fach Journals & Comma-Separated Citation Splitting
* **The Vulnerability:**
  - Real KSE data exports (`teacher_raw.json`) store 22 APA citations in a single string separated by commas, with **zero newlines**. Naive newline splitting collapsed 22 papers into one single 6,896-character string.
  - Ukrainian monographs (Category B) often lack DOIs and Crossref deposits.
* **Hardened Defense:**
  - Build a robust `CitationParser` that splits on APA year boundaries (`\b(19\d\d|20\d\d)\b`), semicolon delimiters, or DOI prefixes.
  - Extract DOIs first (`10.\d{4,9}/...`). If no DOI, use clean title.
  - For unindexed Ukrainian works, match directly against Scholar profile articles or ORCID public works rather than querying OpenAlex.

### 5. Institutional Whitelist False-Positive Traps
* **The Vulnerability:** Naive extraction from `professional_development` pulls in non-academic entries (`"SnowPro"`, `"SAFe 5.0 Agilist"`) or mass institutions (*Taras Shevchenko National University of Kyiv*, *University of Warsaw*), which would cause any homonym from KNU or Warsaw to be auto-verified.
* **Hardened Defense:**
  - Blacklist training keywords (`сертифікат`, `школа`, `курс`, `конференція`, `SAFe`, `SnowPro`).
  - Whitelist only confirmed academic appointments (`професор`, `доцент`, `дослідник`, `fellow`).
  - Whitelisted foreign institutions **never auto-verify an author on their own**. They may only be used to waive unverified penalties when a publication or ORCID is already matched.

### 6. Wikidata Coverage Reality (<1%)
* **The Vulnerability:** Live SPARQL queries show only **580 Ukrainian researchers** have both ORCID and Google Scholar in Wikidata across the entire country.
* **Hardened Defense:** Wikidata is treated as an opportunistic, free Tier 0 shortcut (0 Serper credits), but never a blocking dependency.

---

## 🧹 3. Clean Code Audit & Anti-Bloat Architecture

To eliminate spaghetti logic, avoid code bloat, and fix hidden bugs, the 305-line procedural `process_faculty_member` will be decomposed into 5 testable, single-responsibility components:

```
[Faculty Record / Input Name]
             │
             ▼
┌────────────────────────────────────────┐
│ 1. DossierAnchors / CitationParser     │  Extract DOIs, clean titles, existing IDs,
│    (faculty_bridge.py / matcher)       │  and academic whitelist institutions
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│ 2. WorksResolver (Priority 1)          │  OpenAlex Works API / Crossref
│    (faculty_matcher.py)                │  Extracts canonical name, ORCID, metrics
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│ 3. ScholarResolver (Priority 2)        │  Direct ID -> Wikidata SPARQL (0 quota)
│    (faculty_matcher.py)                │  -> 1-Shot Serper (author-level, 1 quota)
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│ 4. OrcidResolver (Priority 3)          │  Direct ID -> Wikidata SPARQL
│    (faculty_matcher.py)                │  -> Public ORCID API Works search
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│ 5. AffiliationEvaluator &              │  Pure rule engine: evaluates KSE/partner
│    DecisionEngine (Pure Logic)         │  links, assigns status, computes confidence
└──────────────────┬─────────────────────┘
                   │
                   ▼
       [Structured MatchResult]
```

### Specific Bug Fixes Included:
1. **Title NoneType Crash:** Fix `str(item.get('title') or '')` across all regex title cleans.
2. **SerpAPI Author None Crash:** Fix `(p_json.get('author') or {}).get(...)` and `(data.get('profiles') or {}).get(...)`.
3. **Teacher Filter Transliteration:** Add `transliterate_ru` to `match_teacher_name` in `faculty_bridge.py` so Russian variants (`Сергей` $\leftrightarrow$ `Sergey`) match correctly.
4. **Patronymic Filter Fix:** Ensure `match_teacher_name` compares only against core name tokens (`c_core`), not full tokens (`c_tokens`).
5. **Bridge Scientometrics Version Bug:** Replace `anchors["field_versions"].get("scientometrics", 1)` with `(anchors["field_versions"].get("scientometrics") or 1)` to prevent `null` version crashes in PATCH payloads.
6. **Cache Poisoning Fix:** Ensure failed network requests do NOT poison the in-memory cache with empty results.

---

## 🚫 4. Items Explicitly Excluded (Per User Command)
* **NO Discipline Filtering:** No filtering or penalties based on `academic_degree` or `faculty_id` (preserves interdisciplinary research).
* **NO Syllabus Scraping:** Exclude syllabus URLs from `teaching_materials` (avoids volatility and noise).

---

## 📊 5. API Quota Consumption Target

| Service | Previous Consumption | Inverted Pipeline Target |
| :--- | :--- | :--- |
| **OpenAlex Works & Crossref** | 0% used | 100% Free (Polite Pool) |
| **Wikidata SPARQL** | Unused for Scholar $\rightarrow$ ORCID | 100% Free (0 Quota) |
| **ORCID Public API** | 100% Free | 100% Free |
| **Serper.dev Usage** | 4–6 queries / person | **$\le 1$ query / person** |
| **Total Faculty Capacity (2,500 Quota)** | ~400 faculty | **2,500+ faculty** |

---

## 🛠️ 6. Phased Implementation Roadmap

1. **Phase 1: Foundation Helpers (`faculty_matcher.py` & `faculty_bridge.py`)**
   - Implement `CitationParser` with DOI extraction and APA citation splitting.
   - Implement `normalize_phonetic_surname()` and two-token author matching.
   - Implement `get_orcid_from_wikidata(scholar_id)` bidirectional SPARQL.
   - Fix null-safety bugs and `match_teacher_name` in `faculty_bridge.py`.

2. **Phase 2: WorksResolver & ScholarResolver**
   - Implement `resolve_author_from_works()` in `faculty_matcher.py` (OpenAlex DOI + title search, canonical name extraction).
   - Harden `search_google_scholar_serper()`: author-level search with `view_op=list_works` filter and Early Exit.

3. **Phase 3: Pipeline Orchestration & DecisionEngine**
   - Refactor `process_faculty_member` to follow Priority 1 (Works) $\rightarrow$ Priority 2 (Scholar) $\rightarrow$ Priority 3 (ORCID) $\rightarrow$ Priority 4 (Name fallback).
   - Ensure backward compatibility: keep existing function signatures intact.

4. **Phase 4: Verification & Benchmarking**
   - Run `test_ground_truth.py` (verify 7/7 100% pass rate).
   - Run `test_new_faculty.py` (verify 15 faculty benchmark).
   - Run `faculty_bridge.py` on the 20 real faculty members in `teachers_sanitized_batch.json` and verify Serper quota spent is $\le 1$ per person.
