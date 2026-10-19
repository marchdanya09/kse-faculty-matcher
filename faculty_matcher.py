import warnings
warnings.filterwarnings("ignore")

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple
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
DEFAULT_SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
DEFAULT_GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
DEFAULT_GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "")
DEFAULT_OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "")
POLITE_EMAIL = "grant@kse.org.ua"
POLITE_USER_AGENT = f"KSE-DataQuality/1.0 (mailto:{POLITE_EMAIL})"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

def resolve_api_keys(
    serper_key: Optional[str] = None,
    serpapi_key: Optional[str] = None
) -> Tuple[str, str]:
    """Resolves Serper and SerpAPI keys with auto-detection for 40-character keys."""
    resolved_serper = (serper_key or os.getenv("SERPER_API_KEY") or DEFAULT_SERPER_API_KEY).strip()
    resolved_serpapi = (serpapi_key or os.getenv("SERPAPI_API_KEY") or DEFAULT_SERPAPI_KEY).strip()
    # Auto-detect: Serper.dev keys are 40 hex chars, SerpAPI keys are 64 hex chars
    if not resolved_serper and len(resolved_serpapi) == 40:
        resolved_serper = resolved_serpapi
        resolved_serpapi = ""
    elif len(resolved_serpapi) == 40 and resolved_serper == resolved_serpapi:
        resolved_serpapi = ""
    return resolved_serper, resolved_serpapi

KSE_INSTITUTION_KEYWORDS = [
    'kyiv school of economics', 'kse', 'kyiv economics institute',
    'economics education and research consortium', 'eerc', 'київська школа економіки',
    'київська школа'
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
    'ь': '', '\'': '', '’': '', 'ʼ': '', '`': '', '‘': '', '´': '', 'ʻ': ''
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
    'і': 'i', 'І': 'I', 'ї': 'i', 'Ї': 'I', 'є': 'ye', 'Є': 'Ye', 'ґ': 'g', 'Ґ': 'G',
    '\'': '', '’': '', 'ʼ': '', '`': '', '‘': '', '´': '', 'ʻ': ''
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
    if not name or not name.strip():
        return []
    clean_str = re.sub(r'[\’\ʼ\`\‘\´\ʻ]', "'", name.strip())
    clean_str = re.sub(r'\s*-\s*', '-', clean_str)
    tokens = [t for t in re.split(r'\s+', clean_str) if t]
    if not tokens:
        return [name]

    clean_tokens = list(tokens)
    # Strip patronymic ONLY if 3+ tokens (protects surnames like Прокопович).
    # Check tokens[1] first so "First Patronymic Last" (e.g. Павло Олександрович Прокопович)
    # does not accidentally strip the surname Прокопович!
    if len(tokens) >= 3:
        if tokens[1].lower().endswith(PATRONYMIC_ENDINGS):
            clean_tokens = [tokens[0]] + tokens[2:]
        elif tokens[-1].lower().endswith(PATRONYMIC_ENDINGS):
            clean_tokens = tokens[:-1]

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
        # Latin input: generate swapped orders
        for order in orders:
            variants.add(order)
            if 'ii' in order:
                variants.add(order.replace('ii', 'iy'))
            if 'iy' in order:
                variants.add(order.replace('iy', 'ii'))

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
                'elen', 'yur', 'anna', 'hann', 'tet', 'tat', 'viach', 'vyach',
                'myk', 'mik', 'oleks', 'alex', 'andr', 'dmyt', 'dmit', 'rom',
                'nat', 'boh', 'bog', 'tar', 'vas', 'vikt', 'yevh', 'evg',
                'yul', 'oks', 'dar', 'svit', 'stan', 'den', 'ant', 'art',
                'borys', 'boris', 'kost', 'kyr', 'kir', 'lev', 'mary', 'nadi',
                'pol', 'step', 'yar', 'rusl', 'bahr', 'vad'
            ]):
                score += 50
            if first_part.startswith('volod'):
                score += 15
            if 'iy' in first_part or 'ii' in first_part:
                score += 30
            elif 'ey' in first_part:
                score += 25
            if 'giy' in first_part or 'gey' in first_part or 'gomza' in v.lower():
                score += 20
        return score

    ranked_latin = sorted(latin_variants, key=_rank_latin_variant, reverse=True)
    if has_cyrillic:
        primary_ukr = transliterate_ukr(' '.join(clean_tokens))
        primary_ukr_g = re.sub(r'\bH', 'G', re.sub(r'\bh', 'g', primary_ukr))
        for p in reversed([primary_ukr, primary_ukr_g]):
            if p in ranked_latin:
                ranked_latin.remove(p)
                ranked_latin.insert(0, p)

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
def normalize_title(title: str) -> str:
    """Normalizes publication title by stripping HTML entities, unicode quotes, dashes, and extra whitespace."""
    if not title:
        return ""
    import html
    t = html.unescape(str(title))
    # Normalize unicode quotes and apostrophes
    t = re.sub(r'[\u2018\u2019\u201A\u201B\u2032\u02BC`]', "'", t)
    t = re.sub(r'[\u201C\u201D\u201E\u201F\u2033"]', '"', t)
    # Normalize unicode hyphens and dashes
    t = re.sub(r'[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]', '-', t)
    # Strip HTML tags
    t = re.sub(r'<[^>]+>', ' ', t)
    # Normalize whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def match_publication_title(kw: str, candidate_title: str, threshold: float = 75) -> bool:
    """Robustly checks if a candidate work title matches a known ground-truth work."""
    if not kw or not candidate_title:
        return False
    kw_norm = normalize_title(kw).lower()
    cand_norm = normalize_title(candidate_title).lower()
    if fuzz.token_set_ratio(kw_norm, cand_norm) >= threshold:
        return True
    # Subtitle splitting: compare main titles before colon or dash
    kw_main = re.split(r'[:\-–—]', kw_norm)[0].strip()
    cand_main = re.split(r'[:\-–—]', cand_norm)[0].strip()
    if len(kw_main) > 15 and len(cand_main) > 15:
        if fuzz.token_set_ratio(kw_main, cand_main) >= max(threshold, 80):
            return True
    return False

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
                    "source": "Wikidata SPARQL Bridge (Free Tier 1)",
                    "match_score": 100,
                    "is_wikidata_crosslink": True
                }
    except Exception:
        pass
    return None

