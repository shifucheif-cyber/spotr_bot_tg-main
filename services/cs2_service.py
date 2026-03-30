import difflib
import logging
import re
import requests
from datetime import datetime
from urllib.parse import quote

from services.external_source import search_event_thesportsdb
from services.data_fetcher import CS2Fetcher, EsportsGameFetcher

try:
    import HLTV
except ImportError:
    HLTV = None


def build_context_terms(match_context: dict | None, opponent: str) -> str:
    if not match_context:
        return opponent
    parts = [opponent, match_context.get("date", ""), match_context.get("league", "")]
    return " ".join(part for part in parts if part)


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


def fetch_cs2_real_data(match_name: str, match_context: dict | None = None) -> str:
    """
    Fetch real CS2 match data from HLTV and Liquipedia.
    
    Args:
        match_name: Match name (e.g., "FaZe vs Vitality")
        
    Returns:
        Structured data with match information
    """
    try:
        teams = parse_match_teams(match_name)
        if len(teams) != 2:
            logging.warning(f"Could not parse teams from {match_name}")
            return parse_cs2_fallback(match_name)

        team1, team2 = teams[0].strip(), teams[1].strip()
        match_context_terms = build_context_terms(match_context, f"{team1} {team2}")
        team1_context = build_context_terms(match_context, team2)
        team2_context = build_context_terms(match_context, team1)
        fetcher = CS2Fetcher()
        
        # Fetch match info from multiple sources
        match_data = fetcher.fetch_match_info(team1, team2, context_terms=match_context_terms)
        
        if not match_data:
            logging.info(f"No match data found for {match_name}")
            return parse_cs2_fallback(match_name)

        # Fetch team stats for both teams
        team1_stats = fetcher.fetch_team_stats(team1, context_terms=team1_context)
        team2_stats = fetcher.fetch_team_stats(team2, context_terms=team2_context)

        # Format data for LLM analysis
        result = f"""
📊 **Матч:** {team1.upper()} vs {team2.upper()}

**Источники данных:**
- HLTV (рейтинги, история матчей, динамика формы)
- Liquipedia (составы, трансферы, статистика команд)

**Информация о командах:**

*{team1.upper()}:*
{format_team_data(team1_stats) if team1_stats else "Загрузка данных..."}

*{team2.upper()}:*
{format_team_data(team2_stats) if team2_stats else "Загрузка данных..."}

**Последние матчи:**
- Ищутся в базе HLTV...

**История личных встреч (H2H):**
- Анализируется...

**Ключевые метрики:**
- Винрейт команд в последних 10 матчах
- Рейтинг игроков на ключевых позициях
- Пулы карт и предпочтения
- Форма вратарей (для Valorant) / стартеров (для CS2)
"""
        
        logging.info(f"Successfully fetched CS2 data for {match_name}")
        return result

    except Exception as e:
        logging.error(f"Error fetching CS2 real data: {e}")
        return parse_cs2_fallback(match_name)


def format_team_data(team_stats: dict) -> str:
    """Format team statistics for display."""
    if not team_stats:
        return "Данные загружаются..."
    
    lines = []
    for key, value in team_stats.items():
        if key not in ["source", "timestamp"]:
            lines.append(f"  - {key}: {value}")
    
    return "\n".join(lines) if lines else "Данные загружаются..."


def has_payload(team_info: dict | None) -> bool:
    return bool(team_info) and any(
        key in team_info for key in ("report", "validated_count", "status", "validated_sources")
    )


