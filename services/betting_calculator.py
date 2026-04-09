"""Betting recommendation calculator using Kelly Criterion and Value Betting"""
import re
import json


def normalize_score(raw_score: str) -> str:
    """
    Приводит счет к формату X:Y, поддерживает 2:1, 2-1, 2 1 и т.д.
    Если не найдено — возвращает "Н/Д".
    """
    if not isinstance(raw_score, str):
        return "Н/Д"
    m = re.search(r"(\d+)[:\-\s](\d+)", raw_score)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return "Н/Д"


def extract_probability(llm_response: str) -> float | None:
    """
    Извлекает процент вероятности из ответа модели.
    Учитывает markdown из контракта: «📈 **Вероятность победы (1-я сторона):** 58%».
    После скобки идёт `):**`, поэтому старые шаблоны с `[\\:\\s]+` после «сторона» не срабатывали.
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
    Falls back to existing regex for probability ONLY if JSON loading fails or fields are missing.
    """
    probability = None
    odds = None
    prob_t1 = None
    prob_t2 = None
    # Try finding JSON block
    match = re.search(r'```json\s*(\{.*?\})\s*```', llm_response, re.DOTALL | re.IGNORECASE)
    if not match:
        match = re.search(r'(\{.*?\})', llm_response, re.DOTALL)
    result = {
        "probability": None,
        "win_probability_team1": None,
        "win_probability_team2": None,
        "odds": None,
        "draw_probability": None,
        "recommended_bet_size": None,
        "confidence_score": None,
        "analysis_summary": None,
        "exact_score": "Н/Д",
        "total_prediction": "Н/Д",
        "total_recommendation": "Н/Д",
        "total_value": "Н/Д"
    }
    if match:
        try:
            json_str = match.group(1).strip()
            data = json.loads(json_str)
            # Вероятности
            prob_t1 = data.get("win_probability_team1")
            prob_t2 = data.get("win_probability_team2")
            if prob_t1 is not None:
                try: prob_t1 = float(prob_t1)
                except (ValueError, TypeError): prob_t1 = None
            if prob_t2 is not None:
                try: prob_t2 = float(prob_t2)
                except (ValueError, TypeError): prob_t2 = None
            if prob_t1 is None:
                prob_val = data.get("probability")
                if prob_val is not None:
                    try: prob_t1 = float(prob_val)
                    except: prob_t1 = None
            result["probability"] = prob_t1
            result["win_probability_team1"] = prob_t1
            result["win_probability_team2"] = prob_t2
            # Остальные поля
            result["odds"] = float(data.get("odds")) if data.get("odds") is not None else None
            result["draw_probability"] = data.get("draw_probability")
            result["recommended_bet_size"] = data.get("recommended_bet_size")
            result["confidence_score"] = data.get("confidence_score")
            result["analysis_summary"] = data.get("analysis_summary")
            # exact_score
            exact_score = data.get("exact_score")
            result["exact_score"] = normalize_score(exact_score)
            # total_prediction (float из строки или числа)
            total_pred = data.get("total_prediction")
            if isinstance(total_pred, (int, float)):
                result["total_prediction"] = float(total_pred)
            elif isinstance(total_pred, str):
                nums = re.findall(r"\d+[\.,]?\d*", total_pred)
                if nums:
                    result["total_prediction"] = float(nums[0].replace(",", "."))
                else:
                    result["total_prediction"] = "Н/Д"
            # total_recommendation
            total_rec = data.get("total_recommendation")
            if isinstance(total_rec, str) and total_rec.strip():
                result["total_recommendation"] = total_rec.strip()
            # total_value (совместимость)
            total_val = data.get("total_value")
            if isinstance(total_val, str) and total_val.strip():
                result["total_value"] = total_val.strip()
            elif result["total_prediction"] != "Н/Д":
                result["total_value"] = str(result["total_prediction"])
        except Exception:
            pass
    # Fallback to regex for probability
    if result["probability"] is None:
        result["probability"] = extract_probability(llm_response)
        result["win_probability_team1"] = result["probability"]
    return result


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
    probability = data.get("probability")
    odds = data.get("odds")
    
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
    
    # Priority to JSON recommended bet size
    json_bet_size = data.get("recommended_bet_size")
    value_data = calculate_value_bet(probability, odds)
    
    stake_percent = value_data["stake_percent"]
    if json_bet_size is not None:
        try:
            s_val = float(json_bet_size)
            if s_val > 0:
                stake_percent = f"{s_val}%"
            else:
                stake_percent = "ПРОПУСК"
        except (ValueError, TypeError):
            pass

    return {
        "probability": probability,
        "win_probability_team1": data.get("win_probability_team1") if data.get("win_probability_team1") is not None else probability,
        "win_probability_team2": data.get("win_probability_team2"),
        "odds": odds,
        "draw_probability": data.get("draw_probability"),
        "stake_percent": stake_percent,
        "confidence_score": data.get("confidence_score"),
        "analysis_summary": data.get("analysis_summary"),
        "exact_score": data.get("exact_score", "Н/Д"),
        "total_prediction": data.get("total_prediction", "Н/Д"),
        "total_recommendation": data.get("total_recommendation", "Н/Д"),
        "total_value": data.get("total_value", "Н/Д"),
        "recommendation": value_data["recommendation"],
        "status": "success",
    }