def get_orcid_from_wikidata(scholar_id: str) -> Optional[Dict]:
    """Resolves a Google Scholar ID to ORCID iD via Wikidata P496. Free, official, zero ban risk."""
    if not scholar_id:
        return None
    clean_id = scholar_id.strip()
    sparql = f"""
    SELECT ?orcid WHERE {{
      ?person wdt:P1960 "{clean_id}" .
      ?person wdt:P496 ?orcid .
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
                orcid = bindings[0]["orcid"]["value"]
                return {
                    "orcid_id": orcid,
                    "orcid_url": f"https://orcid.org/{orcid}",
                    "source": "Wikidata SPARQL Bridge (Free Tier 1)",
                    "match_score": 100,
                    "is_wikidata_crosslink": True
                }
    except Exception:
        pass
    return None

class CitationParser:
    """
    Parses academic citations (APA, DSTU/GOST, Math/IEEE), extracts DOIs,
    cleans titles, and splits concatenated citation strings without collapsing papers.
    """
    DOI_REGEX = re.compile(r'(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[^\s,;"<>]+)', re.IGNORECASE)

    @classmethod
    def extract_dois(cls, text: str) -> List[str]:
        if not text:
            return []
        dois = []
        for m in cls.DOI_REGEX.finditer(str(text)):
            doi = re.sub(r'[,;.\)\]]+$', '', m.group(1).strip())
            if doi and doi not in dois:
                dois.append(doi)
        return dois

    @classmethod
    def split_citations(cls, raw: str) -> List[str]:
        if not raw or not str(raw).strip():
            return []
        text = str(raw).strip()
        # 1. Normalize numbered items preceded by comma, semicolon, newline, or dot (1-99)
        text = re.sub(r'(?:^|[\r\n]+|[,;.]\s*)(\b\d{1,2}[\.\)])\s+', r'\n\1 ', text)
        # 2. Normalize citations glued after a DOI URL
        text = re.sub(r'((?:https?://)?(?:dx\.)?doi\.org/10\.\d{4,9}/[^\s,;]+)[,;]\s*(?=[A-ZА-ЯЁІЇЄ])', r'\1\n', text)
        # 3. Normalize citations glued after DOI prefix
        text = re.sub(r'(DOI:\s*10\.\d{4,9}/[^\s,;]+)[,;]\s*(?=[A-ZА-ЯЁІЇЄ])', r'\1\n', text, flags=re.IGNORECASE)
        # 4. Normalize citations glued after APA year pattern / author boundary
        text = re.sub(
            r',\s*(?=[A-ZА-ЯЁІЇЄ][a-zа-яёіїє\']+(?:,\s*[A-ZА-ЯЁІЇЄ]\.|\s+[A-ZА-ЯЁІЇЄ]\.)[^(]{0,120}\((?:19|20)\d{2}[a-z]?\))',
            r'\n',
            text
        )

        raw_chunks = re.split(r'[\r\n]+|;\s*', text)
        chunks = []
        for c in raw_chunks:
            c = re.sub(r'^\s*\d{1,2}[\.\)]\s*', '', c).strip().strip(',;')
            if len(c) >= 10:
                chunks.append(c)
        return chunks

    @classmethod
    def extract_clean_title(cls, citation: str) -> str:
        if not citation:
            return ""
        clean = str(citation).strip()
        clean = re.sub(r'^\s*\d{1,2}[\.\)]\s*', '', clean)
        m_quotes = re.search(r'["“«]([^"”»]{10,250})["”»]', clean)
        if m_quotes:
            return m_quotes.group(1).strip()

        text_no_url = re.sub(r'https?://\S+', '', clean)
        text_no_url = re.sub(r'doi:\s*10\.\S+', '', text_no_url, flags=re.IGNORECASE)
        text_no_url = re.sub(r'\bdoi:\s*$', '', text_no_url, flags=re.IGNORECASE).strip().strip(',;.')

        if ' // ' in text_no_url:
            before = text_no_url.split(' // ')[0].strip()
            t = before.split(' / ')[0].strip() if ' / ' in before else before
            t = re.sub(r'^[A-ZА-ЯЁІЇЄ][a-zа-яёіїє\']+\s+[A-ZА-ЯЁІЇЄ]\.[A-ZА-ЯЁІЇЄ]?\.?\s*', '', t)
            return t.strip().strip('"\'')
        elif ' / ' in text_no_url:
            t = text_no_url.split(' / ')[0].strip()
            t = re.sub(r'^[A-ZА-ЯЁІЇЄ][a-zа-яёіїє\']+\s+[A-ZА-ЯЁІЇЄ]\.[A-ZА-ЯЁІЇЄ]?\.?\s*', '', t)
            return t.strip().strip('"\'')

        m_apa = re.search(r'^\s*[^()]{2,140}\(\s*(?:19|20)\d{2}[a-z]?\s*\)\s*[\.:]\s*([^.\n\?!]+)', text_no_url)
        if m_apa:
            return m_apa.group(1).strip().strip('"\'')

        parts = [p.strip() for p in re.split(r'(?<!\b[A-ZА-ЯЁІЇЄ])\.\s+', text_no_url) if p.strip()]
        cand_parts = [p for p in parts if len(p) >= 8 and not re.match(r'^(?:doi|vol|volume|no|pp|pages)\b', p, re.I)]
        if len(cand_parts) >= 2:
            return cand_parts[1].strip().strip('"\'')

        comma_parts = [cp.strip() for cp in text_no_url.split(',') if cp.strip()]
        if len(comma_parts) >= 3:
            for cp in comma_parts:
                has_initials = bool(re.search(r'\b[A-ZА-ЯЁІЇЄ]\.', cp))
                is_volume_pages = bool(re.search(r'^\d+|^\(\d{4}\)', cp))
                if not has_initials and not is_volume_pages and len(cp) >= 6:
                    return cp.strip().strip('"\'')

        return text_no_url.strip().strip('"\'')

    @classmethod
    def parse_works(cls, works_input: List[str]) -> List[Dict]:
        results = []
        seen = set()
        for item in (works_input or []):
            if not item:
                continue
            for chunk in cls.split_citations(str(item)):
                dois = cls.extract_dois(chunk)
                doi = dois[0] if dois else None
                title = cls.extract_clean_title(chunk)
                key = doi.lower() if doi else (title.lower() if title else '')
                if key and key not in seen:
                    seen.add(key)
                    results.append({
                        'doi': doi,
                        'title': title,
                        'raw': chunk
                    })
        return results

def normalize_phonetic_surname(s: str) -> str:
    """Normalizes phonetic variations in Ukrainian, Russian, and English transliterated surnames."""
    if not s:
        return ''
    if any(ord(c) > 127 for c in s):
        s = transliterate_ukr(s)
    s = s.strip().lower()
    s = re.sub(r'[\’\ʼ\`\‘\´\ʻ\']', '', s)
    s = s.replace('shch', 'sc').replace('kh', 'h').replace('x', 'h').replace('zh', 'z').replace('ch', 'c').replace('sh', 's').replace('ts', 'c')
    s = s.replace('g', 'h').replace('w', 'v').replace('y', 'i').replace('j', 'i')
    s = re.sub(r'(.)\1+', r'\1', s)
    s = re.sub(r'i+$', '', s)
    return s

def parse_name_parts(name: str) -> Tuple[str, str]:
    """Extracts given name and surname, accounting for patronymics and Slavic name orders."""
    tokens = [t.strip('.,') for t in re.split(r'\s+', name.strip()) if t.strip('.,')]
    if not tokens:
        return '', ''
    if len(tokens) >= 3:
        if tokens[1].lower().endswith(PATRONYMIC_ENDINGS):
            tokens = [tokens[0]] + tokens[2:]
        elif tokens[-1].lower().endswith(PATRONYMIC_ENDINGS):
            tokens = tokens[:-1]
    if len(tokens) == 1:
        return '', tokens[0]
    known_first_cyr = set(CROSS_LANG_NAME_PAIRS.keys()) | set(CROSS_LANG_NAME_PAIRS.values())
    known_first_lat = set(LATIN_TO_CYR_NAMES.keys())
    t0_low = tokens[0].lower()
    t1_low = tokens[1].lower()
    if t0_low in known_first_cyr or t0_low in known_first_lat or any(t0_low.startswith(p) for p in ['myk', 'nik', 'olek', 'serh', 'serg', 'volod', 'vlad', 'mari', 'igor', 'ihor', 'kate', 'tymo', 'maks', 'gann', 'hann', 'tet', 'tat', 'yur', 'olen', 'elen', 'pav', 'ivan', 'rom']):
        return tokens[0], tokens[1]
    elif t1_low in known_first_cyr or t1_low in known_first_lat or any(t1_low.startswith(p) for p in ['myk', 'nik', 'olek', 'serh', 'serg', 'volod', 'vlad', 'mari', 'igor', 'ihor', 'kate', 'tymo', 'maks', 'gann', 'hann', 'tet', 'tat', 'yur', 'olen', 'elen', 'pav', 'ivan', 'rom']):
        return tokens[1], tokens[0]
    else:
        return tokens[0], tokens[1]

def get_compatible_initials(given_name: str) -> set:
    """Returns set of allowed uppercase initials for a given name across UKR, RUS, and ENG."""
    if not given_name:
        return set()
    g_low = given_name.lower().strip()
    g_tr = transliterate_ukr(given_name).lower().strip() if any(ord(c) > 127 for c in given_name) else given_name.lower().strip()
    inits = {g_tr[0].upper()} if g_tr else set()

    # Check specific cross-language initial pairs:
    # 1. Mykola / Nikolay (M <-> N)
    if any(g_low.startswith(p) for p in ('микол', 'никол')) or any(g_tr.startswith(p) for p in ('mykol', 'nikol', 'mikol')):
        inits.add('M')
        inits.add('N')
    # 2. Ganna / Hanna / Anna (G <-> H <-> A)
    elif any(g_low.startswith(p) for p in ('ганн', 'анн')) or any(g_tr.startswith(p) for p in ('gann', 'hann', 'ann')):
        inits.add('G')
        inits.add('H')
        inits.add('A')
    # 3. Olena / Elena (O <-> E)
    elif any(g_low.startswith(p) for p in ('олен', 'єлен', 'елен')) or any(g_tr.startswith(p) for p in ('olen', 'elen', 'yelen')):
        inits.add('O')
        inits.add('E')
    # 4. Oleksandr / Aleksandr (O <-> A)
    elif any(g_low.startswith(p) for p in ('олександр', 'александр')) or any(g_tr.startswith(p) for p in ('oleks', 'aleks')):
        inits.add('O')
        inits.add('A')
    # 5. Oleksiy / Aleksey (O <-> A)
    elif any(g_low.startswith(p) for p in ('олексі', 'алексе')) or any(g_tr.startswith(p) for p in ('oleks', 'aleks')):
        inits.add('O')
        inits.add('A')
    # 6. Yevhen / Evgeny (Y <-> E)
    elif any(g_low.startswith(p) for p in ('євген', 'евген')) or any(g_tr.startswith(p) for p in ('yevh', 'evg', 'eug')):
        inits.add('Y')
        inits.add('E')
    return inits

def match_author_in_work(target_name: str, authorships: list) -> list:
    """Disambiguates candidate authors on a paper using two-token matching (surname + given name / initial)."""
    given, surname = parse_name_parts(target_name)
    norm_surname = normalize_phonetic_surname(surname)
    compatible_inits = get_compatible_initials(given)

    matches = []
    for a in authorships:
        c_name = a.get('name') or ''
        c_tokens = [t.strip('.,') for t in re.split(r'\s+', c_name) if t.strip('.,')]
        if not c_tokens:
            continue

        surname_idx = -1
        for idx, tok in enumerate(c_tokens):
            if normalize_phonetic_surname(tok) == norm_surname or fuzz.ratio(normalize_phonetic_surname(tok), norm_surname) >= 85:
                surname_idx = idx
                break
        if surname_idx == -1:
            continue

        rem_tokens = [c_tokens[i] for i in range(len(c_tokens)) if i != surname_idx]
        if not rem_tokens:
            matches.append((a, 50, 'surname_only'))
            continue

        given_matched = False
        match_type = ''
        for tok in rem_tokens:
            tok_init = tok[0].upper()
            tok_tr = transliterate_ukr(tok) if any(ord(c) > 127 for c in tok) else tok
            given_tr = transliterate_ukr(given) if any(ord(c) > 127 for c in given) else given

            if len(tok_tr) > 1 and len(given_tr) > 1 and fuzz.ratio(tok_tr.lower(), given_tr.lower()) >= 70:
                given_matched = True
                match_type = 'full_name'
                break
            elif tok_init in compatible_inits:
                given_matched = True
                match_type = 'initial'
                break

        if given_matched:
            matches.append((a, 100 if match_type == 'full_name' else 85, match_type))

    return matches

def resolve_author_from_works(
    target_name: str,
    name_variants: List[str],
    works_list: List[str],
    openalex_api_key: Optional[str] = None
) -> Optional[Dict]:
    """
    Priority 1 Inverted Resolver:
    Queries OpenAlex Works API (with Polite Pool mailto, backoff, and Crossref fallback)
    using extracted DOIs or clean titles. Disambiguates authorships via two-token matching.
    Returns author profile dict containing canonical name, ORCID, OpenAlex ID, and paper metrics.
    """
    if not works_list:
        return None

    openalex_key = (openalex_api_key or os.getenv("OPENALEX_API_KEY") or DEFAULT_OPENALEX_API_KEY).strip()
    parsed_works = CitationParser.parse_works(works_list)
    if not parsed_works:
        return None

    # Sort so works with DOI come first
    sorted_works = sorted(parsed_works, key=lambda w: (bool(w.get('doi')), len(w.get('title') or '')), reverse=True)

    for work_item in sorted_works[:5]:
        doi = work_item.get('doi')
        clean_title = work_item.get('title') or ''

        work_data = None
        source_api = None

        # 1. Try OpenAlex Works API
        if doi:
            oa_url = f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi)}?mailto={POLITE_EMAIL}"
            headers = {"User-Agent": POLITE_USER_AGENT}
            if openalex_key:
                headers["api_key"] = openalex_key
            req = urllib.request.Request(oa_url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    work_data = json.loads(resp.read().decode('utf-8'))
                    source_api = "OpenAlex (DOI)"
            except urllib.error.HTTPError:
                work_data = None
            except Exception:
                work_data = None
        elif len(clean_title) >= 15:
            oa_url = f"https://api.openalex.org/works?search={urllib.parse.quote(clean_title[:100])}&per_page=3&mailto={POLITE_EMAIL}"
            headers = {"User-Agent": POLITE_USER_AGENT}
            if openalex_key:
                headers["api_key"] = openalex_key
            req = urllib.request.Request(oa_url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    search_res = json.loads(resp.read().decode('utf-8'))
                    for r_item in search_res.get('results', []):
                        r_title = str(r_item.get('title') or '')
                        if match_publication_title(clean_title, r_title, threshold=70):
                            work_data = r_item
                            source_api = "OpenAlex (Title Search)"
                            break
            except urllib.error.HTTPError:
                work_data = None
            except Exception:
                work_data = None

        # 2. Crossref Fallback if OpenAlex didn't return work data
        if not work_data:
            if doi:
                cr_url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
                cr_req = urllib.request.Request(cr_url, headers={"User-Agent": POLITE_USER_AGENT})
                try:
                    with urllib.request.urlopen(cr_req, timeout=8) as cr_resp:
                        cr_json = json.loads(cr_resp.read().decode('utf-8'))
                        work_data = cr_json.get('message', {})
                        source_api = "Crossref (DOI)"
                except Exception:
                    pass
            elif len(clean_title) >= 15:
                cr_url = f"https://api.crossref.org/works?query.title={urllib.parse.quote(clean_title[:100])}&rows=3"
                cr_req = urllib.request.Request(cr_url, headers={"User-Agent": POLITE_USER_AGENT})
                try:
                    with urllib.request.urlopen(cr_req, timeout=8) as cr_resp:
                        cr_json = json.loads(cr_resp.read().decode('utf-8'))
                        for item in cr_json.get('message', {}).get('items', []):
                            item_titles = item.get('title', [])
                            t_cand = item_titles[0] if (item_titles and isinstance(item_titles, list)) else ''
                            if match_publication_title(clean_title, str(t_cand), threshold=70):
                                work_data = item
                                source_api = "Crossref (Title Search)"
                                break
                except Exception:
                    pass

        if not work_data:
            continue

        # 3. Extract authorships from work_data (normalize between OpenAlex and Crossref)
        authors_normalized = []
        if "authorships" in work_data:
            for a_item in work_data.get("authorships", []):
                a_obj = a_item.get("author") or {}
                raw_name = a_obj.get("display_name") or ""
                raw_orcid = a_obj.get("orcid") or ""
                clean_orcid = raw_orcid.split("/")[-1].strip() if raw_orcid else None
                insts = [
                    str((inst.get("display_name") or ""))
                    for inst in (a_item.get("institutions") or [])
                    if isinstance(inst, dict) and inst.get("display_name")
                ]
                authors_normalized.append({
                    "name": raw_name,
                    "orcid": clean_orcid,
                    "id": a_obj.get("id"),
                    "institutions": insts,
                    "source": source_api
                })
        elif "author" in work_data:
            for a_item in work_data.get("author", []):
                given = a_item.get("given") or ""
                family = a_item.get("family") or ""
                full = f"{given} {family}".strip()
                raw_orcid = a_item.get("ORCID") or ""
                clean_orcid = raw_orcid.split("/")[-1].strip() if raw_orcid else None
                authors_normalized.append({
                    "name": full,
                    "orcid": clean_orcid,
                    "id": None,
                    "institutions": [],
                    "source": source_api
                })

        # 4. Disambiguate author matching target_name using two-token matching (require given name / initial, score >= 80)
        matched_authors = match_author_in_work(target_name, authors_normalized)
        valid_matches = [m for m in matched_authors if m[1] >= 80]
        if len(valid_matches) == 1:
            best_author, match_score, match_type = valid_matches[0]
            canonical_name = best_author.get("name")
            resolved_orcid = best_author.get("orcid")
            oa_author_id = best_author.get("id")

            item_title_val = work_item.get("title") or (work_data.get("title") if isinstance(work_data.get("title"), str) else "")
            h_index = 0
            cited_by_count = 0
            works_count = 0
            sample_works = [item_title_val] if item_title_val else []
            if oa_author_id:
                clean_aid = oa_author_id.split("/")[-1]
                oa_author_url = f"https://api.openalex.org/authors/{clean_aid}?mailto={POLITE_EMAIL}"
                headers_a = {"User-Agent": POLITE_USER_AGENT}
                if openalex_key:
                    headers_a["api_key"] = openalex_key
                try:
                    req_a = urllib.request.Request(oa_author_url, headers=headers_a)
                    with urllib.request.urlopen(req_a, timeout=6) as resp_a:
                        a_data = json.loads(resp_a.read().decode('utf-8'))
                        stats = a_data.get("summary_stats") or {}
                        h_index = stats.get("h_index", 0)
                        cited_by_count = a_data.get("cited_by_count", 0)
                        works_count = a_data.get("works_count", 0)
                        if not resolved_orcid and a_data.get("orcid"):
                            resolved_orcid = a_data["orcid"].split("/")[-1].strip()
                except Exception:
                    pass

            return {
                "canonical_name": canonical_name,
                "orcid_id": resolved_orcid,
                "openalex_id": oa_author_id,
                "institutions": best_author.get("institutions", []),
                "matched_work_title": item_title_val,
                "work_doi": doi,
                "h_index": h_index,
                "cited_by_count": cited_by_count,
                "works_count": works_count,
                "sample_works": sample_works,
                "source": source_api
            }
        elif len(valid_matches) > 1:
            continue

    return None

def fetch_orcid_works(orcid_id: str) -> List[str]:
    """Retrieves titles of public works from an ORCID iD. 100% free, official public API."""
    if not orcid_id:
        return []
    clean_id = orcid_id.split('/')[-1].strip()
    url = f"https://pub.orcid.org/v3.0/{clean_id}/works"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": POLITE_USER_AGENT}
    )
    works = []
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for group in (data.get("group") or []):
                for summary in (group.get("work-summary") or []):
                    title_obj = (summary.get("title") or {}).get("title") or {}
                    t_val = title_obj.get("value")
                    if t_val and str(t_val).strip():
                        works.append(str(t_val).strip())
    except Exception:
        pass
    return works

def resolve_direct_orcid(orcid_input: str) -> Optional[Dict]:
    """Directly resolves a pre-known ORCID iD or URL."""
    if not orcid_input:
        return None
    m = re.search(r'(\d{4}-\d{4}-\d{4}-[\dX]{4})', orcid_input)
    if not m:
        return None
    clean_id = m.group(1)
    url = f"https://pub.orcid.org/v3.0/{clean_id}/record"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": POLITE_USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            person = data.get("person") or {}
            name_obj = person.get("name") or {}
            given = ((name_obj.get("given-names") or {}).get("value") or "").strip()
            family = ((name_obj.get("family-name") or {}).get("value") or "").strip()
            full_name = f"{given} {family}".strip()

            insts = []
            employments = ((data.get("activities-summary") or {}).get("employments") or {}).get("affiliation-group") or []
            for aff in employments:
                for sum_item in (aff.get("summaries") or []):
                    emp = sum_item.get("employment-summary") or {}
                    org = (emp.get("organization") or {}).get("name")
                    if org:
                        insts.append(str(org))

            return {
                'orcid_id': clean_id,
                'orcid_url': f"https://orcid.org/{clean_id}",
                'name_in_orcid': full_name,
                'institutions': insts,
                'source': 'ORCID (Direct Ground Truth Anchor)'
            }
    except urllib.error.HTTPError as e:
        if e.code in (404, 409, 410):
            return None
        return {
            'orcid_id': clean_id,
            'orcid_url': f"https://orcid.org/{clean_id}",
            'source': 'ORCID (Direct Ground Truth Anchor)'
        }
    except Exception:
        return {
            'orcid_id': clean_id,
            'orcid_url': f"https://orcid.org/{clean_id}",
            'source': 'ORCID (Direct Ground Truth Anchor)'
        }

def safe_serpapi_get(
    params: dict,
    timeout: int = 25,
    max_retries: int = 2,
    backoff_factor: float = 1.5
) -> Optional[requests.Response]:
    """Executes a SerpAPI GET request with generous timeout (25s) and automatic retries for transient read/connect timeouts."""
    url = 'https://serpapi.com/search.json'
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code in (502, 503, 504) and attempt < max_retries:
                time.sleep(backoff_factor * (attempt + 1))
                continue
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < max_retries:
                time.sleep(backoff_factor * (attempt + 1))
                continue
            raise e
        except requests.exceptions.RequestException as e:
            raise e
    return None

def safe_serper_post(payload: Dict, api_key: str, timeout: int = 15, max_retries: int = 2) -> Optional[requests.Response]:
    """Sends a POST request to Serper.dev with retries and timeout protection."""
    if not api_key:
        return None
    headers = {
        'X-API-KEY': api_key.strip(),
        'Content-Type': 'application/json'
    }
    url = "https://google.serper.dev/search"
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code in (502, 503, 504) and attempt < max_retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt < max_retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            return None
        except Exception:
            return None
    return None

def resolve_direct_scholar(
    scholar_input: str,
    serpapi_key: Optional[str] = None,
    serper_key: Optional[str] = None
) -> Optional[Dict]:
    """Directly resolves a pre-known Google Scholar ID or URL without consuming API search credits."""
    if not scholar_input:
        return None
    m = re.search(r'user=([a-zA-Z0-9_\-]+)', scholar_input)
    scholar_id = m.group(1) if m else scholar_input.strip()

    return {
        'scholar_id': scholar_id,
        'profile_url': f"https://scholar.google.com/citations?user={scholar_id}&hl=en",
        'source': 'Google Scholar (Direct Ground Truth Anchor)',
        'match_score': 100,
        'email_verification': 'Verified'
    }

def search_scholar_by_article_serper(
    author_name: str,
    article_title: str,
    name_variants: Optional[List[str]] = None,
    serper_key: Optional[str] = None
) -> Optional[Dict]:
    """Finds Google Scholar profile via Serper.dev by querying article title and matching author link."""
    serper_key, _ = resolve_api_keys(serper_key=serper_key)
    if not serper_key or not article_title:
        return None

    variants = name_variants or generate_name_variants(author_name)
    clean_kw = normalize_title(article_title)
    clean_kw = re.sub(r'^[\'"“‘\s]+|[\'"”’\s]+$', '', clean_kw)

    queries_to_try = [f'site:scholar.google.com/citations "{variants[0]}" {clean_kw[:50]}'.strip()]
    if ':' in clean_kw:
        main_t = clean_kw.split(':', 1)[0].strip()
        if len(main_t) > 15:
            queries_to_try.append(f'site:scholar.google.com/citations "{variants[0]}" {main_t}'.strip())

    for q_str in queries_to_try:
        try:
            r = safe_serper_post({'q': q_str}, api_key=serper_key, timeout=15, max_retries=2)
            if r and r.status_code == 200:
                data = r.json()
                for item in data.get('organic', []):
                    link = item.get('link', '')
                    if 'citations?user=' not in link:
                        continue
                    m = re.search(r'user=([a-zA-Z0-9_\-]+)', link)
                    if not m:
                        continue
                    a_id = m.group(1)
                    raw_title = str(item.get('title') or '')
                    clean_title = re.sub(r'\s*-\s*.*?(?:Google|Scholar|Академ).*', '', raw_title, flags=re.IGNORECASE).strip()
                    sub_names = [s.strip() for s in re.split(r'[,/;|]', clean_title) if s.strip()]
                    name_sim = max(fuzz.token_sort_ratio(v, sub) for v in variants for sub in (sub_names or [clean_title]))

                    if name_sim >= 70:
                        snippet = str(item.get('snippet') or '').replace('\n', ' ')
                        is_kse = (
                            any(k in snippet.lower() for k in KSE_INSTITUTION_KEYWORDS) or
                            any(k in clean_title.lower() for k in KSE_INSTITUTION_KEYWORDS) or
                            'kse.org.ua' in snippet.lower()
                        )
                        cited_by = None
                        cited_m = re.search(r'[Cc]ited by\s*([\d,]+)|[Цц]итуван[ья][\s:]*([\d,]+)|[Цц]итат[\s:]*([\d,]+)', snippet)
                        if cited_m:
                            for grp in cited_m.groups():
                                if grp:
                                    try:
                                        cited_by = int(grp.replace(',', ''))
                                        break
                                    except ValueError:
                                        pass

                        return {
                            'scholar_id': a_id,
                            'profile_url': f"https://scholar.google.com/citations?user={a_id}&hl=en",
                            'name': clean_title,
                            'affiliations': snippet[:160],
                            'email_verification': 'kse.org.ua' if 'kse.org.ua' in snippet.lower() else ('Verified' if is_kse else 'Unverified'),
                            'is_kse_affiliated': is_kse,
                            'source': 'Serper.dev (Publication Co-Citation Anchor)',
                            'match_score': 100,
                            'matched_article': article_title,
                            'ground_truth_matched': True,
                            'cited_by': cited_by
                        }
        except Exception:
            pass
    return None

def search_scholar_by_article(
    author_name: str,
    article_title: str,
    name_variants: Optional[List[str]] = None,
    serpapi_key: Optional[str] = None,
    serper_key: Optional[str] = None
) -> Optional[Dict]:
    """Finds Google Scholar profile by querying an article title and matching author link in citations."""
    serper_key, serpapi_key = resolve_api_keys(serper_key=serper_key, serpapi_key=serpapi_key)
    if serper_key:
        serper_art = search_scholar_by_article_serper(
            author_name, article_title, name_variants=name_variants, serper_key=serper_key
        )
        if serper_art:
            return serper_art

    if not serpapi_key or not article_title:
        return None

    variants = name_variants or generate_name_variants(author_name)
    clean_kw = normalize_title(article_title)
    clean_kw = re.sub(r'^[\'"“‘\s]+|[\'"”’\s]+$', '', clean_kw)

    queries_to_try = [f"{author_name} {clean_kw}".strip()]
    # If the title has a subtitle, also try querying with main title
    if ':' in clean_kw:
        main_t = clean_kw.split(':', 1)[0].strip()
        if len(main_t) > 15:
            queries_to_try.append(f"{author_name} {main_t}".strip())

    for q_str in queries_to_try:
        params = {
            'engine': 'google_scholar',
            'q': q_str,
            'api_key': serpapi_key
        }
        try:
            r = safe_serpapi_get(params, timeout=25, max_retries=2)
            if r and r.status_code == 200:
                data = r.json()
                for item in data.get('organic_results', []):
                    item_title = str(item.get('title') or '')
                    if not match_publication_title(article_title, item_title, threshold=70):
                        continue
                    # Inspect authors listed in publication_info
                    pub_info = item.get('publication_info', {})
                    authors = pub_info.get('authors', [])
                    for a in authors:
                        a_name = a.get('name', '')
                        a_id = a.get('author_id')
                        link = a.get('link', '')
                        if not a_id and 'user=' in link:
                            m = re.search(r'user=([a-zA-Z0-9_\-]+)', link)
                            if m:
                                a_id = m.group(1)

                        if not a_id:
                            continue

                        # Check name similarity with our author name variants
                        name_sim = max(fuzz.token_sort_ratio(v, a_name) for v in variants)
                        # Short initials match like 'M Trehub', 'Trehub, M', 'Trehub, M.V.'
                        if name_sim < 70:
                            clean_a = re.sub(r'[.,]', ' ', a_name).strip()
                            a_parts = clean_a.split()
                            if len(a_parts) >= 2:
                                for v in variants:
                                    v_parts = v.split()
                                    if len(v_parts) >= 2:
                                        v_surname = v_parts[-1].lower()
                                        v_initial = v_parts[0][0].upper()
                                        if a_parts[-1].lower() == v_surname and a_parts[0][0].upper() == v_initial:
                                            name_sim = 85
                                            break
                                        if a_parts[0].lower() == v_surname and a_parts[1][0].upper() == v_initial:
                                            name_sim = 85
                                            break

                        if name_sim >= 70:
                            cand_obj = {
                                'scholar_id': a_id,
                                'profile_url': f"https://scholar.google.com/citations?user={a_id}&hl=en",
                                'name': a_name,
                                'source': 'SerpAPI (Publication Co-Citation Anchor)',
                                'match_score': 100,
                                'matched_article': item_title,
                                'ground_truth_matched': True
                            }
                            # Fetch full profile info for clean affiliations and citation counts
                            try:
                                prof_r = safe_serpapi_get({
                                    'engine': 'google_scholar_author',
                                    'author_id': a_id,
                                    'api_key': serpapi_key
                                }, timeout=20, max_retries=1)
                                if prof_r and prof_r.status_code == 200:
                                    p_json = prof_r.json()
                                    p_data = (p_json.get('author') or {})
                                    cand_obj['affiliations'] = p_data.get('affiliations', '')
                                    cand_obj['email_verification'] = p_data.get('email', '')
                                    table = (p_json.get('cited_by') or {}).get('table') or []
                                    if table and isinstance(table, list) and len(table) > 0 and isinstance(table[0], dict):
                                        c_val = (table[0].get('citations') or {}).get('all')
                                        if c_val is not None:
                                            cand_obj['cited_by'] = c_val
                                    if p_data.get('name'):
                                        cand_obj['name'] = p_data.get('name')
                            except Exception:
                                pass
                            return cand_obj
        except Exception:
            pass
    return None

_VERIFIED_WORKS_CACHE: Dict[str, List[str]] = {}

def verify_scholar_candidate_works(
    scholar_id: str,
    known_works: List[str],
    serpapi_key: Optional[str] = None
) -> Optional[str]:
    """Checks if a Scholar candidate's profile contains any of the known publication titles."""
    if not scholar_id or not known_works:
        return None
    serpapi_key = (serpapi_key or os.getenv('SERPAPI_API_KEY') or DEFAULT_SERPAPI_KEY).strip()
    if not serpapi_key:
        return None

    if scholar_id in _VERIFIED_WORKS_CACHE:
        articles = _VERIFIED_WORKS_CACHE[scholar_id]
    else:
        articles = []
        try:
            r = safe_serpapi_get({
                'engine': 'google_scholar_author',
                'author_id': scholar_id,
                'api_key': serpapi_key,
                'num': 20
            }, timeout=20, max_retries=2)
            if r and r.status_code == 200:
                articles = [str(a.get('title') or '') for a in (r.json().get('articles') or []) if isinstance(a, dict) and a.get('title')]
                if articles:
                    _VERIFIED_WORKS_CACHE[scholar_id] = articles
        except Exception:
            pass

    for kw in known_works:
        for art in articles:
            if match_publication_title(kw, art, threshold=75):
                return art
    return None

