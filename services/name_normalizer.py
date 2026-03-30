import difflib
import re
from typing import Iterable, Optional

MATCH_SEPARATORS = r"\s+(?:vs\.?|v\.?|против)\s+|\s*-\s*"

CYRILLIC_TO_LATIN = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ы": "y", "э": "e", "ю": "yu", "я": "ya", "ъ": "", "ь": "",
})

GENERIC_TOKENS = {
    "fc", "cf", "hc", "sc", "fk", "bk", "club", "team", "esports", "esport",
}

COMMON_ALIASES = {
    "автомибилист": "Автомобилист",
    "автомобилист екатеринбург": "Автомобилист",
    "салават": "Салават Юлаев",
    "салават юлаев уфа": "Салават Юлаев",
    "ман юнайтед": "Manchester United",
    "man utd": "Manchester United",
    "man united": "Manchester United",
    "man city": "Manchester City",
    "psg": "Paris Saint-Germain",
    "natus vincere": "Navi",
}

ESPORTS_TEAM_ALIASES = {
    "navi": "Navi",
    "na vi": "Navi",
    "natus vincere": "Navi",
    "team liquid": "Team Liquid",
    "liquid": "Team Liquid",
    "team secret": "Team Secret",
    "secret": "Team Secret",
    "team spirit": "Team Spirit",
    "spirit": "Team Spirit",
    "g2": "G2 Esports",
    "g2 esports": "G2 Esports",
    "vitality": "Team Vitality",
    "team vitality": "Team Vitality",
    "faze": "FaZe Clan",
    "faze clan": "FaZe Clan",
    "fnatic": "Fnatic",
    "paper rex": "Paper Rex",
    "prx": "Paper Rex",
    "sentinels": "Sentinels",
    "sen": "Sentinels",
    "evil geniuses": "Evil Geniuses",
    "eg": "Evil Geniuses",
    "gen g": "Gen.G",
    "geng": "Gen.G",
    "gen.g": "Gen.G",
    "t1": "T1",
    "skt": "T1",
    "skt t1": "T1",
    "jdg": "JD Gaming",
    "jd gaming": "JD Gaming",
    "blg": "Bilibili Gaming",
    "bilibili gaming": "Bilibili Gaming",
    "drx": "DRX",
    "edg": "EDward Gaming",
    "edward gaming": "EDward Gaming",
    "tes": "Top Esports",
    "top esports": "Top Esports",
    "falcons": "Team Falcons",
    "team falcons": "Team Falcons",
}

TOURNAMENT_ALIASES = {
    "ti": "The International",
    "the international": "The International",
    "dreamleague": "DreamLeague",
    "esl pro league": "ESL Pro League",
    "iem": "Intel Extreme Masters",
    "vct": "Valorant Champions Tour",
    "valorant champions tour": "Valorant Champions Tour",
    "masters": "Valorant Masters",
    "valorant masters": "Valorant Masters",
    "champions": "Valorant Champions",
    "valorant champions": "Valorant Champions",
    "lck": "League of Legends Champions Korea",
    "lec": "League of Legends EMEA Championship",
    "lpl": "League of Legends Pro League",
    "lcs": "League Championship Series",
    "msi": "Mid-Season Invitational",
    "worlds": "League of Legends World Championship",
    "world championship": "League of Legends World Championship",
}

COMMON_ALIASES.update(ESPORTS_TEAM_ALIASES)
COMMON_ALIASES.update(TOURNAMENT_ALIASES)

CANONICAL_SEARCH_VARIANTS = {
    "Navi": ["Navi", "Natus Vincere"],
    "Team Liquid": ["Team Liquid", "Liquid"],
    "Team Secret": ["Team Secret", "Secret"],
    "Team Spirit": ["Team Spirit", "Spirit"],
    "G2 Esports": ["G2 Esports", "G2"],
    "Team Vitality": ["Team Vitality", "Vitality"],
    "FaZe Clan": ["FaZe Clan", "FaZe"],
    "Paper Rex": ["Paper Rex", "PRX"],
    "Sentinels": ["Sentinels", "SEN"],
    "Gen.G": ["Gen.G", "Gen G", "GenG"],
    "T1": ["T1", "SKT T1", "SKT"],
    "JD Gaming": ["JD Gaming", "JDG"],
    "Bilibili Gaming": ["Bilibili Gaming", "BLG"],
    "EDward Gaming": ["EDward Gaming", "EDG"],
    "Top Esports": ["Top Esports", "TES"],
    "The International": ["The International", "TI"],
    "Valorant Champions Tour": ["Valorant Champions Tour", "VCT"],
    "Valorant Masters": ["Valorant Masters", "Masters"],
    "Valorant Champions": ["Valorant Champions", "Champions"],
    "League of Legends Champions Korea": ["League of Legends Champions Korea", "LCK"],
    "League of Legends EMEA Championship": ["League of Legends EMEA Championship", "LEC"],
    "League of Legends Pro League": ["League of Legends Pro League", "LPL"],
    "League Championship Series": ["League Championship Series", "LCS"],
    "Mid-Season Invitational": ["Mid-Season Invitational", "MSI"],
    "League of Legends World Championship": ["League of Legends World Championship", "Worlds"],
}


def split_match_text(match_text: str) -> list[str]:
    parts = re.split(MATCH_SEPARATORS, match_text, flags=re.I)
    return [part.strip() for part in parts if part and part.strip()]


def transliterate_text(text: str) -> str:
    transliterated = text.lower().translate(CYRILLIC_TO_LATIN)
    return re.sub(r"\s+", " ", transliterated).strip()