def fetch_generic_esports_data(
    match_name: str,
    game_key: str,
    source_lines: list[str],
    metric_lines: list[str],
    match_context: dict | None = None,
    emoji: str = "🎮",
) -> str:
    try:
        teams = parse_match_teams(match_name)
        if len(teams) != 2:
            return ""

        team1, team2 = teams[0].strip(), teams[1].strip()
        match_context_terms = build_context_terms(match_context, f"{team1} {team2}")
        team1_context = build_context_terms(match_context, team2)
        team2_context = build_context_terms(match_context, team1)
        fetcher = EsportsGameFetcher(game_key)

        match_data = fetcher.fetch_match_info(team1, team2, context_terms=match_context_terms)
        team1_stats = fetcher.fetch_team_info(team1, context_terms=team1_context)
        team2_stats = fetcher.fetch_team_info(team2, context_terms=team2_context)

        if not any([has_payload(match_data), has_payload(team1_stats), has_payload(team2_stats)]):
            return ""

        sources_block = "\n".join(f"- {line}" for line in source_lines)
        metrics_block = "\n".join(f"- {line}" for line in metric_lines)
        return f"""
{emoji} **Матч:** {team1.upper()} vs {team2.upper()}

**Источники данных:**
{sources_block}

**Информация по матчу:**
{format_team_data(match_data) if match_data else "Данные матча загружаются..."}

**Информация о команде 1 ({team1.upper()}):**
{format_team_data(team1_stats) if team1_stats else "Данные загружаются..."}

**Информация о команде 2 ({team2.upper()}):**
{format_team_data(team2_stats) if team2_stats else "Данные загружаются..."}

**Ключевые метрики:**
{metrics_block}
"""
    except Exception as e:
        logging.error("Error fetching %s real data: %s", game_key, e)
        return ""


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


def parse_valorant_from_text(match_name: str) -> str:
    teams = parse_match_teams(match_name)
    if len(teams) == 2:
        return f"""
Матч: {teams[0].title()} vs {teams[1].title()}

Факторы анализа:
- пул карт и процент атак/защит
- мета агентов и роль дуэлянтов/инициаторов
- форма ростера и последние замены
- история личных встреч и результаты на LAN
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


def parse_valorant_fallback(match_name: str) -> str:
    return f"""
Матч: {match_name}

Факторы анализа:
- пул карт и сторона атаки/защиты
- мета агентов и командные комбинации
- текущий ростер и замены
- форма команды на последних турнирах
Анализ:
- смотрите на map pool, agent pool и свежесть состава
- учитывайте опыт на LAN и качество исполнения ретейков
"""


def get_esports_data(match_name: str, discipline: str, match_context: dict | None = None) -> str:
    d = discipline.lower()
    if "cs" in d or "cs2" in d or "counter-strike" in d or "hltv" in d:
        # Try to fetch real data from HLTV/Liquipedia
        result = fetch_cs2_real_data(match_name, match_context=match_context)
        if result and "Валидация: validated" in result and "Подтверждено источников:" in result:
            return result

        # Fall back to template if real data unavailable
        logging.info("CS2: Real data unavailable, using template")
        return parse_cs2_fallback(match_name)

    if "dota" in d or "dota 2" in d:
        result = fetch_generic_esports_data(
            match_name,
            "dota2",
            source_lines=[
                "Dotabuff (мета героев, публичная форма игроков)",
                "Liquipedia (сетки, замены, расписание)",
            ],
            metric_lines=[
                "Мета героев и текущий патч",
                "Форма игроков и активность в пабликах",
                "Замены и стабильность ростера",
                "История личных встреч и сетка турнира",
            ],
            match_context=match_context,
        )
        if result:
            return result
        result = parse_dota_from_text(match_name)
        if result:
            return result
        return parse_dota_fallback(match_name)

    if "lol" in d or "league of legends" in d:
        result = fetch_generic_esports_data(
            match_name,
            "lol",
            source_lines=[
                "Oracle's Elixir (gold per minute, контроль объектов, advanced stats)",
                "Liquipedia (сетки, замены, расписание)",
            ],
            metric_lines=[
                "Gold per minute и разница по золоту",
                "Контроль драконов, герольда, Nashor",
                "Драфт, текущая мета и глубина пула чемпионов",
                "Замены и форма состава",
            ],
            match_context=match_context,
        )
        if result:
            return result
        result = parse_lol_from_text(match_name)
        if result:
            return result
        return parse_lol_fallback(match_name)

    if "valorant" in d:
        result = fetch_generic_esports_data(
            match_name,
            "valorant",
            source_lines=[
                "VLR.gg (карты, агенты, детальные разборы матчей)",
                "Liquipedia (ростеры, замены, расписание)",
            ],
            metric_lines=[
                "Пул карт и винрейты по картам",
                "Пулы агентов и командные комбинации",
                "Текущие замены и стабильность состава",
                "Результаты последних матчей и опыт на LAN",
            ],
            match_context=match_context,
        )
        if result:
            return result
        result = parse_valorant_from_text(match_name)
        if result:
            return result
        return parse_valorant_fallback(match_name)

    return parse_cs2_fallback(match_name)