# ==============================================================================
# 3. OPENALEX API (DISAMBIGUATED WITH POLITE POOL)
# ==============================================================================
def query_openalex(
    name_variants: List[str],
    known_works: Optional[List[str]] = None
) -> Optional[Dict]:
    """Queries OpenAlex author search API across variants and ranks candidates by affiliation & name match."""
    seen_ids = set()
    candidates = []

    for variant in name_variants[:4]:
        q = urllib.parse.quote(variant)
        url = f"https://api.openalex.org/authors?search={q}&mailto={POLITE_EMAIL}"
        oa_headers = {'User-Agent': POLITE_USER_AGENT}
        if DEFAULT_OPENALEX_API_KEY:
            oa_headers['api_key'] = DEFAULT_OPENALEX_API_KEY
        req = urllib.request.Request(url, headers=oa_headers)

        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    results = data.get('results', [])
                    for cand in results[:10]:
                        cid = cand.get('id') or ''
                        if not cid or cid in seen_ids:
                            continue
                        seen_ids.add(cid)

                        dname = str(cand.get('display_name') or '')
                        name_sim = max(fuzz.token_sort_ratio(v, dname) for v in name_variants)
                        if name_sim < 70:
                            continue

                        insts = [
                            (a.get('institution') or {}).get('display_name')
                            for a in (cand.get('affiliations') or [])
                            if isinstance(a, dict) and (a.get('institution') or {}).get('display_name')
                        ]
                        inst_str = ' '.join(insts).lower()
                        has_kse = any(k in inst_str for k in KSE_INSTITUTION_KEYWORDS)
                        has_partner = any(p in inst_str for p in PARTNER_INSTITUTION_KEYWORDS)

                        has_work_match = False
                        matched_work = None
                        if known_works:
                            c_auth_id = cid.split('/')[-1]
                            try:
                                w_url = f"https://api.openalex.org/works?filter=author.id:{c_auth_id}&per_page=10&mailto={POLITE_EMAIL}"
                                w_req = urllib.request.Request(w_url, headers=oa_headers)
                                with urllib.request.urlopen(w_req, timeout=6) as w_resp:
                                    w_data = json.loads(w_resp.read().decode())
                                    for w_item in (w_data.get('results') or []):
                                        w_title = str(w_item.get('title') or '')
                                        for kw in known_works:
                                            if match_publication_title(kw, w_title, threshold=75):
                                                has_work_match = True
                                                matched_work = kw
                                                break
                                        if has_work_match:
                                            break
                            except Exception:
                                pass

                        score = name_sim + (50 if has_kse else (25 if has_partner else 0))
                        if has_work_match:
                            score += 200

                        candidates.append((score, has_kse or has_work_match, cand, insts, matched_work))
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    break
                time.sleep(0.5 * (attempt + 1))
            except Exception:
                time.sleep(0.5 * (attempt + 1))

        # Early exit if a verified KSE author or ground-truth work author is found
        if any(c[0] >= 140 for c in candidates):
            break

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[1], x[0]), reverse=True)
    best_score, has_kse, best, insts, matched_work = candidates[0]

    author_id = (best.get('id') or '').split('/')[-1]
    sample_works = []
    if author_id:
        works_url = f"https://api.openalex.org/works?filter=author.id:{author_id}&per_page=3&mailto={POLITE_EMAIL}"
        wreq = urllib.request.Request(works_url, headers=oa_headers)
        try:
            with urllib.request.urlopen(wreq, timeout=8) as wresp:
                wdata = json.loads(wresp.read().decode())
                sample_works = [str(w.get('title') or '') for w in (wdata.get('results') or []) if isinstance(w, dict) and w.get('title')]
        except Exception:
            pass

    stats = best.get('summary_stats') or {}
    return {
        'openalex_id': best.get('id'),
        'display_name': best.get('display_name'),
        'orcid': best.get('orcid'),
        'affiliations': insts,
        'has_kse_affiliation': has_kse,
        'works_count': best.get('works_count', 0),
        'cited_by_count': best.get('cited_by_count', 0),
        'h_index': stats.get('h_index', 0),
        'sample_works': sample_works,
        'matched_work': matched_work
    }

