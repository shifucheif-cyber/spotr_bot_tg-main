"""E2E test: Hockey — Омские крылья vs Челмет Челябинск → Groq analysis."""
import sys, os, asyncio
sys.path.insert(0, "d:/spotr_bot_tg-main")
os.chdir("d:/spotr_bot_tg-main")
from dotenv import load_dotenv; load_dotenv()

import logging
logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
log = logging.getLogger("E2E")

# ── Step 1: Search ──
log.info("STEP 1: Collecting search data...")
from services.data_fetcher import HockeyFetcher, fetch_match_analysis_data

search_data = fetch_match_analysis_data(
    "Омские крылья vs Челмет Челябинск",
    HockeyFetcher(),
    "fetch_team_info",
    "\U0001f3d2",
    match_context={"date": "2026-04-03", "league": "ВХЛ"},
)
log.info("Search data: %d chars", len(search_data))

# ── Step 2: LLM ──
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
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

payload = (
    f"{search_data}\n\n"
    "Подтвержденный матч: Омские крылья vs Челмет Челябинск\n"
    "Дата матча: 2026-04-03\n"
    "Лига/турнир: ВХЛ\n"
)

async def run():
    from groq import Client as GroqClient
    client = GroqClient(api_key=GROQ_API_KEY, base_url="https://api.groq.com")
    loop = asyncio.get_event_loop()
    log.info("Calling Groq LLM...")
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
    result = response.choices[0].message.content
    log.info("LLM OK: %d chars", len(result))
    print("\n" + "=" * 60)
    print(result)
    print("=" * 60)
    with open("_hockey_analysis.txt", "w", encoding="utf-8") as f:
        f.write(result)

asyncio.run(run())
