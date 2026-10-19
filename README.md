# KSE Faculty Academic Profile Matcher & Database Sync Bridge

Automated, cost-effective pipeline for discovering, disambiguating, and validating academic profiles (**Google Scholar** and **ORCID iD**) for Kyiv School of Economics (KSE) faculty and researchers, with a safe, non-destructive synchronization bridge to the KSE **Faculty Data** platform.

---

## 🏗️ Architecture & End-to-End Pipeline

The integration between **Faculty Data** and **kse-faculty-matcher** follows a strict, safe, 3-stage pipeline:

```
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: EXPORT & SANITIZATION (sanitize_faculty_data.py)              │
│ • Downloads faculty profiles via Faculty Data Admin REST API           │
│ • Strictly scrubs PII (passports, tax IDs, diploma numbers)            │
│ • Preserves publications, scientometrics, DOIs, and profile metadata   │
│ └── Output: all_teachers_sanitized.json                                │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: PROFILE MATCHING & DISCOVERY BRIDGE (faculty_bridge.py)       │
│ • Extracts known publications & ground-truth anchors                   │
│ • Priority 1: OpenAlex Works API (via DOIs / Article Titles)           │
│ • Priority 2: Wikidata SPARQL Bridge (Free cross-links)                │
│ • Priority 3: Google Scholar Discovery via Serper.dev (Early Exit)     │
│ • Incremental Watermark & Content Hashing (.matcher_state.json)        │
│ └── Output: enriched_all_teachers.json                                 │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: SAFE DATABASE SYNCHRONIZATION (faculty_db_sync.py)            │
│ • Safe by default: DRY-RUN with visual Before vs Proposed diff table   │
│ • Intelligent Preserving Merger (preserves Scopus, WoS, notes)         │
│ • Optimistic Concurrency Control (OCC) handling (HTTP 409 retry)       │
│ • Pre-flight automatic snapshot backup (sync_backup_<timestamp>.json)  │
│ • Quality Gating: strictly writes ONLY confirmed VERIFIED profiles     │
│ └── Target: KSE Faculty Data Database via Admin PATCH API              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Step-by-Step Workflow & Bridge Commands

### Крок 1. Спочатку вивантажуємо та знеособлюємо дані з Faculty Data
> [!IMPORTANT]
> **Обов'язковий перший крок:** Перед запуском пошукового моста необхідно вивантажити свіжі профілі викладачів з платформи Faculty Data через утиліту знеособлення `sanitize_faculty_data.py`. Це повністю усуває конфіденційні персональні дані (паспорти, ІПН, дипломи), зберігаючи наукові публікації, статті та наукометрію.

```bash
# Вивантажити всіх викладачів з усіх факультетів у знеособлений файл:
python3 sanitize_faculty_data.py \
  --api-key "$FACULTY_DATA_API_KEY" \
  --faculty all \
  -o all_teachers_sanitized.json
```
*(Скрипт автоматично підключається до бекенду `https://faculty-data-two.vercel.app/api/admin/v1`, обходить усі факультети, видаляє PII та записує чистий файл).*

---

### Крок 2. Запуск інвертованого пошукового моста (`faculty_bridge.py`)
Після того, як дані вивантажено, запускаємо міст резолюції. Він проганяє викладачів через базу публікацій, знаходить відсутні ORCID та Google Scholar і зберігає всі результати в єдиний структурований файл:

```bash
# Повний прогін по всіх викладачах:
python3 faculty_bridge.py \
  --file all_teachers_sanitized.json \
  -o enriched_all_teachers.json

# Тестовий прогін на вибірці з 5 викладачів:
python3 faculty_bridge.py \
  --file all_teachers_sanitized.json \
  -l 5 \
  -o enriched_sample.json
```

#### Режими інкрементальної синхронізації:
- `--mode incremental` (за замовчуванням): якщо викладач уже верифікований і його публікації/ПІБ не змінювалися, він пропускається миттєво (`0.001` с, 0 зовнішніх запитів). Повторно перевіряються лише нові або змінені викладачі.
- `--mode new-only`: опрацьовує виключно викладачів із повністю порожніми полями наукометрії.
- `--mode force-all`: примусовий повний перерахунок усіх 190+ викладачів з оновленням кешу.

---

### Крок 3. Безпечна синхронізація з базою даних (`faculty_db_sync.py`)

#### 3.1. Безпечний попередній перегляд (Safe Dry-Run — Zero Writes):
Перед внесенням будь-яких змін перегляньте детальний Before/After diff:
```bash
python3 faculty_db_sync.py -i enriched_all_teachers.json
```
Ви побачите форматований звіт: які клітинки зараз у базі, які нові посилання будуть додані, та які викладачі пропускаються. **Жодного байту в базу не відправляється.**