# ==============================================================================
# 4. DIRECT ORCID API (STRICT HOMONYM PROTECTION)
# ==============================================================================
def query_orcid(
    name_variants: List[str],
    known_works: Optional[List[str]] = None
) -> Optional[Dict]:
    """Queries ORCID Public API with strict surname, given name, and optional publication matching."""
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
                for cand in (results or [])[:15]:
                    cand_given = str(cand.get('given-names') or '')
                    cand_family = str(cand.get('family-names') or '')
                    raw_insts = cand.get('institution-name') or []
                    cand_insts = [str(x) for x in raw_insts if x]

                    f_sim = max(
                        fuzz.ratio(v_family.lower(), cand_family.lower()),
                        fuzz.ratio(v_given.lower(), cand_family.lower())
                    )
                    # Check phonetic surname match (e.g. Trehub <-> Tregub)
                    if (
                        (v_family and cand_family and normalize_phonetic_surname(v_family) == normalize_phonetic_surname(cand_family)) or
                        (v_given and cand_family and normalize_phonetic_surname(v_given) == normalize_phonetic_surname(cand_family))
                    ):
                        f_sim = max(f_sim, 95)

                    g_sim = max(
                        fuzz.ratio(v_given.lower(), cand_given.lower()),
                        fuzz.token_set_ratio(v_given.lower(), cand_given.lower()),
                        fuzz.ratio(v_family.lower(), cand_given.lower())
                    )

                    # Strict threshold: surname >= 85, given name >= 70
                    if f_sim >= 85 and g_sim >= 70:
                        inst_str = ' '.join(cand_insts).lower()
                        has_kse = any(k in inst_str for k in KSE_INSTITUTION_KEYWORDS)
                        score = f_sim + g_sim + (50 if has_kse else 0)

                        cand_work_matched = None
                        if known_works:
                            c_id = cand.get('orcid-id')
                            if c_id:
                                c_works = fetch_orcid_works(c_id)
                                for kw in known_works:
                                    for cw in c_works:
                                        if match_publication_title(kw, cw, threshold=75):
                                            cand_work_matched = kw
                                            score += 250
                                            break
                                    if cand_work_matched:
                                        break

                        if score > best_score:
                            best_score = score
                            best_match = {
                                'orcid_id': cand.get('orcid-id'),
                                'orcid_url': f"https://orcid.org/{cand.get('orcid-id')}",
                                'name_in_orcid': f"{cand_given} {cand_family}".strip(),
                                'other_names': cand.get('other-name', []),
                                'institutions': cand_insts,
                                'matched_work': cand_work_matched
                            }
                            if has_kse or cand_work_matched:
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
                        clean_title = re.sub(r'\s*-\s*.*?(?:Google|Scholar|Академ).*', '', clean_title, flags=re.IGNORECASE).strip()
                        snippet = str(item.get("snippet") or "").replace('\n', ' ')

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
                print(f"  [Google CSE Notice]: HTTP 403 - {err_data.get('message', 'Quota or key error')}", file=sys.stderr)
                return None
            else:
                print(f"  [Google CSE Notice]: HTTP {resp.status_code}", file=sys.stderr)
        except Exception as e:
            print(f"  [Google CSE Error for {variant}]: {e}", file=sys.stderr)
            continue

    return None

