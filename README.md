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
- **Explicit Diagnostics & Error Visibility:**
  - Transparent distinction between true absence of a profile and API key / network errors.
  - Dedicated diagnostic messages for missing keys, invalid credentials (HTTP 401/403), and quota exhaustion (HTTP 429).

---

## 🛠️ Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/marchdanya09/kse-faculty-matcher.git
   cd kse-faculty-matcher
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
   Set your `SERPAPI_API_KEY` (gives 250 free requests per month, enough for ~200+ faculty members with early exit).  
   *Note:* You can also pass the API key directly via CLI using `--api-key <key>`.

---

## 📖 CLI Usage

The pipeline supports direct command-line execution with fuzzy matching across **Ukrainian**, **English**, and **Russian** names:

### 1. Single Faculty Lookup:
```bash
# In Ukrainian:
python3 faculty_matcher.py "Тимофій Брік"

# In English:
python3 faculty_matcher.py "Sergiy Kozerenko"

# In Russian:
python3 faculty_matcher.py "Сергей Козеренко"
```

### 2. Pass SerpAPI Key Directly via CLI:
```bash
python3 faculty_matcher.py "Sergiy Kozerenko" --api-key YOUR_SERPAPI_KEY
```

### 3. Output Pure JSON to stdout (Scripting & Piping):
```bash
python3 faculty_matcher.py "Тимофій Брік" --json
```

### 4. Multiple Names & Save to File:
```bash
python3 faculty_matcher.py "Maksym Obrizan" "Павло Прокопович" -o results.json
```

### 5. Process Batch from File (One name per line or JSON array):
```bash
python3 faculty_matcher.py -f faculty_list.txt -o results.json
```

### 6. Silent Mode (Suppress Progress Logs):
```bash
python3 faculty_matcher.py -f faculty_list.txt -o results.json --quiet
```

### 7. Run Verification Benchmark Suite:
```bash
# Standard 9-faculty benchmark:
python3 faculty_matcher.py --benchmark

# Extended 15-faculty batch benchmark:
python3 test_new_faculty.py
```

---

## ⚙️ CLI Reference Table

| Argument / Flag | Description |
| :--- | :--- |
| `names ...` | Positional faculty name(s) (supports UKR, ENG, RUS). |
| `-n`, `--name NAME` | Faculty member name (can be repeated for multiple names). |
| `-f`, `--file PATH` | Path to text file (one name per line) or JSON array of names. |
| `-o`, `--output PATH` | Path to write output JSON file. |
| `--api-key KEY` | SerpAPI key for Google Scholar lookup (overrides `.env` / environment). |
| `--json` | Output pure JSON to stdout (suppresses progress logs for scripting/piping). |
| `-q`, `--quiet` | Suppress progress and summary messages to stderr/stdout. |
| `--benchmark`, `--demo` | Run the standard benchmark on the 9 reference faculty members. |
| `-h`, `--help` | Show command-line help message and exit. |

---

## 🛡️ Error Diagnostics & Status Codes

The matcher provides transparent status reporting to eliminate ambiguity between missing profiles and API configuration issues:

| Status Code | Meaning |
| :--- | :--- |
| `VERIFIED (AUTO)` | High-confidence match (ORCID and/or Scholar confirmed with KSE email `@kse.org.ua` or institutional snippet). |
| `PARTIAL MATCH (NEEDS REVIEW)` | Valid ORCID found with KSE affiliation, but Google Scholar profile is unregistered or not indexed. |
| `PARTIAL MATCH (SCHOLAR API ERROR)` | Valid ORCID found, but Scholar resolution failed due to an API key or quota issue. |
| `NEEDS REVIEW (HOMONYM RISK / UNVERIFIED AFFILIATION)` | Profile found with matching name, but without confirmed KSE affiliation (blocks false positives). |
| `MISSING / NOT FOUND` | No matching profiles found across any database (verified absent). |
| `ERROR (SCHOLAR API KEY ERROR)` | Scholar lookup could not be performed due to missing or invalid API credentials. |

### `[SCHOLAR]` Diagnostic Messages:
- `[SCHOLAR]: ERROR — API key not configured (set SERPAPI_API_KEY in .env or pass --api-key)`: Key is completely missing.
- `[SCHOLAR]: ERROR — SerpAPI access denied (HTTP 401: Invalid API key)`: Provided API key is incorrect or expired.
- `[SCHOLAR]: ERROR — SerpAPI search quota exceeded (HTTP 429: Account out of searches)`: Monthly search limit exhausted.
- `[SCHOLAR]: No registered profile found`: API call succeeded (HTTP 200) and author legitimately has no public profile.

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
