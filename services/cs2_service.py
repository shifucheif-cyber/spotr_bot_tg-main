import difflib
import logging
import re

from services.external_source import search_event_thesportsdb

try:
    import HLTV
except ImportError:
    HLTV = None


def normalize_team_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9а-яё\s]", " ", name)
    name = re.sub(r"\bteam\b", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def parse_match_teams(match_name: str) -> list[str]:
    parts = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", match_name, flags=re.I)
    return [normalize_team_name(p) for p in parts if p.strip()]


def is_similar(a: str, b: str) -> bool:
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


def parse_cs2_from_hltv(match_name: str) -> str:
    if HLTV is None:
        return ""

    try:
        normalized_query = normalize_team_name(match_name)
        query_teams = parse_match_teams(match_name)

        all_matches = []
        for fetch_name in ("get_upcoming_matches", "get_live_matches"):
            fetch = getattr(HLTV, fetch_name, None)
            if not fetch:
                continue
            try:
                entries = fetch()
            except Exception as e:
                logging.warning("HLTV %s failed: %s", fetch_name, e)
                continue

            if not entries:
                continue

            for entry in entries:
                if isinstance(entry, tuple) and len(entry) == 2:
                    all_matches.append(entry)
                elif isinstance(entry, dict) and "teams" in entry and len(entry["teams"]) >= 2:
                    all_matches.append((entry["teams"][0], entry["teams"][1]))

        for team1, team2 in all_matches:
            title = f"{team1} vs {team2}"
            normalized_title = normalize_team_name(title)

            if normalized_query in normalized_title or normalized_title in normalized_query:
                return f"""
Матч: {team1} vs {team2}

Состояние:
- матч найден в расписании CS2
- формат и пул карт нужно уточнить
- анализируйте текущую форму, составы и метагейм команд
"""

            if len(query_teams) == 2:
                team1_name = normalize_team_name(team1)
                team2_name = normalize_team_name(team2)
                if (
                    is_similar(query_teams[0], team1_name)
                    and is_similar(query_teams[1], team2_name)
                ) or (
                    is_similar(query_teams[0], team2_name)
                    and is_similar(query_teams[1], team1_name)
                ):
                    return f"""
Матч: {team1} vs {team2}

Состояние:
- матч найден в расписании CS2
- формат и пул карт нужно уточнить
- анализируйте текущую форму, составы и метагейм команд
"""

        return ""
    except Exception as e:
        logging.warning("HLTV parser failed: %s", e)
        return ""


def parse_cs2_fallback(match_name: str) -> str:
    teams = parse_match_teams(match_name)
    factors = [
        "формат (Bo1/Bo3/Bo5)",
        "пул карт и предпочтения",
        "составы команд и замены",
        "рейтинг игроков и текущая форма",
        "экономика и покупка",
        "тренерские правки и ментальная стабильность"
    ]
    factor_block = "\n".join(f"- {item}" for item in factors)

    if len(teams) == 2:
        return f"""
Матч: {teams[0].title()} vs {teams[1].title()}

Факторы анализа:
{factor_block}

Анализ:
- проверьте пул карт и предпочтения команд
- учитывайте замену игроков и свежесть состава
- рейтинг игроков и экономическая стабильность решают
"""

    return f"""
Матч: {match_name}

Факторы анализа:
{factor_block}

Анализ:
- ищите информацию о картах, составе и истории личных встреч
- учитывайте тренерские правки и ротации
"""


def parse_dota_from_text(match_name: str) -> str:
    teams = parse_match_teams(match_name)
    if len(teams) == 2:
        return f"""
Матч: {teams[0].title()} vs {teams[1].title()}

Факторы анализа:
- мета героев и винрейты в текущем патче
- ротация состава и роли поддержки
- экономика, контроль карты и Roshan
- замены, состояние игроков и форма
"""
    return ""


def parse_lol_from_text(match_name: str) -> str:
    teams = parse_match_teams(match_name)
    if len(teams) == 2:
        return f"""
Матч: {teams[0].title()} vs {teams[1].title()}

Факторы анализа:
- драфт и мета текущей patch
- состояние линий и выбор череды чемпионов
- команда, тренерские правки, замены
- лиговая форма и история личных встреч
"""
    return ""


def parse_dota_fallback(match_name: str) -> str:
    return f"""
Матч: {match_name}

Факторы анализа:
- мета героев и винрейты
- ротация состава и замены
- экономика и контроль карты
- форма команды и подготовка
Анализ:
- обратите внимание на патч и героев
- считайте важность роли поддержки и каптана
"""


def parse_lol_fallback(match_name: str) -> str:
    return f"""
Матч: {match_name}

Факторы анализа:
- драфт и мета патча
- состояние линий и тренерские правки
- ротация и замены
- командная координация и зона контроля
Анализ:
- смотрите на драфт и текущую мету
- учитывайте состояние лидов и тренерскую стратегию
"""


def get_esports_data(match_name: str, discipline: str) -> str:
    d = discipline.lower()
    if "cs" in d or "cs2" in d or "counter-strike" in d or "hltv" in d:
        result = parse_cs2_from_hltv(match_name)
        if result:
            return result

        logging.info("Esports parser: CS2 HLTV не нашёл матч, пробуем fallback")
        return parse_cs2_fallback(match_name)

    if "dota" in d or "dota 2" in d:
        result = parse_dota_from_text(match_name)
        if result:
            return result
        return parse_dota_fallback(match_name)

    if "lol" in d or "league of legends" in d:
        result = parse_lol_from_text(match_name)
        if result:
            return result
        return parse_lol_fallback(match_name)

    return parse_cs2_fallback(match_name)