def search_google_scholar_serper(
    name_variants: List[str],
    serper_key: Optional[str] = None,
    known_works: Optional[List[str]] = None,
    canonical_name: Optional[str] = None,
    is_gt_verified: bool = False
) -> Optional[Dict]:
    """Finds Google Scholar profile using Serper.dev (2,500 Free Queries, strictly <= 1 query consumed per person)."""
    serper_key, _ = resolve_api_keys(serper_key=serper_key)
    if not serper_key:
        return None

    # Priority: Query canonical international name if available, else best transliteration
    if canonical_name:
        target_query = canonical_name.strip()
        query_str = f'site:scholar.google.com/citations "{target_query}"'
    else:
        top_lat = [v for v in name_variants if not any(ord(c) > 127 for c in v)]
        target_query = top_lat[0] if top_lat else (name_variants[0] if name_variants else "")
        if not target_query:
            return None
        # If alternative latin transliteration exists (e.g. Ivan Homza vs Ivan Gomza), combine with OR in single query
        alt_variant = None
        for v in top_lat[1:]:
            v_parts = v.split()
            t_parts = target_query.split()
            if len(v_parts) == len(t_parts) and v.lower() != target_query.lower() and v_parts[0].lower() == t_parts[0].lower():
                alt_variant = v
                break
        if alt_variant:
            query_str = f'site:scholar.google.com/citations "{target_query}" OR "{alt_variant}"'
        else:
            query_str = f'site:scholar.google.com/citations "{target_query}"'

    all_check_variants = ([canonical_name] if canonical_name else []) + name_variants

    candidates = []
    try:
        payload = {'q': query_str}
        r = safe_serper_post(payload, api_key=serper_key, timeout=15, max_retries=2)
        if r and r.status_code == 200:
            data = r.json()
            for item in data.get('organic', []):
                link = item.get('link', '')
                if 'citations?user=' not in link:
                    continue
                # Hardening 1: Ignore junk list_works URLs
                if 'view_op=list_works' in link:
                    continue
                m = re.search(r'user=([a-zA-Z0-9_\-]+)', link)
                if not m:
                    continue
                uid = m.group(1)
                raw_title = str(item.get('title') or '')
                clean_title = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', raw_title)
                clean_title = re.sub(r'\s*-\s*.*?(?:Google|Scholar|Академ).*', '', clean_title, flags=re.IGNORECASE).strip()
                snippet = str(item.get('snippet') or '').replace('\n', ' ')

                # Hardening 2: Ignore junk Google pages
                if not clean_title or clean_title.lower() in ('title', 'google scholar', 'user profile') or 'no information is available' in snippet.lower():
                    continue

                # Multi-alias splitting rule: split on [,/;|]
                sub_names = [s.strip() for s in re.split(r'[,/;|]', clean_title) if s.strip()]
                name_sim = max(fuzz.token_sort_ratio(v, sub) for v in all_check_variants for sub in (sub_names or [clean_title]))

                # Anti-homonym check
                if name_sim < 60:
                    continue

                is_kse = (
                    any(k in snippet.lower() for k in KSE_INSTITUTION_KEYWORDS) or
                    any(k in clean_title.lower() for k in KSE_INSTITUTION_KEYWORDS) or
                    'kse.org.ua' in snippet.lower()
                )
                is_partner = (
                    any(p in snippet.lower() for p in PARTNER_INSTITUTION_KEYWORDS) or
                    any(p in clean_title.lower() for p in PARTNER_INSTITUTION_KEYWORDS)
                )

                has_gt_work = False
                matched_art = None
                if known_works and name_sim >= 65:
                    for kw in known_works:
                        if match_publication_title(kw, snippet, threshold=60) or normalize_title(kw) in normalize_title(snippet):
                            has_gt_work = True
                            matched_art = kw
                            name_sim = 100
                            break

                # If identity is already verified by ground truth or publication anchor, waive external affiliation penalty (GEMINI.md Rule 3.A)
                is_gt = has_gt_work or is_gt_verified
                if is_kse or is_gt:
                    match_score = min(name_sim + 25, 100) if not is_gt else 100
                    is_kse_flag = True
                elif is_partner:
                    match_score = min(name_sim + 10, 100)
                    is_kse_flag = False
                else:
                    match_score = name_sim
                    is_kse_flag = False

                if (is_kse_flag and match_score >= 75) or (is_partner and match_score >= 75) or (match_score >= 85):
                    cited_by = None
                    cited_m = re.search(r'[Cc]ited by\s*([\d,]+)|[Цц]итуван[ья][\s:]*([\d,]+)|[Цц]итат[\s:]*([\d,]+)', snippet)
                    if cited_m:
                        for grp in cited_m.groups():
                            if grp:
                                try:
                                    cited_by = int(grp.replace(',', ''))
                                    break
                                except ValueError:
                                    pass

                    cand_obj = {
                        'scholar_id': uid,
                        'profile_url': f"https://scholar.google.com/citations?user={uid}&hl=en",
                        'name': clean_title,
                        'affiliations': snippet[:160],
                        'email_verification': 'kse.org.ua' if 'kse.org.ua' in snippet.lower() else ('Verified' if is_kse else 'Unverified'),
                        'is_kse_affiliated': is_kse_flag,
                        'ground_truth_matched': is_gt,
                        'matched_article': matched_art,
                        'cited_by': cited_by,
                        'source': 'Serper.dev (Verified Ground Truth Publication)' if is_gt else 'Serper.dev (Google Scholar)',
                        'match_score': min(match_score, 100)
                    }
                    # EARLY EXIT: Save credits immediately if high-confidence KSE/ground-truth profile found
                    if is_kse_flag and match_score >= 85:
                        return cand_obj
                    if match_score >= 90 and is_kse_flag:
                        return cand_obj
                    candidates.append(cand_obj)
        elif r and r.status_code == 401:
            return {
                'error': True,
                'error_type': 'API_KEY_INVALID',
                'message': 'Serper.dev access denied (HTTP 401: Invalid API key)'
            }
        elif r and r.status_code == 429:
            return {
                'error': True,
                'error_type': 'QUOTA_EXCEEDED',
                'message': 'Serper.dev search quota exceeded (HTTP 429)'
            }
    except Exception:
        pass

    if candidates:
        candidates.sort(key=lambda x: (x.get('is_kse_affiliated', False), x.get('match_score', 0)), reverse=True)
        return candidates[0]
    return None