#### 3.2. Інтерактивний запис у БД (з підтвердженням [y/N] для кожного викладача):
Найбезпечніший спосіб для поступового наповнення:
```bash
python3 faculty_db_sync.py \
  -i enriched_all_teachers.json \
  --api-key "$FACULTY_DATA_WRITE_KEY" \
  --execute \
  --prod-confirm \
  --interactive
```

#### 3.3. Пакетний запис усіх верифікованих профілів:
```bash
python3 faculty_db_sync.py \
  -i enriched_all_teachers.json \
  --api-key "$FACULTY_DATA_WRITE_KEY" \
  --execute \
  --prod-confirm
```

#### 3.4. Автоматичний бекап і миттєвий відкат (Rollback):
Перед кожним записом скрипт зберігає файл `sync_backup_<timestamp>.json`. Якщо знадобиться повернути попередній стан клітинок у базі, виконайте:
```bash
python3 faculty_db_sync.py \
  --restore sync_backup_20261019_030500.json \
  --api-key "$FACULTY_DATA_WRITE_KEY" \
  --execute \
  --prod-confirm
```

---

## 🛡️ Ключові гарантії збереження даних

1. **Intelligent Preserving Merger (Zero Data Loss):**
   Функція `merge_scientometrics_cells` зчитує всі наявні клітинки рядка. Вона **строго зберігає** Scopus, Web of Science, ResearcherID та адміністративні примітки, оновлюючи або дописуючи лише канонічні URL `https://orcid.org/...` та `https://scholar.google.com/citations?user=...`.
2. **Оптимістичне блокування (OCC) та обробка 409 Conflict:**
   Скрипт передає поточну версію рядка `field_versions["scientometrics"]`. Якщо викладач або адмін паралельно редагував профіль, сервер повертає `409 Conflict` — скрипт автоматично витягує свіжу версію, пере-зливає дані та безпечно повторює запит.
3. **Quality Gating:**
   До запису допускаються **виключно** викладачі зі статусом `VERIFIED (AUTO)` або `VERIFIED (GROUND TRUTH MATCH)` з оцінкою $\ge 90/100$. Омоніми та непідтверджені профілі блокуються.

---

## 📖 Автономний CLI Матчера (`faculty_matcher.py`)

Для швидкої точкової перевірки окремих дослідників підтримується автономний CLI (підтримує українську, англійську та транслітерацію):

```bash
# Пошук за ПІБ:
python3 faculty_matcher.py "Тимофій Брік"
python3 faculty_matcher.py "Sergiy Kozerenko"

# Детермінований пошук за назвою статті (-w / --work):
python3 faculty_matcher.py "Mykola Trehub" -w "Determining and determinable factors influencing the size of zone of land-use restriction"

# Прямий якорний пошук за ORCID або Scholar ID:
python3 faculty_matcher.py "Mykola Trehub" --orcid "0000-0002-2205-5622"
python3 faculty_matcher.py "Mykola Trehub" --scholar "QnhQqygAAAAJ"

# Вивід чистого JSON (для пайпів):
python3 faculty_matcher.py "Тимофій Брік" --json
```

---

## 📊 Верифікаційні бенчмарки

Всі модулі покриті автоматизованими тестами регресії:

```bash
# 1. Бенчмарк якорної верифікації за публікаціями (100% pass rate):
python3 test_ground_truth.py

# 2. Бенчмарк 15 нових викладачів KSE (100% pass rate):
python3 test_new_faculty.py

# 3. Базовий бенчмарк 9 викладачів:
python3 faculty_matcher.py --benchmark
```

---

## 📦 Опис файлів проекту

| Файл | Призначення |
| :--- | :--- |
| `sanitize_faculty_data.py` | **Крок 1**: Безпечний експортер і PII-санітайзер даних з Faculty Data API. |
| `faculty_bridge.py` | **Крок 2**: Пошуковий міст (інвертований пайплайн, хешування стану, збереження enriched JSON). |
| `faculty_db_sync.py` | **Крок 3**: Міст безпечного запису в базу даних (Dry-Run, Diff, Preserving Merger, OCC, Rollback). |
| `faculty_matcher.py` | Ядро пошуку: транслітерація CMU 2010, OpenAlex, ORCID API, Wikidata SPARQL, Serper Scholar. |
| `test_ground_truth.py` | Автоматичний тест-раннер якорного пошуку за статтями. |
| `test_new_faculty.py` | Пакетний тест-раннер викладачів KSE. |

---

## 📄 License
MIT License
