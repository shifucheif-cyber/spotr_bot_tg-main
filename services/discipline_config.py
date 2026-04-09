"""Конфигурация дисциплин: типы участников, шаблоны поиска, обязательные данные.

Используется в collect_discipline_data() (search_engine.py) и fetch_match_analysis_data() (data_fetcher.py).
"""

from datetime import datetime
from typing import Optional

DISCIPLINE_CONFIG = {
    # ── Командные виды спорта ──
    "football": {
        "participant_type": "team",
        "has_total": True,
        "has_draw": True,
        "has_cards": True,
        "has_substitutions": True,
        "score_format": "goals",
        # [0] = обязательные данные (form, h2h, injuries); [1] = расширенные
        "search_templates_ru": [
            "{entity} футбол {season} форма результаты статистика травмы состав xG",
            "{entity} футбол {season} новости замены трансферы карточки дисквалификации усталость расписание",
        ],
        "search_templates_en": [
            "{entity} football {season} form results stats injuries lineup xG",
            "{entity} football {season} news transfers substitutions cards fatigue schedule",
        ],
        "h2h_template_ru": "{p1} vs {p2} футбол очные встречи h2h статистика последние матчи",
        "h2h_template_en": "{p1} vs {p2} football head to head h2h stats recent matches",
        "required_data": ["form", "h2h", "injuries"],
        "desired_data": [
            "cards", "substitutions", "xG", "home_away", "motivation",
            "standings", "fatigue", "news", "tactical_matchup",
        ],
    },
    "hockey": {
        "participant_type": "team",
        "has_total": True,
        "has_draw": False,
        "has_cards": True,  # удаления
        "has_substitutions": True,
        "score_format": "goals",
        "search_templates_ru": [
            "{entity} хоккей {season} форма результаты статистика травмы состав вратарь",
            "{entity} хоккей {season} новости замены удаления спецбригады большинство меньшинство",
        ],
        "search_templates_en": [
            "{entity} hockey {season} form results stats injuries roster goalie save percentage",
            "{entity} hockey {season} news trades penalties power play penalty kill",
        ],
        "h2h_template_ru": "{p1} vs {p2} хоккей очные встречи h2h статистика последние матчи",
        "h2h_template_en": "{p1} vs {p2} hockey head to head h2h stats recent matches",
        "required_data": ["form", "h2h", "injuries"],
        "desired_data": [
            "penalties", "substitutions", "power_play", "penalty_kill",
            "goalie_stats", "home_away", "standings", "fatigue",
        ],
    },
    "basketball": {
        "participant_type": "team",
        "has_total": True,
        "has_draw": False,
        "has_cards": False,
        "has_substitutions": True,
        "score_format": "points",
        "search_templates_ru": [
            "{entity} баскетбол {season} форма результаты статистика травмы состав",
            "{entity} баскетбол {season} новости замены темп рейтинг подборы потери скамейка",
        ],
        "search_templates_en": [
            "{entity} basketball {season} form results stats injuries roster",
            "{entity} basketball {season} news trades pace offensive defensive rating rebounds turnovers bench",
        ],
        "h2h_template_ru": "{p1} vs {p2} баскетбол очные встречи h2h статистика последние матчи",
        "h2h_template_en": "{p1} vs {p2} basketball head to head h2h stats recent matches",
        "required_data": ["form", "h2h", "injuries"],
        "desired_data": [
            "substitutions", "pace", "off_def_rating", "rebounds",
            "turnovers", "bench", "home_away", "standings",
        ],
    },
    "volleyball": {
        "participant_type": "team",
        "has_total": True,
        "has_draw": False,
        "has_cards": False,
        "has_substitutions": True,
        "score_format": "sets",
        "search_templates_ru": [
            "{entity} волейбол {season} форма результаты статистика травмы состав",
            "{entity} волейбол {season} новости замены подача приём атака связующий",
        ],
        "search_templates_en": [
            "{entity} volleyball {season} form results stats injuries roster",
            "{entity} volleyball {season} news substitutions serve reception attack efficiency setter",
        ],
        "h2h_template_ru": "{p1} vs {p2} волейбол очные встречи h2h статистика последние матчи",
        "h2h_template_en": "{p1} vs {p2} volleyball head to head h2h stats recent matches",
        "required_data": ["form", "h2h", "injuries"],
        "desired_data": [
            "substitutions", "serve", "reception", "attack_efficiency",
            "setter", "home_away", "standings",
        ],
    },

    # ── Соло / пара ──
    "tennis": {
        "participant_type": "solo_or_pair",
        "has_total": True,
        "has_draw": False,
        "has_cards": False,
        "has_substitutions": False,
        "score_format": "sets",
        "search_templates_ru": [
            "{entity} теннис {season} рейтинг форма результаты травмы покрытие",
            "{entity} теннис {season} подача приём брейк-пойнты усталость расписание турниров",
        ],
        "search_templates_en": [
            "{entity} tennis {season} ranking form results injuries surface win rate",
            "{entity} tennis {season} serve percentage break points fatigue schedule recent matches",
        ],
        "h2h_template_ru": "{p1} vs {p2} теннис очные встречи h2h покрытие статистика",
        "h2h_template_en": "{p1} vs {p2} tennis head to head h2h surface stats recent",
        "required_data": ["form", "h2h", "ranking"],
        "desired_data": [
            "surface_winrate", "serve_percentage", "break_points",
            "fatigue", "motivation",
        ],
    },
    "table_tennis": {
        "participant_type": "solo_or_pair",
        "has_total": True,
        "has_draw": False,
        "has_cards": False,
        "has_substitutions": False,
        "score_format": "sets",
        "search_templates_ru": [
            "{entity} настольный теннис {season} рейтинг форма результаты стиль",
            "{entity} настольный теннис {season} серии турниры последние матчи",
        ],
        "search_templates_en": [
            "{entity} table tennis {season} ranking form results style matchup",
            "{entity} table tennis {season} recent series tournaments matches",
        ],
        "h2h_template_ru": "{p1} vs {p2} настольный теннис очные встречи h2h статистика",
        "h2h_template_en": "{p1} vs {p2} table tennis head to head h2h stats",
        "required_data": ["form", "h2h", "ranking"],
        "desired_data": ["style", "equipment", "series"],
    },
    "mma": {
        "participant_type": "solo",
        "has_total": False,
        "has_draw": False,
        "has_cards": False,
        "has_substitutions": False,
        "score_format": "method_round",
        "search_templates_ru": [
            "{entity} ММА {season} рекорд форма результаты антропометрия reach стиль",
            "{entity} ММА {season} striking takedown defense cardio fight camp тренер новости",
        ],
        "search_templates_en": [
            "{entity} MMA {season} record form results reach striking accuracy takedown defense",
            "{entity} MMA {season} cardio ground game submissions fight camp coach news",
        ],
        "h2h_template_ru": "{p1} vs {p2} ММА очный бой h2h статистика прогноз",
        "h2h_template_en": "{p1} vs {p2} MMA fight h2h stats prediction preview",
        "required_data": ["form", "record", "striking"],
        "desired_data": [
            "reach", "takedown_defense", "cardio", "ground_game",
            "submissions", "fight_camp", "method_wins",
        ],
    },
    "boxing": {
        "participant_type": "solo",
        "has_total": False,
        "has_draw": True,
        "has_cards": False,
        "has_substitutions": False,
        "score_format": "method_round",
        "search_templates_ru": [
            "{entity} бокс {season} рекорд форма результаты титулы reach",
            "{entity} бокс {season} punch output KO нокаут footwork fight camp тренер новости",
        ],
        "search_templates_en": [
            "{entity} boxing {season} record form results titles reach opposition level",
            "{entity} boxing {season} punch output KO ratio footwork fight camp coach news",
        ],
        "h2h_template_ru": "{p1} vs {p2} бокс бой h2h статистика прогноз",
        "h2h_template_en": "{p1} vs {p2} boxing fight h2h stats prediction preview",
        "required_data": ["form", "record", "reach"],
        "desired_data": [
            "punch_output", "ko_ratio", "footwork", "opposition_level",
            "fight_camp", "activity",
        ],
    },

    # ── Киберспорт ──
    "cs2": {
        "participant_type": "team",
        "has_total": True,
        "has_draw": False,
        "has_cards": False,
        "has_substitutions": True,
        "score_format": "maps",
        "search_templates_ru": [
            "{entity} CS2 {season} рейтинг HLTV форма результаты состав",
            "{entity} CS2 {season} map pool сильные слабые карты замены ростер новости",
        ],
        "search_templates_en": [
            "{entity} CS2 Counter-Strike {season} HLTV rating form results roster",
            "{entity} CS2 {season} map pool strengths weaknesses roster changes news",
        ],
        "h2h_template_ru": "{p1} vs {p2} CS2 очные матчи h2h карты статистика",
        "h2h_template_en": "{p1} vs {p2} CS2 head to head h2h maps stats recent",
        "required_data": ["form", "h2h", "roster"],
        "desired_data": [
            "hltv_rating", "map_pool", "pistol_rounds",
            "roster_changes", "strengths_in_discipline",
        ],
    },
    "dota2": {
        "participant_type": "team",
        "has_total": True,
        "has_draw": False,
        "has_cards": False,
        "has_substitutions": True,
        "score_format": "maps",
        "search_templates_ru": [
            "{entity} Dota 2 {season} форма результаты состав hero pool",
            "{entity} Dota 2 {season} драфт мета ранняя поздняя игра замены ростер новости",
        ],
        "search_templates_en": [
            "{entity} Dota 2 {season} form results roster hero pool winrate",
            "{entity} Dota 2 {season} draft meta early late game roster changes news",
        ],
        "h2h_template_ru": "{p1} vs {p2} Dota 2 очные матчи h2h статистика",
        "h2h_template_en": "{p1} vs {p2} Dota 2 head to head h2h stats recent",
        "required_data": ["form", "h2h", "roster"],
        "desired_data": [
            "hero_pool", "draft_meta", "early_late_game",
            "roster_changes", "strengths_in_discipline",
        ],
    },
    "lol": {
        "participant_type": "team",
        "has_total": True,
        "has_draw": False,
        "has_cards": False,
        "has_substitutions": True,
        "score_format": "maps",
        "search_templates_ru": [
            "{entity} League of Legends {season} форма результаты состав champion pool",
            "{entity} LoL {season} драфт dragon baron gold lead замены ростер новости",
        ],
        "search_templates_en": [
            "{entity} League of Legends {season} form results roster champion priority",
            "{entity} LoL {season} draft dragon baron control early gold lead roster changes news",
        ],
        "h2h_template_ru": "{p1} vs {p2} LoL очные матчи h2h статистика",
        "h2h_template_en": "{p1} vs {p2} League of Legends head to head h2h stats recent",
        "required_data": ["form", "h2h", "roster"],
        "desired_data": [
            "champion_priority", "dragon_baron", "gold_lead",
            "roster_changes", "strengths_in_discipline",
        ],
    },
    "valorant": {
        "participant_type": "team",
        "has_total": True,
        "has_draw": False,
        "has_cards": False,
        "has_substitutions": True,
        "score_format": "maps",
        "search_templates_ru": [
            "{entity} Valorant {season} форма результаты состав agent picks",
            "{entity} Valorant {season} map win rates clutch ACS замены ростер новости",
        ],
        "search_templates_en": [
            "{entity} Valorant {season} form results roster agent picks ACS rating",
            "{entity} Valorant {season} map win rates clutch stats roster changes news",
        ],
        "h2h_template_ru": "{p1} vs {p2} Valorant очные матчи h2h карты статистика",
        "h2h_template_en": "{p1} vs {p2} Valorant head to head h2h maps stats recent",
        "required_data": ["form", "h2h", "roster"],
        "desired_data": [
            "agent_picks", "map_winrates", "clutch_stats",
            "acs_rating", "roster_changes", "strengths_in_discipline",
        ],
    },
}