def search_google_scholar(
    name_variants: List[str],
    sample_works: List[str] = None,
    google_api_key: Optional[str] = None,
    google_cse_cx: Optional[str] = None,
    serpapi_key: Optional[str] = None,
    serper_key: Optional[str] = None,
    known_works: Optional[List[str]] = None,
    canonical_name: Optional[str] = None,
    is_gt_verified: bool = False
) -> Optional[Dict]:
    """Finds Google Scholar profile URL across Serper.dev (Free Tier), Google CSE, and SerpAPI."""
    serper_key, serpapi_key = resolve_api_keys(serper_key=serper_key, serpapi_key=serpapi_key)

    # 1. Tier 1: Serper.dev (Strictly <= 1 query / person, zero scraping ban risk)
    serper_error = None
    if serper_key:
        serper_res = search_google_scholar_serper(
            name_variants,
            serper_key=serper_key,
            known_works=known_works,
            canonical_name=canonical_name,
            is_gt_verified=is_gt_verified
        )
        if serper_res:
            if not serper_res.get('error'):
                return serper_res
            serper_error = serper_res
        # RULE 3.C: Strictly <= 1 Serper query per faculty member. Budget exhausted.
        serper_key = None

    # 2. Tier 2: Direct ground-truth article co-citation lookup if known_works provided and SerpAPI available
    if known_works and (serpapi_key or serper_key):
        target_author = canonical_name or name_variants[0]
        for kw in known_works[:2]:
            art_cand = search_scholar_by_article(
                target_author,
                kw,
                name_variants=name_variants,
                serpapi_key=serpapi_key,
                serper_key=serper_key
            )
            if art_cand:
                return art_cand

    # 3. Tier 3: Google Programmable Search Engine (100 Free queries/day)
    cse_result = search_google_scholar_cse(name_variants, api_key=google_api_key, cx=google_cse_cx)
    if cse_result:
        return cse_result

    # 4. Tier 4: SerpAPI with Early Exit (Paid / Free Monthly Credits)
    if not serpapi_key:
        if serper_error:
            return serper_error
        if serper_key:
            return None
        return {
            'error': True,
            'error_type': 'API_KEY_MISSING',
            'message': 'API key not configured (set SERPER_API_KEY or SERPAPI_API_KEY in .env or pass --api-key)'
        }

    api_candidates = []
    api_error = None

    for variant in name_variants[:6]:
        try:
            params = {
                'engine': 'google_scholar',
                'q': variant,
                'api_key': serpapi_key
            }
            r = safe_serpapi_get(params, timeout=25, max_retries=2)
            if r and r.status_code == 200:
                data = r.json()
                if "error" in data:
                    err_msg = data["error"]
                    if "run out of searches" in err_msg.lower() or "quota" in err_msg.lower():
                        api_error = {
                            'error': True,
                            'error_type': 'QUOTA_EXCEEDED',
                            'message': f'SerpAPI quota exceeded: {err_msg}'
                        }
                    else:
                        api_error = {
                            'error': True,
                            'error_type': 'API_ERROR',
                            'message': f'SerpAPI error: {err_msg}'
                        }
                    break

                authors = (data.get('profiles') or {}).get('authors', [])
                for a in (authors or []):
                    cand_name = str(a.get('name') or '')
                    cand_affil = str(a.get('affiliations') or '')
                    email = str(a.get('email') or '')

                    # Split multiple author aliases in Scholar name (e.g. 'Ігор Сердюк, Igor Serdiuk')
                    sub_names = [s.strip() for s in re.split(r'[,/;|]', cand_name) if s.strip()]
                    sim = max(fuzz.token_sort_ratio(v, sub) for v in name_variants for sub in (sub_names or [cand_name]))
                    is_kse = (
                        any(k in cand_affil.lower() for k in KSE_INSTITUTION_KEYWORDS) or
                        'kse.org.ua' in email.lower()
                    )
                    is_partner = any(p in cand_affil.lower() for p in PARTNER_INSTITUTION_KEYWORDS)

                    # Check if candidate has ground-truth work
                    has_gt_work = False
                    if known_works and sim >= 70:
                        matched_art = verify_scholar_candidate_works(a.get('author_id'), known_works, serpapi_key=serpapi_key)
                        if matched_art:
                            has_gt_work = True
                            sim = 100

                    if is_kse or has_gt_work:
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
                            'is_kse_affiliated': is_kse or has_gt_work,
                            'ground_truth_matched': has_gt_work,
                            'cited_by': a.get('cited_by'),
                            'source': 'SerpAPI (Verified Ground Truth Publication)' if has_gt_work else 'SerpAPI (Google Scholar Engine)',
                            'match_score': min(sim, 100)
                        }
                        # EARLY EXIT: Save paid credits immediately if high-confidence KSE/ground-truth profile found
                        if (is_kse or has_gt_work) and sim >= 85:
                            return cand_obj
                        api_candidates.append(cand_obj)
            elif r and r.status_code == 401:
                try:
                    err_msg = r.json().get('error', 'Invalid API key')
                except Exception:
                    err_msg = 'Invalid API key'
                api_error = {
                    'error': True,
                    'error_type': 'API_KEY_INVALID',
                    'message': f'SerpAPI access denied (HTTP 401: {err_msg})'
                }
                break
            elif r and r.status_code == 403:
                try:
                    err_msg = r.json().get('error', 'Forbidden / Access denied')
                except Exception:
                    err_msg = 'Forbidden'
                api_error = {
                    'error': True,
                    'error_type': 'ACCESS_FORBIDDEN',
                    'message': f'SerpAPI access forbidden (HTTP 403: {err_msg})'
                }
                break
            elif r and r.status_code == 429:
                try:
                    err_msg = r.json().get('error', 'Quota exceeded')
                except Exception:
                    err_msg = 'Quota exceeded'
                api_error = {
                    'error': True,
                    'error_type': 'QUOTA_EXCEEDED',
                    'message': f'SerpAPI search quota exceeded (HTTP 429: {err_msg})'
                }
                break
            elif r is not None:
                api_error = {
                    'error': True,
                    'error_type': 'API_ERROR',
                    'message': f'SerpAPI returned HTTP {r.status_code}'
                }
                break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            # Transient timeout/connection issue on this variant; record error and continue to next alias
            api_error = {
                'error': True,
                'error_type': 'NETWORK_TIMEOUT',
                'message': f'SerpAPI network timeout (read timeout): {e}'
            }
            continue
        except requests.exceptions.RequestException as e:
            api_error = {
                'error': True,
                'error_type': 'NETWORK_ERROR',
                'message': f'SerpAPI network error: {e}'
            }
            break

    if api_candidates:
        api_candidates.sort(key=lambda x: (x['is_kse_affiliated'], x['match_score']), reverse=True)
        return api_candidates[0]

    if api_error:
        return api_error

    return None

