# KSE Faculty Matcher — Planned Pipeline Upgrade Architecture
> **Internal Project Context & Specification**  
> Location: `PIPELINE_UPGRADE_PLAN.md`  
> Created: October 2026  
> Status: Planning / Alignment Phase (Do NOT implement code until user confirms)

---

## 🎯 1. Conceptual Shift: Anchor-First Inverted Pipeline

### The Core Problem with Current Architecture
Currently, the pipeline follows a **Name-First Forward Search**:
1. It takes the teacher's Ukrainian name (e.g. `Власенко Марія Олександрівна` or `Чаїнська Марія Олександрівна`).
2. Generates CMU 2010 transliterations (`Mariia Vlasenko`).
3. Queries OpenAlex author search and ORCID API by name.
4. Performs post-hoc verification against works.

**Why this failed in practice:**
* **Name Entropy vs. Title/DOI Entropy:**
  * Ukrainian faculty members frequently publish under alternative names or international pen-names that do not match CMU 2010 (e.g., `Masha Vlasenko`, `María Chayinska`, `Ganna Vakhitova`).
  * An author name has high entropy and dozens of homonyms across universities (e.g. linguists at KNU).
  * In contrast, a **DOI** or a **scientific publication title** has near-zero entropy: it belongs to exactly **one paper worldwide**.
* **Wasted Ground Truth in Faculty Database:**
  * The KSE `faculty-data` record already contains rich ground-truth anchors:
    - `indexed_publications` (frequently contains raw DOIs: `10.1093/...`, `10.1016/...`)
    - `ukrainian_fach_publications` (official Ukrainian certified journal articles)
    - `textbooks_and_monographs` (monographs and books)
    - `scientometrics.google_scholar` (Google Scholar ID, e.g. `tCspiMoAAAAJ`)
    - `scientometrics.orcid` (ORCID iD)
    - `professional_development` & `dissertation_councils` (prior/parallel institutions: IM PAN, University of Messina)
    - `international_projects_and_expertise` (known international co-authors: Frits Beukers, Patrice Rusconi)

### The New Paradigm: Anchor-First Inverted Hierarchy
Instead of searching by name, we search by our **most reliable, hardest-to-confuse anchor**:

```
Priority 1: DOIs / Publication Titles (OpenAlex Works / Crossref)
       ↓ (If not found or no works)
Priority 2: Google Scholar Profile (Wikidata reverse lookup -> Serper 1-shot)
       ↓ (If no Scholar)
Priority 3: ORCID iD (OpenAlex /authors/orcid -> Wikidata -> 1-shot Serper)
       ↓ (If ZERO anchors exist)
Priority 4: Fallback to Name Search (CMU 2010 + Early Exit)
```

---

## 📋 2. Itemized Planned Pipeline Changes

### Item 1: Citation Parsing & DOI Extraction
* **File:** `faculty_bridge.py` and `faculty_matcher.py`
* **Function:** `parse_publication_anchor(raw_citation: str) -> Dict`
* **Logic:**
  1. Extract DOI regex `(?:doi\.org/|doi:\s*)(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)`.
  2. If DOI exists, return `{'doi': doi, 'title': clean_title}`.
  3. If no DOI, parse clean title (handling APA `Author (Year). Title. Journal`, quoted titles `«...»`, or comma-separated titles).
  4. Sanitize titles for API queries (strip commas, colons, semicolons to prevent OpenAlex HTTP 400).
* **Sources to Ingest:**
  - `indexed_publications`
  - `ukrainian_fach_publications`
  - `textbooks_and_monographs`