def get_search_variants(text: str, discipline: Optional[str] = None, limit: int = 4) -> list[str]:
    original = text.strip()
    if not original:
        return []

    resolution = resolve_entity_name(original, discipline=discipline)
    candidates = [original, resolution["corrected"]]
    canonical_variants = CANONICAL_SEARCH_VARIANTS.get(resolution["corrected"], [])
    candidates.extend(canonical_variants)

    transliterated_original = transliterate_text(original)
    transliterated_corrected = transliterate_text(resolution["corrected"])
    candidates.extend([transliterated_original, transliterated_corrected])

    deduplicated: list[str] = []
    seen = set()
    for candidate in candidates:
        value = re.sub(r"\s+", " ", candidate).strip()
        if not value:
            continue
        normalized = value.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(value)
        if len(deduplicated) >= limit:
            break
    return deduplicated


def expand_context_terms(context_terms: Optional[str], discipline: Optional[str] = None) -> list[str]:
    if not context_terms:
        return []

    original = re.sub(r"\s+", " ", context_terms).strip()
    if not original:
        return []

    normalized = normalize_entity_name(original)
    expanded = [original]
    if normalized in TOURNAMENT_ALIASES:
        expanded.append(TOURNAMENT_ALIASES[normalized])

    tokens = original.split()
    rebuilt_tokens = []
    changed = False
    for token in tokens:
        normalized_token = normalize_entity_name(token)
        replacement = TOURNAMENT_ALIASES.get(normalized_token)
        if replacement:
            rebuilt_tokens.append(replacement)
            changed = True
        else:
            rebuilt_tokens.append(token)
    if changed:
        expanded.append(" ".join(rebuilt_tokens))

    deduplicated: list[str] = []
    seen = set()
    for item in expanded:
        value = re.sub(r"\s+", " ", item).strip()
        normalized_value = value.lower()
        if not value or normalized_value in seen:
            continue
        seen.add(normalized_value)
        deduplicated.append(value)
    return deduplicated[:2]


def normalize_entity_name(name: str) -> str:
    cleaned = name.strip().lower().replace("ё", "е")
    cleaned = re.sub(r"[\"'`«»()\[\]{}]", " ", cleaned)
    cleaned = re.sub(r"[^\w\sа-я-]", " ", cleaned, flags=re.UNICODE)
    cleaned = cleaned.replace("_", " ")
    tokens = [token for token in cleaned.split() if token not in GENERIC_TOKENS]
    return " ".join(tokens)


def _similarity(left: str, right: str) -> float:
    direct = difflib.SequenceMatcher(None, left, right).ratio()
    translit_left = transliterate_text(left)
    translit_right = transliterate_text(right)
    translit = difflib.SequenceMatcher(None, translit_left, translit_right).ratio()
    token_overlap = 0.0
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if left_tokens and right_tokens:
        token_overlap = len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))
    return max(direct, translit, token_overlap)


def _default_candidate_pool(discipline: Optional[str] = None) -> list[str]:
    try:
        from services.match_finder import UPCOMING_MATCHES, get_sport_keys_for_discipline
    except Exception:
        return []

    sports = set(get_sport_keys_for_discipline(discipline)) if discipline else set(UPCOMING_MATCHES.keys())
    if not sports:
        sports = set(UPCOMING_MATCHES.keys())

    candidates: list[str] = []
    for sport, matches in UPCOMING_MATCHES.items():
        if sport not in sports:
            continue
        for match in matches:
            candidates.extend([match.get("home", ""), match.get("away", "")])
    candidates.extend(COMMON_ALIASES.values())
    return [candidate for candidate in candidates if candidate]


def resolve_entity_name(
    name: str,
    discipline: Optional[str] = None,
    candidate_pool: Optional[Iterable[str]] = None,
    minimum_score: float = 0.86,
) -> dict:
    original = name.strip()
    if not original:
        return {
            "original": name,
            "normalized": "",
            "corrected": "",
            "applied": False,
            "reason": "empty",
            "score": 0.0,
        }

    normalized = normalize_entity_name(original)
    if normalized in COMMON_ALIASES:
        corrected = COMMON_ALIASES[normalized]
        return {
            "original": original,
            "normalized": normalized,
            "corrected": corrected,
            "applied": corrected != original,
            "reason": "alias",
            "score": 1.0,
        }

    candidates = list(candidate_pool or _default_candidate_pool(discipline))
    normalized_candidates = {}
    for candidate in candidates:
        normalized_candidate = normalize_entity_name(candidate)
        if normalized_candidate:
            normalized_candidates.setdefault(normalized_candidate, candidate)

    if normalized in normalized_candidates:
        corrected = normalized_candidates[normalized]
        return {
            "original": original,
            "normalized": normalized,
            "corrected": corrected,
            "applied": corrected != original,
            "reason": "exact",
            "score": 1.0,
        }

    best_candidate = original
    best_score = 0.0
    second_score = 0.0
    for candidate_normalized, candidate_display in normalized_candidates.items():
        score = _similarity(normalized, candidate_normalized)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_candidate = candidate_display
        elif score > second_score:
            second_score = score

    should_apply = best_score >= minimum_score and best_score - second_score >= 0.04
    corrected = best_candidate if should_apply else original
    return {
        "original": original,
        "normalized": normalized,
        "corrected": corrected,
        "applied": corrected != original,
        "reason": "fuzzy" if should_apply else "unchanged",
        "score": round(best_score, 3),
    }


def resolve_match_entities(team1: str, team2: str, discipline: Optional[str] = None) -> dict:
    first = resolve_entity_name(team1, discipline=discipline)
    second = resolve_entity_name(team2, discipline=discipline)
    corrected_match = f"{first['corrected']} vs {second['corrected']}"
    return {
        "team1": first,
        "team2": second,
        "match": corrected_match,
        "changed": first["applied"] or second["applied"],
    }