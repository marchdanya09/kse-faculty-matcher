# KSE Faculty Academic Profile Matcher — Instructions & Project Context

> **Automatic Context for Antigravity Agents**  
> This file is loaded automatically by Antigravity in every new chat session within this workspace.

---

## 🎯 1. Project Overview & Mission
This project automates the retrieval, disambiguation, and validation of academic profiles (**Google Scholar** and **ORCID iD**) for Kyiv School of Economics (**KSE**) faculty and researchers.

- **Workspace Path:** `/Users/apple/Documents/KSE/Grant`
- **GitHub Repository:** Private repo at `https://github.com/marchdanya09/kse-faculty-matcher`

---

## 🏗️ 2. Key Architecture & File Structure

| File | Purpose |
| :--- | :--- |
| `faculty_matcher.py` | **Core Production Pipeline**: Transliteration, OpenAlex, ORCID Public API, Wikidata SPARQL, SerpAPI Scholar resolver, anti-homonym logic. |
| `test_new_faculty.py` | **Batch Benchmark Runner**: Runs batch evaluations and logs detailed metrics. |
| `faculty_results.json` | First benchmark dataset (9 faculty members, 100% verified/handled). |
| `faculty_results_batch2.json` | Second benchmark dataset (15 faculty members, 100% verified/handled). |
| `.env.example` / `.gitignore` | Security configuration (Zero hardcoded API keys permitted!). |
| `README.md` | Public repository documentation. |

---

## ⚙️ 3. Critical Architectural Rules & Design Decisions

### A. Strict Anti-Homonym Protection
- **`VERIFIED (AUTO)`** requires **confirmed KSE affiliation** (or partner institutions like NaUKMA, NASU, KNU) in at least one primary source:
  - Email containing `@kse.org.ua`, OR
  - Affiliation snippet containing `KSE` / `Kyiv School of Economics`, OR
  - Verified cross-link in Wikidata (`P496` $\leftrightarrow$ `P1960`).
- If an author name matches but has NO institutional link to KSE (e.g. a different researcher at KPI or Poltava), mark as **`NEEDS REVIEW (HOMONYM RISK / UNVERIFIED AFFILIATION)`**, NEVER auto-verify!

### B. Ukrainian Transliteration & Name Parsing
- Follows the official **CMU 2010** transliteration standard.
- **Patronymic Safety:** Ukrainian patronymics (*по батькові* ending in `-ович`, `-івна`, etc.) must be stripped **ONLY when $\ge 3$ tokens exist**. Never strip 2-token names (protects Slavic surnames like *Прокопович Павло*).
- **Multi-Alias Scholar Splitting:** Ukrainian authors often concatenate several aliases in their Scholar title (e.g. `"Ігор Сердюк, Igor Serdiuk, Ihor Serdiuk"`). Always split on `[,/;|]` before running similarity checks.
- Normalizes unicode apostrophes (`’`, `ʼ`, `` ` `` $\rightarrow$ `'`).

### C. Quota Preservation & Early Exit
- **SerpAPI:** Free tier allows 250 requests/month.
- **Early Exit:** Once a confirmed KSE profile with match score $\ge 90\%$ is found, immediately terminate alias iteration. Consumes **strictly 1 credit per faculty member**.
- **No Hardcoded Keys:** Secrets must strictly load from environment variables (`SERPAPI_API_KEY`).

---

## 📊 4. Current Verification Ground Truth (24 Faculty Handled)

1. **Auto-Verified (15):** Viacheslav Priamitsyn, Sergiy Kozerenko, Kateryna Antoshyna, Mariia Kriuchok, Oleksandra Konopatska, Tymofiy Mylovanov, Pavlo Prokopovych, Ganna Vakhitova, Tymofii Brik, Maksym Obrizan, Volodymyr Kulyk, Ivan Gomza, Igor Serdiuk, Yurii Chopiuk.
2. **Partial Matches (ORCID verified, Scholar unregistered) (6):** Volodymyr Viedienieiev, Olena Halytska, Volodymyr Skochko, Tetiana Proshchenko, Veronika Yurchuk.
3. **Homonym Filters (3):** Natalia Shapoval (policy researcher without personal Scholar, KPI homonym rejected), Roman Mishchenko (Poltava homonym rejected), Sergiy Yakovlev (KPI homonym rejected).
4. **Unregistered (1):** Olena Besedina (no public profiles found).

---

## 🚀 5. Next Steps / Future Work
- Tackle edge cases where faculty members lack individual Scholar profiles or have ambiguous affiliations.
- Implement co-authorship graph matching or publication title cross-referencing for difficult cases.
- Integrate automated KSE staff directory parsing.
