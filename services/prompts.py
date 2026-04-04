import logging
import re
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Путь к папке с промптами
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

def load_prompt_file(filename: str) -> str:
    """Загружает содержимое файла из папки prompts."""
    path = PROMPTS_DIR / filename
    if not path.exists():
        logger.warning(f"Prompt file not found: {path}")
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        logger.error(f"Error reading prompt file {path}: {e}")
        return ""

def get_discipline_prompt(discipline: str, discipline_key: str = None) -> str:
    """
    Получает оптимизированный prompt для дисциплины, загружая его из Markdown-файла.
    Это позволяет редактировать промпты без перезагрузки кода.
    """
    from services.match_finder import normalize_discipline
    
    # 1. Загружаем общий суффикс (контракт ответа)
    common_suffix = load_prompt_file("common_suffix.md")
    
    # 2. Определяем имя файла дисциплины
    target_key = ""
    if discipline_key:
        target_key = discipline_key.lower()
    else:
        # Если это формат "киберспорт: CS2", извлечем "cs2"
        if ":" in discipline:
            parts = discipline.split(":")
            discipline = parts[1].strip().lower()
        target_key = normalize_discipline(discipline).lower()

    # Маппинг ключей на файлы (если отличаются)
    prompt_files = {
        "киберспорт": "cybersport.md",
        "футбол": "football.md",
        "хоккей": "hockey.md",
        "cs2": "cs2.md",
        "dota2": "dota2.md",
        "lol": "lol.md",
        "valorant": "valorant.md",
        "tennis": "tennis.md",
        "теннис": "tennis.md",
        "table_tennis": "table_tennis.md",
        "настольный теннис": "table_tennis.md",
        "mma": "mma.md",
        "мма": "mma.md",
        "boxing": "boxing.md",
        "бокс": "boxing.md",
        "волейбол": "volleyball.md",
        "volleyball": "volleyball.md",
        "баскетбол": "basketball.md",
        "basketball": "basketball.md",
    }

    filename = prompt_files.get(target_key, f"{target_key}.md")
    
    # 3. Пытаемся загрузить специфичный промпт
    prompt_content = load_prompt_file(filename)
    
    # 4. Если файл не найден, пробуем fallback на cybersport.md или football.md
    if not prompt_content:
        logger.info(f"Fallback for {target_key} to cybersport.md")
        prompt_content = load_prompt_file("cybersport.md")
        
    return f"{prompt_content}\n\n{common_suffix}"
