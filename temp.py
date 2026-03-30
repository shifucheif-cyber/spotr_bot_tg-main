import re

with open("bot.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Update the flat recommendation pattern
text = re.sub(r"💰 \*\*Рекомендация по ставке:\*\*.*?P < 55% → ⚠️ ПРОПУСТИТЬ \(Высокая неопределённость\)", "", text, flags=re.DOTALL)

# 2. Update the OUTPUT_CONTRACT_SUFFIX
old_suffix = """ФИНАЛЬНЫЙ ОБЯЗАТЕЛЬНЫЙ FORMAT ОТВЕТА:
📊 **Матч:** <команда/игрок 1> vs <команда/игрок 2>
🏆 **Победитель:** <только один конкретный победитель>
🎯 **Общий тотал:** <тотал голов/карт/сетов/раундов или 'неопределен'>
🔢 **Прогноз по счету:** <точный или сценарный счет, например 2:1 / 3:0 / 2-0>
📈 **Вероятность прогноза:** <число>%
💰 **Ставка:** <6% / 3% / 1% / ПРОПУСК>
📝 **Обоснование:**
- 2-4 кратких пункта по делу

Если данных мало, все равно заполни все поля, но явно пометь low-confidence lean."""

new_suffix = """ФИНАЛЬНЫЙ ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ОТВЕТА:
Сначала напиши развернутый текстовый анализ:
📊 **Матч:** <команда/игрок 1> vs <команда/игрок 2>
🏆 **Победитель:** <только один конкретный победитель>
🎯 **Общий тотал:** <тотал/неопределен>
🔢 **Прогноз по счету:** <точный или сценарный счет, например 2:1 / 3:0 / 2-0>
📝 **Обоснование:**
- 3-5 пунктов по делу (анализ формы, травм, личных встреч, мотивации)

А В САМОМ КОНЦЕ СООБЩЕНИЯ ВЫВЕДИ JSON БЛОК. Обязательно укажи честную вероятность победы от 0 до 100 и коэффициент (odds). Если коэффициент букмекера не найден в данных - поставь null.
```json
{
  "probability": 75,
  "odds": null
}
```"""

text = text.replace(old_suffix, new_suffix)

# 3. Add graceful fallback to LLMs
old_except = """        log_user_event(message.from_user.id, "analysis_exception", {"error": str(e)})
        await message.answer(f"❌ Ошибка: {str(e)}")"""

new_except = """        log_user_event(message.from_user.id, "analysis_exception", {"error": str(e)})
        if "No available LLM providers" in str(e):
            await message.answer("⚙️ Сервисы ИИ временно недоступны. Пожалуйста, попробуйте позже.")
        elif "quota" in str(e).lower() or "rate limit" in str(e).lower():
            await message.answer("⚙️ Сервисы ИИ перегружены (лимит запросов). Пожалуйста, попробуйте через пару минут.")
        else:
            await message.answer("❌ Внутренняя ошибка платформы: " + str(e))"""

text = text.replace(old_except, new_except)

with open("bot.py", "w", encoding="utf-8") as f:
    f.write(text)
print("done")
