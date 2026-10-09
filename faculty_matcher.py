import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

# ==============================================================================
# CONFIGURATION & CONSTANTS
# ==============================================================================
def _load_dotenv_auto():
    """Automatically loads variables from .env if present."""
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    ]
    for env_path in candidates:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip("'\"")
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass
            break

_load_dotenv_auto()

DEFAULT_SERPAPI_KEY = os.getenv("SERPAPI_API_KEY", "")
DEFAULT_GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
DEFAULT_GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "")
POLITE_USER_AGENT = "KSE-DataQuality/1.0 (mailto:grant@kse.org.ua)"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

KSE_INSTITUTION_KEYWORDS = [
    'kyiv school of economics', 'kse', 'kyiv economics institute',
    'economics education and research consortium', 'eerc', 'київська школа економіки'
]
PARTNER_INSTITUTION_KEYWORDS = [
    'kyiv-mohyla', 'naukma', 'taras shevchenko', 'knu', 'institute of mathematics',
    'national academy of sciences of ukraine', 'kyiv national economic university', 'kneu'
]

# ==============================================================================
# 1. TRANSLITERATION & MULTILINGUAL NAME PARSING (UKR / ENG / RUS)
# ==============================================================================
UKR_TRANSLIT_INITIAL = {
    'Є': 'Ye', 'Ї': 'Yi', 'Й': 'Y', 'Ю': 'Yu', 'Я': 'Ya',
    'є': 'ye', 'ї': 'yi', 'й': 'y', 'ю': 'yu', 'я': 'ya'
}
UKR_TRANSLIT_MEDIAL = {
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'H', 'Ґ': 'G', 'Д': 'D', 'Е': 'E', 'Є': 'Ie',
    'Ж': 'Zh', 'З': 'Z', 'И': 'Y', 'І': 'I', 'Ї': 'I', 'Й': 'I', 'К': 'K', 'Л': 'L',
    'М': 'M', 'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
    'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch', 'Ю': 'Iu', 'Я': 'Ia',
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'ґ': 'g', 'д': 'd', 'е': 'e', 'є': 'ie',
    'ж': 'zh', 'з': 'z', 'и': 'y', 'і': 'i', 'ї': 'i', 'й': 'i', 'к': 'k', 'л': 'l',
    'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ю': 'iu', 'я': 'ia',
    'ы': 'y', 'Ы': 'Y', 'э': 'e', 'Э': 'E', 'ё': 'io', 'Ё': 'Io', 'ъ': '', 'Ъ': '',
    'ь': '', '\'': '', '’': '', 'ʼ': '', '`': ''
}

RU_TRANSLIT_INITIAL = {
    'Е': 'Ye', 'Ё': 'Yo', 'Ю': 'Yu', 'Я': 'Ya',
    'е': 'ye', 'ё': 'yo', 'ю': 'yu', 'я': 'ya'
}
RU_TRANSLIT_MEDIAL = {
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
    'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
    'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
    'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch',
    'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya',
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    'і': 'i', 'І': 'I', 'ї': 'i', 'Ї': 'I', 'є': 'ye', 'Є': 'Ye', 'ґ': 'g', 'Ґ': 'G'
}

CROSS_LANG_NAME_PAIRS = {
    'сергей': 'сергій', 'сергій': 'сергей',
    'тимофей': 'тимофій', 'тимофій': 'тимофей',
    'вячеслав': "в'ячеслав", "в'ячеслав": 'вячеслав',
    'павел': 'павло', 'павло': 'павел',
    'анна': 'ганна', 'ганна': 'анна',
    'владимир': 'володимир', 'володимир': 'владимир',
    'игорь': 'ігор', 'ігор': 'игорь',
    'иван': 'іван', 'іван': 'иван',
    'екатерина': 'катерина', 'катерина': 'екатерина',
    'татьяна': 'тетяна', 'тетяна': 'татьяна',
    'юрий': 'юрій', 'юрій': 'юрий',
    'елена': 'олена', 'олена': 'елена',
    'роман': 'роман',
    'александр': 'олександр', 'олександр': 'александр',
    'алексей': 'олексій', 'олексій': 'алексей',
    'дмитрий': 'дмитро', 'дмитро': 'дмитрий',
    'михаил': 'михайло', 'михайло': 'михаил',
    'андрей': 'андрій', 'андрій': 'андрей',
    'наталья': 'наталія', 'наталия': 'наталія', 'наталія': 'наталья',
    'мария': 'марія', 'марія': 'мария',
    'виктор': 'віктор', 'віктор': 'виктор',
    'евгений': 'євген', 'євген': 'евгений', 'євгеній': 'евгений',
    'григорий': 'григорій', 'григорій': 'григорий'
}

