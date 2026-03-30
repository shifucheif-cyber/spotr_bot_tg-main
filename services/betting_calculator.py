"""Betting recommendation calculator using Kelly Criterion and Value Betting"""
import re
import json


def extract_probability(llm_response: str) -> float | None:
    """
    Extracts probability percentage from LLM response using fallback regex patterns.
    """
    match = re.search(r'Вероятность[^:]*:\s*(\d+(?:[.,]\d+)?)\s*%', llm_response, re.IGNORECASE)
    if match: return float(match.group(1).replace(',', '.'))
    
    match = re.search(r'[Пп]\s*[=:]\s*(\d+(?:[.,]\d+)?)\s*%', llm_response)
    if match: return float(match.group(1).replace(',', '.'))
    
    match = re.search(r'вероятность[^:]*:\s*(\d+(?:[.,]\d+)?)\s*%', llm_response, re.IGNORECASE)
    if match: return float(match.group(1).replace(',', '.'))
    
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*%', llm_response)
    if match: return float(match.group(1).replace(',', '.'))
    
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
        return {"recommendation": "Недопустимая вероятность", "stake_percent": "0"}
        
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
    
    if probability is None or probability == 0:
        return {
            "probability": None,
            "stake_percent": None,
            "recommendation": "Вероятность не определена (исход не найден)",
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