### Item 2: OpenAlex Works-First Anchor Engine (Free, 0 Serper Quota)
* **File:** `faculty_matcher.py`
* **Function:** `resolve_author_from_openalex_works(anchors, author_name) -> Optional[Dict]`
* **Logic:**
  1. If DOI exists: Query `https://api.openalex.org/works/https://doi.org/{doi}`.
  2. If Title only: Query `https://api.openalex.org/works?filter=title.search:{clean_title}` with `mailto:grant@kse.org.ua`.
  3. Inspect `authorships` array:
     - Match author by surname transliteration variants (`Vlasenko`, `Власенко`).
     - Match initial / first token.
  4. Extract:
     - `canonical_name` (e.g. `"Masha Vlasenko"`)
     - `openalex_author_id` (e.g. `"A5064040555"`)
     - `orcid_id` (e.g. `"0000-0001-7938-9992"`)
     - `institutions`, `citations`, `h_index`, `sample_works`
  5. Fallback to Crossref API (`https://api.crossref.org/works/{doi}`) if OpenAlex is temporarily rate-limited.

### Item 3: Bidirectional Wikidata SPARQL Resolver (Free, 0 Serper Quota)
* **File:** `faculty_matcher.py`
* **Functions:**
  - `get_scholar_from_wikidata(orcid_id: str) -> Optional[str]` (P496 $\rightarrow$ P1960)
  - `get_orcid_from_wikidata(scholar_id: str) -> Optional[str]` (P1960 $\rightarrow$ P496)
* **Impact:**
  - If Wikidata already links ORCID $\leftrightarrow$ Scholar, Scholar ID is resolved with **0 Serper API requests**.

### Item 4: Strictly 1-Shot Serper Co-Citation Search
* **File:** `faculty_matcher.py`
* **Function:** `search_scholar_by_cocitation(canonical_name: str, work_title: str) -> Optional[Dict]`
* **Logic:**
  - Query: `site:scholar.google.com/citations "{canonical_name}" {work_title[:45]}`
  - Immediately extracts Scholar ID from the author citations link.
  - Consumes **strictly 1 Serper query per faculty member** (or 0 if already in Wikidata).

### Item 5: Institutional Affiliations Whitelist (Removing the Affiliation Blindspot)
* **File:** `faculty_bridge.py` & `faculty_matcher.py`
* **Logic:**
  - Extract known academic institutions from teacher dossier:
    - `professional_development` (e.g. *Institute of Mathematics of the Polish Academy of Sciences*, *University of Messina*)
    - `dissertation_councils`
  - Pass these as `whitelist_institutions` to `process_faculty_member`.
  - When evaluating Scholar / ORCID profiles, if the affiliation matches one of these dossier institutions, treat it as **confirmed institutional match** (do NOT penalize as unverified).

### Item 6: Co-Author Validation Booster
* **File:** `faculty_bridge.py` & `faculty_matcher.py`
* **Logic:**
  - Extract international collaborator names from `international_projects_and_expertise` (e.g. *Frits Beukers*, *Patrice Rusconi*, *Anca Minescu*).
  - If a candidate paper contains one of these known co-authors, identity is confirmed with 100% confidence.

---

## 🚫 3. Items Explicitly Excluded (Based on User Guidance)
* **NO Discipline Filtering:**
  - Do NOT filter or reject candidates based on `academic_degree` or `faculty_id` (e.g., mathematician publishing on AI/neural networks, economist publishing on health). Modern research is interdisciplinary.
* **NO Syllabi / URL Scraping from Teaching Materials:**
  - Exclude URLs from `teaching_materials` and `foreign_language_teaching` (too noisy, unpredictable, and volatile).

---

## 📊 4. API Quota Consumption Target

| Metric | Previous Architecture | Inverted Pipeline Target |
| :--- | :--- | :--- |
| **OpenAlex & Crossref** | 100% Free | 100% Free |
| **ORCID Public API** | 100% Free | 100% Free |
| **Wikidata SPARQL** | 100% Free | 100% Free |
| **Serper.dev Usage** | 4–6 queries / person | **$\le 1$ query / person** |
| **Capacity with 2,500 queries** | ~400 faculty | **2,500+ faculty** |