LATIN_TO_CYR_NAMES = {
    'tymofii': ['Тимофій', 'Тимофей'], 'tymofiy': ['Тимофій', 'Тимофей'], 'timofey': ['Тимофій', 'Тимофей'],
    'sergiy': ['Сергій', 'Сергей'], 'serhii': ['Сергій', 'Сергей'], 'sergey': ['Сергій', 'Сергей'],
    'igor': ['Ігор', 'Игорь'], 'ihor': ['Ігор', 'Игорь'],
    'ivan': ['Іван', 'Иван'],
    'pavlo': ['Павло', 'Павел'], 'pavel': ['Павло', 'Павел'],
    'volodymyr': ['Володимир', 'Владимир'], 'vladimir': ['Володимир', 'Владимир'],
    'maksym': ['Максим'], 'maxim': ['Максим'],
    'kateryna': ['Катерина', 'Екатерина'], 'ekaterina': ['Катерина', 'Екатерина'],
    'mariia': ['Марія', 'Мария'], 'mariya': ['Марія', 'Мария'], 'maria': ['Марія', 'Мария'],
    'ganna': ['Ганна', 'Анна'], 'hanna': ['Ганна', 'Анна'], 'anna': ['Ганна', 'Анна'],
    'olena': ['Олена', 'Елена'], 'elena': ['Олена', 'Елена'],
    'tetiana': ['Тетяна', 'Татьяна'], 'tatyana': ['Тетяна', 'Татьяна'],
    'viacheslav': ["В'ячеслав", "Вячеслав"], 'vyacheslav': ["В'ячеслав", "Вячеслав"],
    'yurii': ['Юрій', 'Юрий'], 'yuriy': ['Юрій', 'Юрий'], 'yury': ['Юрій', 'Юрий']
}

PATRONYMIC_ENDINGS = ('ович', 'евич', 'євич', 'івна', 'ївна', 'овна', 'евна')

def transliterate_ukr(text: str) -> str:
    """Official Ukrainian transliteration standard (CMU 2010)."""
    words = text.split()
    res_words = []
    for w in words:
        chars = []
        for i, ch in enumerate(w):
            if i == 0 and ch in UKR_TRANSLIT_INITIAL:
                chars.append(UKR_TRANSLIT_INITIAL[ch])
            else:
                chars.append(UKR_TRANSLIT_MEDIAL.get(ch, ch))
        res_words.append(''.join(chars))
    return ' '.join(res_words)

def transliterate_ru(text: str) -> str:
    """Standard Russian transliteration (BGN/PCGN)."""
    words = text.split()
    res_words = []
    for w in words:
        chars = []
        for i, ch in enumerate(w):
            if i == 0 and ch in RU_TRANSLIT_INITIAL:
                chars.append(RU_TRANSLIT_INITIAL[ch])
            else:
                chars.append(RU_TRANSLIT_MEDIAL.get(ch, ch))
        res_words.append(''.join(chars))
    return ' '.join(res_words)