# ==============================================================================
# 6. UNIFIED DISCOVERY & VALIDATION PIPELINE
# ==============================================================================
def process_faculty_member(
    input_name: str,
    verbose: bool = True,
    serpapi_key: Optional[str] = None,
    serper_key: Optional[str] = None,
    known_works: Optional[List[str]] = None,
    known_orcid: Optional[str] = None,
    known_scholar: Optional[str] = None
) -> Dict:
    if not input_name or not input_name.strip():
        return {
            'input_name': input_name or '',
            'status': 'MISSING / NOT FOUND',
            'confidence_score': 0,
            'reasons': ['Empty or whitespace name provided'],
            'orcid': None,
            'scholar': None,
            'scholar_error': None,
            'metrics': {'h_index': 0, 'citations': 0, 'works_count': 0},
            'sample_works': []
        }

    if verbose:
        print(f"\n{'='*60}")
        print(f"PROCESSING: {input_name}")
        print(f"{'='*60}")

    clean_works = [w.strip() for w in (known_works or []) if w and w.strip()]
    variants = generate_name_variants(input_name)
    if verbose:
        print(f"  Aliases considered: {variants[:4]}")
        if clean_works:
            print(f"  Ground-truth work(s): {clean_works}")
        if known_orcid:
            print(f"  Ground-truth ORCID: {known_orcid}")
        if known_scholar:
            print(f"  Ground-truth Scholar: {known_scholar}")

    gt_reasons = []
    is_gt_verified = False
    orcid_gt_verified = False
    scholar_gt_verified = False
    canonical_name = None
    works_res = None
    discovery_steps: List[str] = []

    # =========================================================================
    # STAGE 1: Direct Ground-Truth Anchors Ingestion
    # =========================================================================
    orcid_info = None
    if known_orcid:
        orcid_info = resolve_direct_orcid(known_orcid)
        if orcid_info:
            is_gt_verified = True
            orcid_gt_verified = True
            gt_reasons.append(f"ORCID anchored directly from ground-truth input: {orcid_info.get('orcid_id')}")
            discovery_steps.append(f"Вхідний ORCID ({orcid_info.get('orcid_id')})")

    scholar_info = None
    if known_scholar:
        scholar_info = resolve_direct_scholar(known_scholar, serpapi_key=serpapi_key, serper_key=serper_key)
        if scholar_info:
            is_gt_verified = True
            scholar_gt_verified = True
            gt_reasons.append(f"Scholar anchored directly from ground-truth input: {scholar_info.get('scholar_id')}")
            discovery_steps.append(f"Вхідний Scholar ID ({scholar_info.get('scholar_id')})")

    # =========================================================================
    # STAGE 2: Priority 1 WorksResolver (OpenAlex / Crossref via DOIs & Titles)
    # =========================================================================
    alex_data = None
    sample_works = []
    if clean_works:
        discovery_steps.append(f"Публікації з бази ({len(clean_works)} робіт)")
        works_res = resolve_author_from_works(input_name, variants, clean_works)
        if works_res:
            canonical_name = works_res.get('canonical_name')
            if canonical_name and canonical_name not in variants:
                variants.insert(0, canonical_name)
            m_doi = works_res.get('matched_doi')
            if m_doi:
                discovery_steps.append(f"DOI ({m_doi}) ➔ OpenAlex Works")
            else:
                discovery_steps.append("Пошук статті ➔ OpenAlex Works")
            if canonical_name:
                discovery_steps.append(f"Канонічне ім'я ({canonical_name})")

            works_orcid = works_res.get('orcid_id')
            if works_orcid and not orcid_info:
                orcid_info = resolve_direct_orcid(works_orcid)
                if orcid_info:
                    is_gt_verified = True
                    orcid_gt_verified = True
                    m_title = works_res.get('matched_work_title') or (clean_works[0] if clean_works else 'known work')
                    gt_reasons.append(f"ORCID verified via ground-truth work: '{m_title}'")
                    discovery_steps.append(f"ORCID зі статті ({orcid_info.get('orcid_id')})")

            alex_data = {
                'h_index': works_res.get('h_index', 0),
                'cited_by_count': works_res.get('cited_by_count', 0),
                'works_count': works_res.get('works_count', 0),
                'sample_works': works_res.get('sample_works', [])
            }
            sample_works = alex_data.get('sample_works', [])

    # =========================================================================
    # STAGE 3: Priority 2 ScholarResolver (Direct -> Wikidata SPARQL -> Serper)
    # =========================================================================
    if not scholar_info and orcid_info and orcid_info.get('orcid_id'):
        scholar_info = get_scholar_from_wikidata(orcid_info['orcid_id'])
        if scholar_info:
            is_gt_verified = True
            scholar_gt_verified = True
            gt_reasons.append(f"Scholar verified via Wikidata cross-link: {scholar_info.get('scholar_id')}")
            discovery_steps.append(f"Wikidata SPARQL (ORCID ➔ Scholar: {scholar_info.get('scholar_id')})")

    if not scholar_info:
        scholar_info = search_google_scholar(
            variants,
            sample_works,
            serpapi_key=serpapi_key,
            serper_key=serper_key,
            known_works=clean_works,
            canonical_name=canonical_name,
            is_gt_verified=is_gt_verified
        )
        if scholar_info and not scholar_info.get('error'):
            engine_name = scholar_info.get('source') or "Google Scholar"
            if scholar_info.get('ground_truth_matched') or scholar_info.get('matched_article') or works_res or is_gt_verified:
                is_gt_verified = True
                scholar_gt_verified = True
                m_art = scholar_info.get('matched_article') or (clean_works[0] if clean_works else 'known work')
                gt_reasons.append(f"Scholar verified via ground-truth article match: '{m_art}'")
                discovery_steps.append(f"{engine_name} (за статтею ➔ {scholar_info.get('scholar_id')})")
            else:
                discovery_steps.append(f"{engine_name} (за ім'ям ➔ {scholar_info.get('scholar_id')})")

    # =========================================================================
    # STAGE 4: Priority 3 OrcidResolver (Direct -> Wikidata SPARQL -> OpenAlex/ORCID)
    # =========================================================================
    if not orcid_info and scholar_info and scholar_info.get('scholar_id'):
        orcid_wiki = get_orcid_from_wikidata(scholar_info['scholar_id'])
        if orcid_wiki:
            direct_data = resolve_direct_orcid(orcid_wiki['orcid_id'])
            if direct_data:
                orcid_info = direct_data
                orcid_info['source'] = 'Wikidata SPARQL Bridge (Free Tier 1)'
                orcid_info['is_wikidata_crosslink'] = True
            else:
                orcid_info = orcid_wiki
            is_gt_verified = True
            orcid_gt_verified = True
            gt_reasons.append(f"ORCID verified via Wikidata cross-link: {orcid_info.get('orcid_id')}")
            discovery_steps.append(f"Wikidata SPARQL (Scholar ➔ ORCID: {orcid_info.get('orcid_id')})")

    if not orcid_info:
        if not alex_data:
            alex_data = query_openalex(variants, known_works=clean_works)
            if alex_data and clean_works and not alex_data.get('matched_work') and not alex_data.get('has_kse_affiliation'):
                alex_data = None
            sample_works = alex_data.get('sample_works', []) if alex_data else []

        if alex_data and alex_data.get('orcid'):
            candidate_orcid = alex_data['orcid'].split('/')[-1]
            verified_alex_orcid = resolve_direct_orcid(candidate_orcid)
            if verified_alex_orcid:
                orcid_insts = [str(x).lower() for x in (verified_alex_orcid.get('institutions') or [])]
                has_kse_cand = any(any(k in inst for k in KSE_INSTITUTION_KEYWORDS) for inst in orcid_insts)
                alex_matched_work = alex_data.get('matched_work')
                if not alex_matched_work and clean_works:
                    c_works = fetch_orcid_works(candidate_orcid)
                    for kw in clean_works:
                        for cw in c_works:
                            if match_publication_title(kw, cw, threshold=75):
                                alex_matched_work = kw
                                break
                        if alex_matched_work:
                            break

                if alex_matched_work:
                    is_gt_verified = True
                    orcid_gt_verified = True
                    orcid_info = {
                        'orcid_id': candidate_orcid,
                        'orcid_url': alex_data['orcid'],
                        'name_in_orcid': verified_alex_orcid.get('name_in_orcid', ''),
                        'institutions': verified_alex_orcid.get('institutions', []),
                        'source': 'OpenAlex (Ground Truth Publication Match)',
                        'matched_work': alex_matched_work
                    }
                    gt_reasons.append(f"ORCID verified via ground-truth work: '{alex_matched_work}'")
                    discovery_steps.append(f"OpenAlex (співпадіння статті ➔ ORCID {candidate_orcid})")
                elif clean_works:
                    if has_kse_cand:
                        orcid_info = {
                            'orcid_id': candidate_orcid,
                            'orcid_url': alex_data['orcid'],
                            'name_in_orcid': verified_alex_orcid.get('name_in_orcid', ''),
                            'institutions': verified_alex_orcid.get('institutions', []),
                            'source': 'OpenAlex'
                        }
                        discovery_steps.append(f"OpenAlex (KSE афіліація ➔ ORCID {candidate_orcid})")
                    else:
                        orcid_info = None
                else:
                    orcid_info = {
                        'orcid_id': candidate_orcid,
                        'orcid_url': alex_data['orcid'],
                        'name_in_orcid': verified_alex_orcid.get('name_in_orcid', ''),
                        'institutions': verified_alex_orcid.get('institutions', []),
                        'source': 'OpenAlex'
                    }
                    discovery_steps.append(f"OpenAlex (авторський пошук ➔ ORCID {candidate_orcid})")

        if not orcid_info:
            direct_orcid = query_orcid(variants, known_works=clean_works)
            if direct_orcid:
                d_insts = [str(x).lower() for x in (direct_orcid.get('institutions') or [])]
                d_has_kse = any(any(k in inst for k in KSE_INSTITUTION_KEYWORDS) for inst in d_insts)
                d_has_partner = any(any(k in inst for k in PARTNER_INSTITUTION_KEYWORDS) for inst in d_insts)
                if direct_orcid.get('matched_work'):
                    is_gt_verified = True
                    orcid_gt_verified = True
                    direct_orcid['source'] = 'ORCID API (Ground Truth Publication Match)'
                    gt_reasons.append(f"ORCID verified via ground-truth work: '{direct_orcid['matched_work']}'")
                    orcid_info = direct_orcid
                    discovery_steps.append(f"ORCID API (співпадіння статті ➔ {direct_orcid.get('orcid_id')})")
                elif clean_works:
                    if d_has_kse or d_has_partner:
                        direct_orcid['source'] = 'ORCID API (Direct search)'
                        orcid_info = direct_orcid
                        discovery_steps.append(f"ORCID API (KSE/партнерська афіліація ➔ {direct_orcid.get('orcid_id')})")
                    else:
                        orcid_info = None
                else:
                    # Name-only search without works:
                    # If candidate explicitly lists institutions but NONE are KSE or partner, reject as external homonym
                    if d_insts and not (d_has_kse or d_has_partner):
                        orcid_info = None
                    else:
                        direct_orcid['source'] = 'ORCID API (Direct search)'
                        orcid_info = direct_orcid
                        discovery_steps.append(f"ORCID API (пошук за ім'ям ➔ {direct_orcid.get('orcid_id')})")
    elif not alex_data:
        alex_data = query_openalex(variants, known_works=clean_works)
        sample_works = alex_data.get('sample_works', []) if alex_data else []

    scholar_error = None
    scholar_profile = None
    if scholar_info:
        if scholar_info.get('error'):
            scholar_error = scholar_info.get('message')
        else:
            scholar_profile = scholar_info

    # 3. Affiliation checks for Disambiguation & Anti-Homonym Protection
    raw_orcid_insts = (orcid_info.get('institutions') or []) if orcid_info else []
    orcid_insts = [str(inst) for inst in raw_orcid_insts if inst]
    has_kse_orcid = bool(orcid_info and any(any(k in inst.lower() for k in KSE_INSTITUTION_KEYWORDS) for inst in orcid_insts))
    has_kse_scholar = bool(scholar_profile and (
        any(k in (scholar_profile.get('affiliations') or '').lower() for k in KSE_INSTITUTION_KEYWORDS) or
        'kse.org.ua' in (scholar_profile.get('email_verification') or '').lower() or
        scholar_profile.get('ground_truth_matched') or
        scholar_profile.get('is_wikidata_crosslink')
    ))
    has_kse_alex = bool(alex_data and alex_data.get('has_kse_affiliation'))
    has_any_kse = has_kse_orcid or has_kse_scholar or has_kse_alex or is_gt_verified

    has_partner_orcid = bool(orcid_info and any(any(k in inst.lower() for k in PARTNER_INSTITUTION_KEYWORDS) for inst in orcid_insts))
    has_partner_scholar = bool(scholar_profile and any(k in (scholar_profile.get('affiliations') or '').lower() for k in PARTNER_INSTITUTION_KEYWORDS))
    has_any_partner = has_partner_orcid or has_partner_scholar

    # Discard non-KSE/non-partner Scholar profile if NOT a ground truth match or verified Wikidata crosslink
    if scholar_profile and not (has_kse_scholar or has_partner_scholar or is_gt_verified or scholar_profile.get('is_wikidata_crosslink')):
        scholar_profile = None

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

    if scholar_profile:
        confidence += 35
        if has_kse_scholar:
            confidence += 15
            reasons.append(f"Scholar profile matched ({scholar_profile.get('match_score', 100)}% with KSE verification)")
        elif has_partner_scholar:
            confidence += 5
            reasons.append(f"Scholar profile matched ({scholar_profile.get('match_score', 100)}% with partner institution)")
        else:
            reasons.append(f"Scholar profile matched ({scholar_profile.get('match_score', 100)}%)")
    elif scholar_error:
        reasons.append(f"Scholar lookup skipped: {scholar_error}")

    if has_kse_alex:
        confidence += 10
        reasons.append("KSE affiliation verified in OpenAlex")

    # Status Determination:
    if orcid_gt_verified and scholar_gt_verified:
        status = "VERIFIED (GROUND TRUTH MATCH)"
        confidence = 100
        reasons = gt_reasons + reasons
    elif is_gt_verified:
        if orcid_info and scholar_profile:
            status = "VERIFIED (GROUND TRUTH MATCH)"
            confidence = 100
            reasons = gt_reasons + reasons
        elif scholar_gt_verified and not orcid_info:
            status = "PARTIAL MATCH (SCHOLAR VERIFIED, ORCID NOT FOUND)"
            confidence = 85
            reasons = gt_reasons + reasons
        elif orcid_gt_verified and not scholar_profile:
            status = "PARTIAL MATCH (ORCID VERIFIED, SCHOLAR NOT FOUND)"
            confidence = 85
            reasons = gt_reasons + reasons
        else:
            status = "VERIFIED (GROUND TRUTH MATCH)"
            confidence = 100
            reasons = gt_reasons + reasons
    elif confidence >= 80 and (has_any_kse or has_any_partner):
        status = "VERIFIED (AUTO)"
    elif confidence >= 40:
        if not (has_any_kse or has_any_partner):
            status = "NEEDS REVIEW (HOMONYM RISK / UNVERIFIED AFFILIATION)"
        else:
            if scholar_error:
                status = "PARTIAL MATCH (SCHOLAR API ERROR)"
            elif has_kse_orcid and not scholar_profile:
                status = "PARTIAL MATCH (ORCID VERIFIED, SCHOLAR NOT FOUND)"
            elif has_kse_scholar and not orcid_info:
                status = "PARTIAL MATCH (SCHOLAR VERIFIED, ORCID NOT FOUND)"
            else:
                status = "PARTIAL MATCH (NEEDS REVIEW)"
    else:
        if scholar_error:
            status = "ERROR (SCHOLAR API KEY ERROR)"
        else:
            status = "MISSING / NOT FOUND"

    if not discovery_steps:
        discovery_steps.append("Пошук за ПІБ (публічних профілів не виявлено)")
    discovery_path = " ➔ ".join(discovery_steps)

    result = {
        'input_name': input_name,
        'status': status,
        'confidence_score': confidence,
        'discovery_path': discovery_path,
        'discovery_steps': discovery_steps,
        'reasons': reasons,
        'orcid': orcid_info,
        'scholar': scholar_profile,
        'scholar_error': scholar_error,
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
        print(f"  [DISCOVERY PATH]: {discovery_path}")
        if orcid_info:
            print(f"  [ORCID]: {orcid_info.get('orcid_url')} ({orcid_info.get('source')})")
        else:
            print(f"  [ORCID]: Not found")

        if scholar_profile:
            print(f"  [SCHOLAR]: {scholar_profile.get('profile_url')} ({scholar_profile.get('source')})")
            affil = scholar_profile.get('affiliations') or 'N/A'
            print(f"             Affiliation: {affil[:70]} | Cited: {scholar_profile.get('cited_by')}")
        elif scholar_error:
            print(f"  [SCHOLAR]: ERROR — {scholar_error}")
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
    parser.add_argument('-w', '--work', action='append', dest='known_works', help="Known scientific publication title (can be repeated).")
    parser.add_argument('--orcid', dest='known_orcid', help="Known ORCID iD or URL.")
    parser.add_argument('--scholar', dest='known_scholar', help="Known Google Scholar user ID or URL.")
    parser.add_argument('--api-key', dest='api_key', help="SerpAPI or Serper.dev key for Google Scholar lookup.")
    parser.add_argument('--serper-key', dest='serper_key', help="Serper.dev API key for Google Scholar lookup (2,500 free queries).")
    parser.add_argument('--benchmark', '--demo', action='store_true', help="Run benchmark on the 9 original test faculty.")

    args = parser.parse_args()

    if args.serper_key:
        os.environ['SERPER_API_KEY'] = args.serper_key
    if args.api_key:
        if len(args.api_key.strip()) == 40 and not args.serper_key:
            os.environ['SERPER_API_KEY'] = args.api_key
        else:
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
        content = ""
        for enc in ('utf-8-sig', 'utf-8', 'cp1251', 'latin-1'):
            try:
                with open(args.file, 'r', encoding=enc) as f:
                    content = f.read().strip()
                break
            except UnicodeDecodeError:
                continue

        if content.startswith('[') and content.endswith(']'):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, str) and item.strip():
                            names_to_process.append(item.strip())
                        elif isinstance(item, dict):
                            name_val = item.get('name') or item.get('faculty_name') or item.get('full_name')
                            if name_val and str(name_val).strip():
                                names_to_process.append(str(name_val).strip())
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
        res = process_faculty_member(
            name,
            verbose=verbose,
            serpapi_key=args.api_key,
            serper_key=args.serper_key,
            known_works=args.known_works,
            known_orcid=args.known_orcid,
            known_scholar=args.known_scholar
        )
        results.append(res)

    output_data = results[0] if len(results) == 1 else results
    if args.json:
        print(json.dumps(output_data, indent=2, ensure_ascii=False))
    elif not args.quiet:
        print(f"\n{'='*60}")
        print(f"PROCESSED: {len(results)} faculty member(s)")
        print(f"{'='*60}")

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        if not args.json and not args.quiet:
            print(f"Results successfully saved to {args.output}")

if __name__ == '__main__':
    main()
