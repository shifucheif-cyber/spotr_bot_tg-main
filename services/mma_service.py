import re
import logging

from services.external_source import search_event_thesportsdb
from services.data_fetcher import MMAFetcher

logger = logging.getLogger(__name__)


def has_validated_data(result: str) -> bool:
    return bool(result) and "Валидация: validated" in result and "Подтверждено источников:" in result


def build_context_terms(match_context: dict | None, opponent: str) -> str:
    if not match_context:
        return opponent
    parts = [opponent, match_context.get("date", ""), match_context.get("league", "")]
    return " ".join(part for part in parts if part)


def normalize_fight_name(fight_name: str) -> str:
    return re.sub(r"\s+", " ", fight_name.strip())


def parse_mma_from_text(fight_name: str) -> str:
    fight_name = normalize_fight_name(fight_name)
    fighters = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", fight_name, flags=re.I)
    if len(fighters) == 2:
        return f"""
Бой: {fighters[0].strip()} vs {fighters[1].strip()}

Факторы:
- рост, размах рук и антропометрия
- силовой стиль, борцовская база, защита
- весогонка, выносливость и восстановление
- последний бой, активность и травмы

Анализ:
- Sherdog дает историю боёв и антропометрию
- UFC Stats дает точность ударов, защиту от тейкдаунов и контроль
- BoxRec помогает проверить рейтинг и активность боксёров
- если борец против ударника, преимущество у борца в клинче
- если есть разница в выносливости, это важно в поздних раундах
"""
    return ""


def parse_mma_fallback(fight_name: str) -> str:
    return f"""
Бой: {fight_name}

Факторы:
- рост и размах рук
- весогонка и подготовка
- стиль и выносливость
- последние результаты

Анализ:
- используйте Sherdog, UFC Stats и BoxRec для проверки истории и рейтинга
- тренерская подготовка и восстановление после травм важны
"""


def parse_mma_external(fight_name: str) -> str:
    event = search_event_thesportsdb(fight_name)
    if not event:
        return ""

    return f"""
Бой: {event.get('strHomeTeam', '').strip()} vs {event.get('strAwayTeam', '').strip()}

Событие: {event.get('strLeague', 'неизвестно')}
Дата: {event.get('dateEvent', 'неизвестно')}
Время: {event.get('strTime', 'неизвестно')}

Факторы:
- рост и размах рук
- весогонка и подготовка
- последний бой и травмы
- стиль и выносливость

Анализ:
- учитывайте стиль и состояние бойцов
- разница в выносливости важна в поздних раундах
"""


def fetch_mma_real_data(fight_name: str, match_context: dict | None = None) -> str:
    """Fetch real MMA/Boxing data from Sherdog, UFC Stats, and BoxRec."""
    try:
        fighters = re.split(r"\s+vs\.?\s+|\s+v\.?\s+|\s*-\s*", fight_name, flags=re.I)
        if len(fighters) != 2:
            return f"Бой: {fight_name}\n\nДанные загружаются из Sherdog, UFC Stats и BoxRec..."

        fighter1 = fighters[0].strip()
        fighter2 = fighters[1].strip()
        fighter1_context = build_context_terms(match_context, fighter2)
        fighter2_context = build_context_terms(match_context, fighter1)
        
        fetcher = MMAFetcher()
        f1_info = fetcher.fetch_fighter_info(fighter1, context_terms=fighter1_context)
        f2_info = fetcher.fetch_fighter_info(fighter2, context_terms=fighter2_context)

        result = f"""
🥊 **Бой:** {fighter1.upper()} vs {fighter2.upper()}

**Источники данных:**
- Sherdog (все бои, рекорды, стили, антропометрия)
- UFC Stats (точность ударов, тейкдауны, контроль)
- BoxRec (для бокса - официальные рейтинги)

**Информация о бойце 1 ({fighter1.upper()}):**
{format_mma_data(f1_info)}

**Информация о бойце 2 ({fighter2.upper()}):**
{format_mma_data(f2_info)}

**Ключевые метрики:**
- Рекорд побед/поражений (W-L-D)
- Способ побед (КО, сабмишн, решение)
- Антропометрия (рост, размах рук, вес)
- История последних боёв (форма)
- Стиль боя и навыки
- Выносливость и адаптация к враг

**Прогноз:**
- Анализируется...
"""
        logger.info(f"Successfully fetched MMA data for {fight_name}")
        return result

    except Exception as e:
        logger.error(f"Error fetching MMA real data: {e}")
        return f"Бой: {fight_name}\n\nДанные загружаются из Sherdog, UFC Stats и BoxRec..."


def format_mma_data(fighter_info: dict) -> str:
    """Format fighter information for display."""
    if not fighter_info:
        return "Данные загружаются..."
    
    lines = []
    for key, value in fighter_info.items():
        if key not in ["fighter"] and value:
            if isinstance(value, dict):
                for k, v in value.items():
                    lines.append(f"  - {k}: {v}")
            else:
                lines.append(f"  - {key}: {value}")
    
    return "\n".join(lines) if lines else "Данные загружаются..."


def get_mma_data(fight_name: str, subdiscipline: str = "mma", match_context: dict | None = None) -> str:
    # Выбираем логику в зависимости от дисциплины (ММА или Бокс)
    if subdiscipline == "boxing":
        # TODO: В будущем добавить специфичную логику для бокса
        pass
    
    # Try to fetch real data
    result = fetch_mma_real_data(fight_name, match_context=match_context)
    if has_validated_data(result):
        return result

    # Fall back to external sources
    external = parse_mma_external(fight_name)
    if external:
        return external

    result = parse_mma_from_text(fight_name)
    if result:
        return result

    return parse_mma_fallback(fight_name)