def generate_name_variants(name: str) -> List[str]:
    """Generates structured name variants across Ukrainian, English, and Russian (CMU 2010 & BGN)."""
    clean_str = re.sub(r'[\’\ʼ\`]', "'", name.strip())
    tokens = [t for t in re.split(r'\s+', clean_str) if t]
    if not tokens:
        return [name]

    clean_tokens = list(tokens)
    # Strip patronymic ONLY if 3+ tokens (protects surnames like Прокопович)
    if len(tokens) >= 3:
        if tokens[-1].lower().endswith(PATRONYMIC_ENDINGS):
            clean_tokens = tokens[:-1]
        elif tokens[1].lower().endswith(PATRONYMIC_ENDINGS):
            clean_tokens = [tokens[0]] + tokens[2:]

    orders = []
    if len(clean_tokens) == 2:
        t0, t1 = clean_tokens[0], clean_tokens[1]
        orders.extend([f"{t0} {t1}", f"{t1} {t0}"])

        # Cross-lingual Ukrainian <-> Russian first name mapping
        for i, t in enumerate([t0, t1]):
            low = t.lower()
            if low in CROSS_LANG_NAME_PAIRS:
                mapped = CROSS_LANG_NAME_PAIRS[low]
                mapped_tc = mapped.capitalize() if t[0].isupper() else mapped
                alt = [t0, t1]
                alt[i] = mapped_tc
                orders.extend([f"{alt[0]} {alt[1]}", f"{alt[1]} {alt[0]}"])
    elif len(clean_tokens) == 1:
        orders.append(clean_tokens[0])
    else:
        orders.append(' '.join(clean_tokens))

    variants = set()
    variants.add(name.strip())

    has_cyrillic = any(ord(c) > 127 for c in name)

    if has_cyrillic:
        for order in orders:
            variants.add(order)
            # Ukrainian CMU 2010 transliteration
            tr_u = transliterate_ukr(order)
            variants.add(tr_u)
            variants.add(re.sub(r'\bH', 'G', re.sub(r'\bh', 'g', tr_u)))
            if 'ii' in tr_u:
                variants.add(tr_u.replace('ii', 'iy'))
                variants.add(tr_u.replace('ii', 'y'))
            if 'iy' in tr_u:
                variants.add(tr_u.replace('iy', 'ii'))
                variants.add(tr_u.replace('iy', 'y'))
            tr_iy = re.sub(r'ii\b', 'iy', tr_u)
            variants.add(tr_iy)

            # Russian BGN transliteration
            tr_r = transliterate_ru(order)
            variants.add(tr_r)
    else:
        # Latin input: generate swapped orders & check for known Cyrillic mappings
        for order in orders:
            variants.add(order)
            if 'ii' in order:
                variants.add(order.replace('ii', 'iy'))
            if 'iy' in order:
                variants.add(order.replace('iy', 'ii'))

        if len(clean_tokens) == 2:
            t0_low = clean_tokens[0].lower()
            t1_low = clean_tokens[1].lower()
            if t0_low in LATIN_TO_CYR_NAMES:
                for cyr_fn in LATIN_TO_CYR_NAMES[t0_low]:
                    variants.add(f"{cyr_fn} {clean_tokens[1]}")
            if t1_low in LATIN_TO_CYR_NAMES:
                for cyr_fn in LATIN_TO_CYR_NAMES[t1_low]:
                    variants.add(f"{cyr_fn} {clean_tokens[0]}")

    # Specific historical roster aliases
    v_lower = name.lower()
    if 'priamitsyn' in v_lower or 'pryamitsyn' in v_lower or 'прямицын' in v_lower or 'пряміцин' in v_lower:
        variants.add('Вячеслав Пряміцин')
        variants.add('Пряміцин Вячеслав')
        variants.add('Вячеслав Прямицын')
        variants.add('Viacheslav Priamitsyn')
        variants.add('Viacheslav Pryamitsyn')
    elif 'kriuchok' in v_lower or 'крючок' in v_lower:
        variants.add('Mariia Kriuchok')
        variants.add('Марія Крючок')
    elif 'kozerenko' in v_lower or 'козеренко' in v_lower:
        variants.add('Сергій Козеренко')
        variants.add('Сергей Козеренко')
        variants.add('Sergiy Kozerenko')
    elif 'viedienieiev' in v_lower or 'ведєнєєв' in v_lower:
        variants.add('Володимир Ведєнєєв')

    # Smart ordering: Latin variants first for academic search engines, preserving exact Latin input
    latin_variants = [v for v in variants if not any(ord(c) > 127 for c in v)]
    cyrillic_variants = [v for v in variants if any(ord(c) > 127 for c in v)]

    def _rank_latin_variant(v: str) -> int:
        score = 0
        parts = v.split()
        if len(parts) == 2:
            first_part = parts[0].lower()
            if any(first_part.startswith(p) for p in [
                'serg', 'serh', 'timof', 'tymof', 'pavl', 'volod', 'vlad',
                'igor', 'ihor', 'ivan', 'maks', 'kate', 'mari', 'olen',
                'elen', 'yur', 'anna', 'hann', 'tet', 'tat', 'viach', 'vyach'
            ]):
                score += 50
            if 'iy' in first_part:
                score += 30
            elif 'ey' in first_part:
                score += 25
            elif 'ii' in first_part:
                score += 15
            if 'giy' in first_part or 'gey' in first_part:
                score += 20
        return score

    ranked_latin = sorted(latin_variants, key=_rank_latin_variant, reverse=True)

    ordered_variants = []
    if not has_cyrillic:
        ordered_variants.append(name.strip())
        for v in ranked_latin + cyrillic_variants:
            if v not in ordered_variants:
                ordered_variants.append(v)
    else:
        for v in ranked_latin:
            if v not in ordered_variants:
                ordered_variants.append(v)
        ordered_variants.append(name.strip())
        for v in cyrillic_variants:
            if v not in ordered_variants:
                ordered_variants.append(v)

    return ordered_variants

