"""E2E test: current hockey pipeline -> data collection -> Groq/SambaNova analysis."""

import asyncio
import logging
import os
import sys

sys.path.insert(0, "d:/spotr_bot_tg-main")
os.chdir("d:/spotr_bot_tg-main")

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
log = logging.getLogger("E2E")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY")
SAMBANOVA_BASE_URL = os.getenv("SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1")
SAMBANOVA_MODEL = os.getenv("SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct")
MATCH_NAME = "Омские крылья vs Челмет Челябинск"
MATCH_CONTEXT = {"date": "2026-04-03", "league": "ВХЛ"}
SYSTEM_PROMPT = """Ты - профессиональный аналитик хоккейных матчей.
Анализируй ТОЛЬКО указанный матч, используя ПОЛУЧЕННЫЕ данные.

**ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:**
📊 **Матч:** [Команда А] vs [Команда Б]
📅 **Дата:** [Дата]

📝 **Анализ команд:**
• **[Команда А]:** (форма, лидеры, травмы, серия побед/поражений)
• **[Команда Б]:** (форма, лидеры, травмы, серия побед/поражений)

🔍 **Ключевые факторы:**
• (Фактор 1)
• (Фактор 2)

📈 **Вероятность победы (1-я команда):** X%

МЕТОДОЛОГИЯ АНАЛИЗА (выполняй строго по шагам):

ШАГ 1 — ИЗВЛЕЧЕНИЕ ФАКТОВ. Из полученных данных выпиши КОНКРЕТНЫЕ факты:
- Последние результаты каждой стороны (серии побед/поражений, счета)
- Личные встречи (H2H) — кто побеждал, с каким счётом
- Травмы, дисквалификации, отсутствие ключевых игроков
- Текущая позиция в турнирной таблице, стадия плей-офф
- Домашнее/выездное преимущество

ШАГ 2 — ВЗВЕШИВАНИЕ. Для каждого факта определи: в чью пользу он работает?
Запиши: «[Факт] → преимущество [Сторона А / Сторона Б / нейтрально]»

ШАГ 3 — ВЫВОД. Подсчитай, у кого больше значимых преимуществ.
Чем больше одна сторона доминирует по фактам — тем дальше вероятность от 50%.
Если факты примерно равны — вероятность близка к 50% (пропуск ставки).

КРИТИЧЕСКОЕ ПРАВИЛО: Победитель = сторона с вероятностью > 50%. Вероятность 2-й стороны = 100 - P.

📋 **Факты из данных:**
- (факт 1 → преимущество [сторона])
- ...

🏆 **Победитель:** <сторона с P > 50%>
🔢 **Прогнозируемый счёт:** X:Y
💰 **Рекомендуемый % от банка:** X% (от 1% до 5%)

```json
{"winner": "TeamName", "probability": X, "score": "X:Y", "stake_percent": X}
```
"""


async def collect_search_data() -> str:
    from services.hockey_service import get_hockey_data

    log.info("STEP 1: Collecting hockey data...")
    search_data = await get_hockey_data(MATCH_NAME, match_context=MATCH_CONTEXT)
    log.info("Search data collected: %d chars", len(search_data))
    return search_data


async def generate_with_groq(payload: str) -> tuple[str, str]:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    from groq import Client as GroqClient

    client = GroqClient(api_key=GROQ_API_KEY, base_url="https://api.groq.com")
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": payload},
            ],
            max_completion_tokens=2000,
            temperature=0.2,
            timeout=30.0,
        ),
    )
    return "groq", response.choices[0].message.content


async def generate_with_sambanova(payload: str) -> tuple[str, str]:
    if not SAMBANOVA_API_KEY:
        raise RuntimeError("SAMBANOVA_API_KEY is not configured")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=SAMBANOVA_API_KEY, base_url=SAMBANOVA_BASE_URL)
    response = await client.chat.completions.create(
        model=SAMBANOVA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": payload},
        ],
        max_tokens=2000,
        temperature=0.2,
        timeout=30.0,
    )
    return "sambanova", response.choices[0].message.content


async def run():
    if not GROQ_API_KEY and not SAMBANOVA_API_KEY:
        raise RuntimeError("At least one of GROQ_API_KEY or SAMBANOVA_API_KEY is required")

    search_data = await collect_search_data()
    payload = (
        f"{search_data}\n\n"
        f"Подтвержденный матч: {MATCH_NAME}\n"
        f"Дата матча: {MATCH_CONTEXT['date']}\n"
        f"Лига/турнир: {MATCH_CONTEXT['league']}\n"
    )

    last_error = None
    provider = None
    result = None
    for generator in (generate_with_groq, generate_with_sambanova):
        try:
            provider_name = "Groq" if generator is generate_with_groq else "SambaNova"
            log.info("STEP 2: Calling %s LLM...", provider_name)
            provider, result = await generator(payload)
            break
        except Exception as exc:
            last_error = exc
            log.warning("%s failed: %s", provider_name, exc)

    if not result:
        raise last_error or RuntimeError("No LLM provider succeeded")

    log.info("LLM OK via %s: %d chars", provider, len(result))
    print("\n" + "=" * 60)
    print(f"Provider: {provider}")
    print(result)
    print("=" * 60)
    with open("_hockey_analysis.txt", "w", encoding="utf-8") as handle:
        handle.write(result)


if __name__ == "__main__":
    asyncio.run(run())
