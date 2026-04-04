"""Betting recommendation calculator using Kelly Criterion and Value Betting"""
import re
import json


def extract_probability(llm_response: str) -> float | None:
    """
    Извлекает процент вероятности из ответа модели.
    Учитывает markdown из контракта: «📈 **Вероятность победы (1-я сторона):** 58%» —
    после скобки идёт `):**`, старые шаблоны с [:\s]+ после «сторона» не срабатывали.
    """
    prioritized = [
        # Контракт бота: 📈 **Вероятность победы (1-я сторона):** N%
        r"📈\s*\*+\s*Вероятность\s+победы[^%]+?(\d+(?:[.,]\d+)?)\s*%",
        r"📈\s*Вероятность\s+победы[^%]+?(\d+(?:[.,]\d+)?)\s*%",
        r"Вероятность\s+победы\s*\([^)]*\)\s*:\s*\*+\s*(\d+(?:[.,]\d+)?)\s*%",
        r"Вероятность\s+победы[^%]+?(\d+(?:[.,]\d+)?)\s*%",
        # «Вероятность:» с опциональными звёздочками после двоеточия
        r"Вероятность[^%\n]{0,120}:\s*\*+\s*(\d+(?:[.,]\d+)?)\s*%",
        r"Вероятность[^%\n]{0,120}:\s*(\d+(?:[.,]\d+)?)\s*%",
        r"[Pp]\s*[=:]\s*(\d+(?:[.,]\d+)?)\s*%",
        r"вероятность[^%\n]{0,120}:\s*(\d+(?:[.,]\d+)?)\s*%",
    ]
    for pat in prioritized:
        m = re.search(pat, llm_response, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if m:
            val = float(m.group(1).replace(",", "."))
            if 0 <= val <= 100:
                return val

    tail = llm_response[-2500:] if len(llm_response) > 2500 else llm_response
    m = re.search(
        r"(?:📈\s*)?(?:\*\*)?\s*Вероятность[^%]{0,200}?(\d+(?:[.,]\d+)?)\s*%",
        tail,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        v = float(m.group(1).replace(",", "."))
        if 0 <= v <= 100:
            return v

    return None


def extract_betting_data(llm_response: str) -> dict:
    """
    Searches for a JSON block within the response text.
    Falls back to existing regex for probability ONLY if JSON loading fails.
    """
    probability = None
    odds = None
    
    # Try finding JSON block
    match = re.search(r'```json\s*(\{.*?\})\s*```', llm_response, re.DOTALL | re.IGNORECASE)
    if not match:
        match = re.search(r'(\{.*?\})', llm_response, re.DOTALL)
        
    if match:
        try:
            data = json.loads(match.group(1))
            prob_val = data.get("probability")
            odds_val = data.get("odds")
            if prob_val is not None:
                probability = float(prob_val)
            if odds_val is not None:
                odds = float(odds_val)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
            
    # Fallback to regex for probability
    if probability is None:
        probability = extract_probability(llm_response)
        
    return {"probability": probability, "odds": odds}


def calculate_value_bet(probability: float, odds: float | None = None) -> dict:
    """
    Calculates value bet metrics and Kelly criterion fraction.
    """
    if probability <= 0 or probability >= 100:
        return {
            "recommendation": (
                "Модель дала крайнее значение (0% или 100%) — для Келли/валуй это недопустимо; "
                "ставку не считаем. Считайте прогноз условным или повторите запрос."
            ),
            "stake_percent": "ПРОПУСК",
        }
        
    fair_odds = 100 / probability
    
    if odds is None:
        min_profitable_odds = fair_odds * 1.05
        return {
            "recommendation": f"⚠️ Ищите коэффициент строго > {min_profitable_odds:.2f} (с учетом маржи). Справедливый кэф: {fair_odds:.2f}.",
            "stake_percent": f"3% (ПРИ кэфе > {min_profitable_odds:.2f})"
        }
        
    if odds <= 1:
        return {"recommendation": "Недопустимый коэффициент", "stake_percent": "0"}
        
    edge = (probability / 100 * odds) - 1
    
    if edge > 0:
        # Kelly Criterion
        f = edge / (odds - 1)
        # Fractional Kelly (1/4 to represent safe bankroll management)
        f_safe = f * 0.25 
        stake_percent = min(max(f_safe * 100, 0.5), 10)  # Clamp between 0.5% and 10% for safety
        return {
            "recommendation": f"✅ Валуй найден! Перевес: {edge*100:.1f}%. Справедливый кэф: {fair_odds:.2f}.",
            "stake_percent": f"{stake_percent:.1f}% от банка"
        }
    else:
        return {
            "recommendation": f"⛔ Пропуск. Перевес отрицательный: {edge*100:.1f}%. Справедливый кэф: {fair_odds:.2f}.",
            "stake_percent": "ПРОПУСК"
        }


def get_bet_recommendation(llm_response: str) -> dict:
    """
    Main function: extracts data and calculates bet recommendations.
    """
    data = extract_betting_data(llm_response)
    probability = data["probability"]
    odds = data["odds"]
    
    if probability is None:
        hint = "В ответе модели не найдена строка с числом вида «Вероятность победы: N%»."
        if re.search(r"Вероятность[^%\n]*\bP\s*%", llm_response, re.I):
            hint = "Модель оставила шаблон «P%» вместо числа — % для ставки не посчитать."
        return {
            "probability": None,
            "stake_percent": "ПРОПУСК",
            "recommendation": hint,
            "status": "invalid",
        }
        
    probability = max(0, min(100, probability))
    value_data = calculate_value_bet(probability, odds)
    
    return {
        "probability": probability,
        "stake_percent": value_data["stake_percent"],
        "recommendation": value_data["recommendation"],
        "status": "success",
    }

