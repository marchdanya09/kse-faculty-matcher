# KSE Faculty Academic Profile Matcher

Automated, cost-effective pipeline for discovering, disambiguating, and validating academic profiles (**Google Scholar** and **ORCID iD**) for Kyiv School of Economics (KSE) faculty and researchers.

---

## 🚀 Key Features

- **Multi-Tier Resolution Architecture:**
  - **Tier 1 (100% Free, Zero Ban Risk):** OpenAlex Polite Pool API + Direct ORCID Public API (`v3.0`) + Wikidata SPARQL Bridge (`P496` $\leftrightarrow$ `P1960`).
  - **Tier 2:** Google Scholar Profile Resolution via SerpAPI with intelligent **Early Exit** optimization (only 1 request per author, 250 free monthly searches).
  - **Tier 3:** Web search fallback.
- **Robust Ukrainian Name Handling:**
  - Official CMU 2010 Ukrainian transliteration standard.
  - Safe handling of patronymics (*по батькові*) — preserves Slavic surnames like *Прокопович*.
  - Unicode apostrophe normalization (`’`, `ʼ`, `` ` `` $\rightarrow$ `'`).
  - Common Latin alias generation (`iy` / `ii` / `y`, `H` / `G`).
- **Anti-Homonym & Disambiguation Engine:**
  - Multi-alias splitting: handles authors who list several name forms in their profile title (e.g. `"Ігор Сердюк, Igor Serdiuk, Ihor Serdiuk"`).
  - Strict institutional affiliation verification: requires verified KSE affiliation (or partner institutions like NaUKMA / NASU / KNU) to achieve `VERIFIED (AUTO)`.
  - Blocks homonyms from unrelated universities from being falsely matched.

---

## 🛠️ Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd <repo-name>
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables (Optional):**
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Set your `SERPAPI_API_KEY` (gives 250 free requests per month, enough for ~200+ faculty members with early-exit).

---

## 📖 CLI Usage

The pipeline supports direct command-line execution with fuzzy matching across **Ukrainian**, **English**, and **Russian** names:

### 1. Single Faculty Lookup:
```bash
# In Ukrainian:
python faculty_matcher.py "Тимофій Брік"

# In English:
python faculty_matcher.py "Sergiy Kozerenko"

# In Russian:
python faculty_matcher.py "Сергей Козеренко"
```

### 2. Output Pure JSON to stdout (Scripting & Piping):
```bash
python faculty_matcher.py "Тимофій Брік" --json
```

### 3. Multiple Names & Save to File:
```bash
python faculty_matcher.py "Maksym Obrizan" "Павло Прокопович" -o results.json
```

### 4. Process Batch from File (One name per line or JSON array):
```bash
python faculty_matcher.py --file faculty_list.txt -o results.json
```

### 5. Run Default Benchmark Suite:
```bash
python faculty_matcher.py --benchmark
# Or run the batch 2 benchmark:
python test_new_faculty.py
```

---

## 📊 Verification Benchmark

The pipeline was evaluated across 24 KSE faculty members and researchers across Economics, Sociology, History, Math, and Computer Science:

- **15 profiles `VERIFIED (AUTO)`** with 100% precision (confirmed KSE email `@kse.org.ua`, KSE affiliations, and citations).
- **6 profiles `PARTIAL MATCH (NEEDS REVIEW)`** accurately identifying registered ORCID with unindexed/absent Scholar profiles.
- **3 profiles `NEEDS REVIEW (HOMONYM RISK)`** preventing false positive matching against unrelated researchers from other institutions.
- **0 false positives.**

---

## 📄 License
MIT License