def get_config(discipline_key: str) -> dict | None:
    """Возвращает конфиг дисциплины или None."""
    return DISCIPLINE_CONFIG.get(discipline_key)


def _current_season() -> str:
    from datetime import timezone as _tz
    now = datetime.now(tz=_tz.utc)
    year = now.year
    return f"{year - 1}/{year}" if now.month < 7 else f"{year}/{year + 1}"


def get_search_queries(
    config: dict,
    entity: str,
    discipline: str,
    is_russian: bool,
) -> list[str]:
    """Рендерит шаблоны поисковых запросов для участника."""
    season = _current_season()
    suffix = "_ru" if is_russian else "_en"
    templates = config.get(f"search_templates{suffix}", config.get("search_templates_en", []))

    queries = []
    for tpl in templates:
        q = tpl.format(entity=entity, discipline=discipline, season=season)
        queries.append(q)
    return queries


def get_h2h_query(
    config: dict,
    p1: str,
    p2: str,
    discipline: str,
    is_russian: bool,
) -> str:
    """Рендерит H2H-запрос."""
    suffix = "_ru" if is_russian else "_en"
    tpl = config.get(f"h2h_template{suffix}", config.get("h2h_template_en", "{p1} vs {p2}"))
    return tpl.format(p1=p1, p2=p2, discipline=discipline)