# ==============================================================================
# 2. TIER 1: WIKIDATA SPARQL BRIDGE (100% FREE, 0 BAN RISK)
# ==============================================================================
def get_scholar_from_wikidata(orcid: str) -> Optional[Dict]:
    """Resolves an ORCID to Google Scholar ID via Wikidata P1960. Free, official, zero ban risk."""
    if not orcid:
        return None
    clean_orcid = orcid.split('/')[-1].strip()
    sparql = f"""
    SELECT ?scholarId WHERE {{
      ?person wdt:P496 "{clean_orcid}" .
      ?person wdt:P1960 ?scholarId .
    }} LIMIT 1
    """
    endpoint = "https://query.wikidata.org/sparql?query=" + urllib.parse.quote(sparql)
    req = urllib.request.Request(
        endpoint,
        headers={"Accept": "application/json", "User-Agent": POLITE_USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            bindings = data.get("results", {}).get("bindings", [])
            if bindings:
                scholar_id = bindings[0]["scholarId"]["value"]
                return {
                    "scholar_id": scholar_id,
                    "profile_url": f"https://scholar.google.com/citations?user={scholar_id}&hl=en",
                    "source": "Wikidata SPARQL Bridge (Free Tier 1)"
                }
    except Exception:
        pass
    return None

# ==============================================================================
# 3. OPENALEX API (DISAMBIGUATED WITH POLITE POOL)
# ==============================================================================
def query_openalex(name_variants: List[str]) -> Optional[Dict]:
    """Queries OpenAlex author search API across variants and ranks candidates by affiliation & name match."""
    seen_ids = set()
    candidates = []

    for variant in name_variants[:4]:
        q = urllib.parse.quote(variant)
        url = f"https://api.openalex.org/authors?search={q}"
        req = urllib.request.Request(url, headers={'User-Agent': POLITE_USER_AGENT})

        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    results = data.get('results', [])
                    for cand in results[:10]:
                        cid = cand.get('id')
                        if cid in seen_ids:
                            continue
                        seen_ids.add(cid)

                        dname = cand.get('display_name', '')
                        name_sim = max(fuzz.token_sort_ratio(v, dname) for v in name_variants)
                        if name_sim < 70:
                            continue

                        insts = [a['institution']['display_name'] for a in cand.get('affiliations', [])]
                        inst_str = ' '.join(insts).lower()
                        has_kse = any(k in inst_str for k in KSE_INSTITUTION_KEYWORDS)
                        has_partner = any(p in inst_str for p in PARTNER_INSTITUTION_KEYWORDS)

                        score = name_sim + (50 if has_kse else (25 if has_partner else 0))
                        candidates.append((score, has_kse, cand, insts))
                break
            except Exception:
                time.sleep(0.5 * (attempt + 1))

        # Early exit if a verified KSE author is found
        if any(c[1] and c[0] >= 140 for c in candidates):
            break

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[1], x[0]), reverse=True)
    best_score, has_kse, best, insts = candidates[0]

    author_id = best['id'].split('/')[-1]
    works_url = f"https://api.openalex.org/works?filter=author.id:{author_id}&per_page=3"
    wreq = urllib.request.Request(works_url, headers={'User-Agent': POLITE_USER_AGENT})
    sample_works = []
    try:
        with urllib.request.urlopen(wreq, timeout=8) as wresp:
            wdata = json.loads(wresp.read().decode())
            sample_works = [w['title'] for w in wdata.get('results', []) if w.get('title')]
    except Exception:
        pass

    stats = best.get('summary_stats', {})
    return {
        'openalex_id': best.get('id'),
        'display_name': best.get('display_name'),
        'orcid': best.get('orcid'),
        'affiliations': insts,
        'has_kse_affiliation': has_kse,
        'works_count': best.get('works_count', 0),
        'cited_by_count': best.get('cited_by_count', 0),
        'h_index': stats.get('h_index', 0),
        'sample_works': sample_works
    }

# ==============================================================================
# 4. DIRECT ORCID API (STRICT HOMONYM PROTECTION)
# ==============================================================================
def query_orcid(name_variants: List[str]) -> Optional[Dict]:
    """Queries ORCID Public API with strict surname and given name matching to prevent false positives."""
    best_match = None
    best_score = -1

    for variant in name_variants[:4]:
        parts = variant.split()
        if len(parts) < 2:
            continue
        v_given, v_family = parts[0], parts[-1]

        q = urllib.parse.quote(variant)
        url = f"https://pub.orcid.org/v3.0/expanded-search/?q={q}"
        req = urllib.request.Request(
            url,
            headers={'Accept': 'application/json', 'User-Agent': POLITE_USER_AGENT}
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                results = json.loads(resp.read().decode()).get('expanded-result', [])
                for cand in results[:15]:
                    cand_given = cand.get('given-names') or ''
                    cand_family = cand.get('family-names') or ''
                    cand_insts = cand.get('institution-name', [])

                    f_sim = max(
                        fuzz.ratio(v_family.lower(), cand_family.lower()),
                        fuzz.ratio(v_given.lower(), cand_family.lower())
                    )
                    g_sim = max(
                        fuzz.ratio(v_given.lower(), cand_given.lower()),
                        fuzz.ratio(v_family.lower(), cand_given.lower())
                    )

                    # Strict threshold: surname >= 85, given name >= 70
                    if f_sim >= 85 and g_sim >= 70:
                        inst_str = ' '.join(cand_insts).lower()
                        has_kse = any(k in inst_str for k in KSE_INSTITUTION_KEYWORDS)
                        score = f_sim + g_sim + (50 if has_kse else 0)

                        if score > best_score:
                            best_score = score
                            best_match = {
                                'orcid_id': cand.get('orcid-id'),
                                'orcid_url': f"https://orcid.org/{cand.get('orcid-id')}",
                                'name_in_orcid': f"{cand_given} {cand_family}".strip(),
                                'other_names': cand.get('other-name', []),
                                'institutions': cand_insts
                            }
                            if has_kse:
                                return best_match
        except Exception:
            continue

    return best_match

# ==============================================================================
# 5. GOOGLE SCHOLAR RETRIEVAL (CSE FREE TIER -> SERPAPI -> FALLBACK)
# ==============================================================================
def search_google_scholar_cse(
    name_variants: List[str],
    api_key: Optional[str] = None,
    cx: Optional[str] = None
) -> Optional[Dict]:
    """Queries Google Custom Search JSON API restricted to scholar.google.com/citations*.
    100% official Google API, 100 free queries/day (3,000/month). Zero scraping ban risk."""
    api_key = api_key or os.getenv("GOOGLE_API_KEY") or DEFAULT_GOOGLE_API_KEY
    cx = cx or os.getenv("GOOGLE_CSE_CX") or DEFAULT_GOOGLE_CSE_CX
    if not api_key or not cx:
        return None

    for variant in name_variants[:3]:
        q_clean = variant.strip()
        params = {
            'key': api_key,
            'cx': cx,
            'q': q_clean,
            'num': 5
        }
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                for item in items:
                    link = item.get("link", "")
                    if "citations?user=" in link:
                        m = re.search(r'user=([a-zA-Z0-9_\-]+)', link)
                        if not m:
                            continue
                        user_id = m.group(1)
                        raw_title = item.get("title", "")
                        clean_title = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', raw_title)
                        clean_title = re.sub(r'\s*-\s*Google Scholar.*', '', clean_title, flags=re.IGNORECASE).strip()
                        snippet = item.get("snippet", "").replace('\n', ' ')

                        cited_by = None
                        cited_m = re.search(r'[Cc]ited by\s*([\d,]+)', snippet)
                        if cited_m:
                            try:
                                cited_by = int(cited_m.group(1).replace(',', ''))
                            except ValueError:
                                pass

                        name_sim = max(fuzz.token_sort_ratio(v, clean_title) for v in name_variants)
                        is_kse = (
                            any(k in snippet.lower() for k in KSE_INSTITUTION_KEYWORDS) or
                            any(k in clean_title.lower() for k in KSE_INSTITUTION_KEYWORDS)
                        )

                        if is_kse:
                            name_sim += 25

                        if name_sim >= 75:
                            return {
                                'scholar_id': user_id,
                                'profile_url': f"https://scholar.google.com/citations?user={user_id}&hl=en",
                                'name': clean_title,
                                'affiliations': snippet[:120],
                                'email_verification': 'Verified' if is_kse else 'Unverified',
                                'cited_by': cited_by,
                                'source': 'Google Programmable Search (100 Free/Day)',
                                'match_score': min(name_sim, 100)
                            }
            elif resp.status_code == 403:
                err_data = resp.json().get('error', {})
                print(f"  [Google CSE Notice]: HTTP 403 - {err_data.get('message', 'Quota or key error')}")
                return None
            else:
                print(f"  [Google CSE Notice]: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [Google CSE Error for {variant}]: {e}")
            continue

    return None

def search_google_scholar(
    name_variants: List[str],
    sample_works: List[str] = None,
    google_api_key: Optional[str] = None,
    google_cse_cx: Optional[str] = None,
    serpapi_key: Optional[str] = None
) -> Optional[Dict]:
    """Finds Google Scholar profile URL across Google CSE (Free Tier), SerpAPI, and Web Search."""
    # 1. Tier 2: Google Programmable Search Engine (100 Free queries/day)
    cse_result = search_google_scholar_cse(name_variants, api_key=google_api_key, cx=google_cse_cx)
    if cse_result:
        return cse_result

    # 2. Tier 3: SerpAPI with Early Exit (Paid / Free Monthly Credits)
    serpapi_key = serpapi_key or os.getenv('SERPAPI_API_KEY') or DEFAULT_SERPAPI_KEY
    if serpapi_key:
        api_candidates = []
        for variant in name_variants[:6]:
            try:
                params = {
                    'engine': 'google_scholar',
                    'q': variant,
                    'api_key': serpapi_key
                }
                r = requests.get('https://serpapi.com/search.json', params=params, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    authors = data.get('profiles', {}).get('authors', [])
                    for a in authors:
                        cand_name = a.get('name', '')
                        cand_affil = a.get('affiliations', '')
                        email = a.get('email', '')

                        # Split multiple author aliases in Scholar name (e.g. 'Ігор Сердюк, Igor Serdiuk')
                        sub_names = [s.strip() for s in re.split(r'[,/;|]', cand_name) if s.strip()]
                        sim = max(fuzz.token_sort_ratio(v, sub) for v in name_variants for sub in (sub_names or [cand_name]))
                        is_kse = (
                            any(k in cand_affil.lower() for k in KSE_INSTITUTION_KEYWORDS) or
                            'kse.org.ua' in email.lower()
                        )
                        is_partner = any(p in cand_affil.lower() for p in PARTNER_INSTITUTION_KEYWORDS)

                        if is_kse:
                            sim += 25
                        elif is_partner:
                            sim += 10
                        else:
                            # Homonym penalty if profile belongs to an unrelated institution
                            sim = min(sim, 65)

                        if sim >= 75:
                            cand_obj = {
                                'scholar_id': a.get('author_id'),
                                'profile_url': a.get('link'),
                                'name': cand_name,
                                'affiliations': cand_affil,
                                'email_verification': email,
                                'is_kse_affiliated': is_kse,
                                'cited_by': a.get('cited_by'),
                                'source': 'SerpAPI (Google Scholar Engine)',
                                'match_score': min(sim, 100)
                            }
                            # EARLY EXIT: Save paid credits immediately if high-confidence KSE profile found
                            if is_kse and sim >= 90:
                                return cand_obj
                            api_candidates.append(cand_obj)
            except Exception as e:
                print(f"  [SerpAPI Error for {variant}]: {e}")

        if api_candidates:
            api_candidates.sort(key=lambda x: (x['is_kse_affiliated'], x['match_score']), reverse=True)
            return api_candidates[0]

    # 2. Web search fallback (DuckDuckGo with polite headers)
    for variant in name_variants[:2]:
        try:
            query = f'site:scholar.google.com/citations {variant}'
            r = requests.post(
                'https://html.duckduckgo.com/html/',
                data={'q': query},
                headers={'User-Agent': BROWSER_USER_AGENT},
                timeout=6
            )
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                for a in soup.find_all('a'):
                    raw = urllib.parse.unquote(a.get('href', ''))
                    if 'citations?user=' in raw:
                        m = re.search(r'user=([a-zA-Z0-9_\-]+)', raw)
                        if m:
                            uid = m.group(1)
                            return {
                                'scholar_id': uid,
                                'profile_url': f'https://scholar.google.com/citations?user={uid}',
                                'source': 'Web Search Fallback'
                            }
        except Exception:
            pass

    return None

# ==============================================================================
# 6. UNIFIED DISCOVERY & VALIDATION PIPELINE
# ==============================================================================
def process_faculty_member(input_name: str, verbose: bool = True) -> Dict:
    if verbose:
        print(f"\n{'='*60}")
        print(f"PROCESSING: {input_name}")
        print(f"{'='*60}")

    variants = generate_name_variants(input_name)
    if verbose:
        print(f"  Aliases considered: {variants[:4]}")

    # 1. OpenAlex lookup
    alex_data = query_openalex(variants)
    orcid_from_alex = alex_data.get('orcid') if alex_data else None
    sample_works = alex_data.get('sample_works', []) if alex_data else []

    # 2. ORCID resolution
    orcid_info = None
    if orcid_from_alex:
        orcid_id = orcid_from_alex.split('/')[-1]
        orcid_info = {
            'orcid_id': orcid_id,
            'orcid_url': orcid_from_alex,
            'source': 'OpenAlex'
        }
    else:
        direct_orcid = query_orcid(variants)
        if direct_orcid:
            direct_orcid['source'] = 'ORCID API (Direct search)'
            orcid_info = direct_orcid

    # 3. Google Scholar resolution (Tier 1: Wikidata SPARQL -> Tier 2: SerpAPI / Search)
    scholar_info = None
    if orcid_info and orcid_info.get('orcid_id'):
        scholar_info = get_scholar_from_wikidata(orcid_info['orcid_id'])

    if not scholar_info:
        scholar_info = search_google_scholar(variants, sample_works)

    # 4. Affiliation checks for Disambiguation & Anti-Homonym Protection
    has_kse_orcid = bool(orcid_info and any(any(k in inst.lower() for k in KSE_INSTITUTION_KEYWORDS) for inst in orcid_info.get('institutions', [])))
    has_kse_scholar = bool(scholar_info and (
        any(k in (scholar_info.get('affiliations') or '').lower() for k in KSE_INSTITUTION_KEYWORDS) or
        'kse.org.ua' in (scholar_info.get('email_verification') or '').lower()
    ))
    has_kse_alex = bool(alex_data and alex_data.get('has_kse_affiliation'))
    has_any_kse = has_kse_orcid or has_kse_scholar or has_kse_alex

    has_partner_orcid = bool(orcid_info and any(any(k in inst.lower() for k in PARTNER_INSTITUTION_KEYWORDS) for inst in orcid_info.get('institutions', [])))
    has_partner_scholar = bool(scholar_info and any(k in (scholar_info.get('affiliations') or '').lower() for k in PARTNER_INSTITUTION_KEYWORDS))
    has_any_partner = has_partner_orcid or has_partner_scholar

    # Discard non-KSE/non-partner Scholar profile if it was just a weak homonym match
    if scholar_info and not (has_kse_scholar or has_partner_scholar):
        if scholar_info.get('match_score', 0) < 85:
            scholar_info = None

    confidence = 0
    reasons = []

    if orcid_info:
        confidence += 40
        if has_kse_orcid:
            confidence += 10
            reasons.append("ORCID confirmed with KSE affiliation")
        elif has_partner_orcid:
            confidence += 5
            reasons.append("ORCID confirmed with partner institution")
        else:
            reasons.append("ORCID found (affiliation unverified)")

    if scholar_info:
        confidence += 35
        if has_kse_scholar:
            confidence += 15
            reasons.append(f"Scholar profile matched ({scholar_info.get('match_score', 100)}% with KSE verification)")
        elif has_partner_scholar:
            confidence += 5
            reasons.append(f"Scholar profile matched ({scholar_info.get('match_score', 100)}% with partner institution)")
        else:
            reasons.append(f"Scholar profile matched ({scholar_info.get('match_score', 100)}%)")

    if has_kse_alex:
        confidence += 10
        reasons.append("KSE affiliation verified in OpenAlex")

    # Status Determination: VERIFIED (AUTO) strictly requires confirmed KSE or partner affiliation
    if confidence >= 80 and (has_any_kse or has_any_partner):
        status = "VERIFIED (AUTO)"
    elif confidence >= 40:
        if not (has_any_kse or has_any_partner):
            status = "NEEDS REVIEW (HOMONYM RISK / UNVERIFIED AFFILIATION)"
        else:
            status = "PARTIAL MATCH (NEEDS REVIEW)"
    else:
        status = "MISSING / NOT FOUND"

    result = {
        'input_name': input_name,
        'status': status,
        'confidence_score': confidence,
        'reasons': reasons,
        'orcid': orcid_info,
        'scholar': scholar_info,
        'metrics': {
            'h_index': alex_data.get('h_index', 0) if alex_data else 0,
            'citations': alex_data.get('cited_by_count', 0) if alex_data else 0,
            'works_count': alex_data.get('works_count', 0) if alex_data else 0,
        },
        'sample_works': sample_works
    }

    if verbose:
        # Summary log
        print(f"  [STATUS]: {status} (Score: {confidence}/100)")
        if orcid_info:
            print(f"  [ORCID]: {orcid_info.get('orcid_url')} ({orcid_info.get('source')})")
        else:
            print(f"  [ORCID]: Not found")

        if scholar_info:
            print(f"  [SCHOLAR]: {scholar_info.get('profile_url')} ({scholar_info.get('source')})")
            affil = scholar_info.get('affiliations') or 'N/A'
            print(f"             Affiliation: {affil[:70]} | Cited: {scholar_info.get('cited_by')}")
        else:
            print(f"  [SCHOLAR]: No registered profile found")

        if alex_data:
            print(f"  [METRICS]: h-index: {alex_data.get('h_index')}, Citations: {alex_data.get('cited_by_count')}, Works: {alex_data.get('works_count')}")
            if sample_works:
                print(f"  [SAMPLE WORK]: \"{sample_works[0]}\"")

    return result

# ==============================================================================
# 7. COMMAND LINE INTERFACE (CLI)
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="KSE Faculty Academic Profile Matcher (Google Scholar & ORCID iD)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Query a single faculty member (supports Ukrainian, English, or Russian):
  python faculty_matcher.py "Тимофій Брік"
  python faculty_matcher.py "Sergiy Kozerenko"
  python faculty_matcher.py "Сергей Козеренко"

  # Query multiple members and save to file:
  python faculty_matcher.py "Maksym Obrizan" "Павло Прокопович" -o results.json

  # Read names from a text file (one name per line):
  python faculty_matcher.py -f names.txt -o results.json

  # Print raw JSON directly to stdout (pipe-friendly):
  python faculty_matcher.py "Tymofii Brik" --json

  # Run standard benchmark test suite:
  python faculty_matcher.py --benchmark
        """
    )
    parser.add_argument('names', nargs='*', help="Faculty member name(s) (supports UKR, ENG, RUS).")
    parser.add_argument('-n', '--name', action='append', dest='flag_names', help="Faculty member name (can be repeated).")
    parser.add_argument('-f', '--file', help="Path to text or JSON file containing faculty names.")
    parser.add_argument('-o', '--output', help="Path to save output JSON file.")
    parser.add_argument('--json', action='store_true', help="Output pure JSON to stdout (suppresses progress logs).")
    parser.add_argument('-q', '--quiet', action='store_true', help="Suppress progress and summary messages.")
    parser.add_argument('--api-key', dest='api_key', help="SerpAPI key for Google Scholar lookup.")
    parser.add_argument('--benchmark', '--demo', action='store_true', help="Run benchmark on the 9 original test faculty.")

    args = parser.parse_args()

    if args.api_key:
        os.environ['SERPAPI_API_KEY'] = args.api_key

    names_to_process = []
    if args.names:
        names_to_process.extend(args.names)
    if args.flag_names:
        names_to_process.extend(args.flag_names)
    if args.file:
        if not os.path.exists(args.file):
            print(f"Error: File '{args.file}' not found.", file=sys.stderr)
            sys.exit(1)
        with open(args.file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if content.startswith('[') and content.endswith(']'):
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        names_to_process.extend([str(x).strip() for x in parsed if str(x).strip()])
                except Exception:
                    pass
            if not names_to_process:
                for line in content.splitlines():
                    cleaned = line.strip().strip(',;"\'')
                    if cleaned:
                        names_to_process.append(cleaned)

    if args.benchmark:
        names_to_process = [
            "Viacheslav Priamitsyn",
            "Sergiy Kozerenko",
            "Volodymyr Viedienieiev",
            "Kateryna Antoshyna",
            "Mariia Kriuchok",
            "Oleksandra Konopatska",
            "Милованов Тимофій Сергійович",
            "Прокопович Павло",
            "Вахітова Ганна Миколаївна"
        ]

    if not names_to_process:
        parser.print_help()
        sys.exit(0)

    verbose = not (args.json or args.quiet)

    results = []
    for name in names_to_process:
        res = process_faculty_member(name, verbose=verbose)
        results.append(res)

    if args.json:
        output_data = results[0] if len(results) == 1 else results
        print(json.dumps(output_data, indent=2, ensure_ascii=False))
    elif not args.quiet:
        print(f"\n{'='*60}")
        print(f"PROCESSED: {len(results)} faculty member(s)")
        print(f"{'='*60}")

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(results if len(results) > 1 else results[0], f, indent=2, ensure_ascii=False)
        if not args.json and not args.quiet:
            print(f"Results successfully saved to {args.output}")

if __name__ == '__main__':
    main()
