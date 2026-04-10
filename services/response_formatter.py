import html as html_module
import re
import json
import logging
from services.name_normalizer import split_match_text

logger = logging.getLogger(__name__)


def _escape(text) -> str:
    """Escape HTML special characters for Telegram parse_mode=HTML."""
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    return html_module.escape(text)


def validate_prediction_consistency(prediction_struct: dict, team1: str = None, team2: str = None) -> None:
    """
    Корректирует exact_score в зависимости от winner и вероятности.
    Если winner — команда 1, а в exact_score голов у команды 2 больше, меняет местами.
    Если вероятность победы > 60%, а счет ничейный — пишет в лог предупреждение.
    Модифицирует prediction_struct in-place.
    """
    exact_score = prediction_struct.get("exact_score")
    winner = prediction_struct.get("winner")
    prob = prediction_struct.get("win_probability_team1")
    # Определяем ничью
    is_draw = False
    if isinstance(exact_score, str):
        m = re.match(r"(\d+):(\d+)", exact_score)
        if m:
            g1, g2 = int(m.group(1)), int(m.group(2))
            if g1 == g2:
                is_draw = True
            # winner: если победитель — команда 1, а голов у нее меньше, меняем счет
            if winner and team1 and team2:
                if winner.strip().lower() == team2.strip().lower() and g1 > g2:
                    prediction_struct["exact_score"] = f"{g2}:{g1}"
                elif winner.strip().lower() == team1.strip().lower() and g2 > g1:
                    prediction_struct["exact_score"] = f"{g2}:{g1}"
    # Если вероятность победы > 60%, а счет ничейный
    try:
        prob_val = float(prob) if prob is not None else None
        if prob_val is not None and prob_val > 60 and is_draw:
            logger.warning("Высокая вероятность победы (%.1f%%), но счет ничейный: %s", prob_val, exact_score)
    except Exception:
        pass

def _extract_contract_field(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" -*")
    return ""


def _sanitize_side_summary(text: str) -> str:
    """Убирает из сводки по команде хвосты с датой/следующими блоками (артефакты regex)."""
    if not text:
        return ""
    t = text.strip()
    for marker in (
        "\n📅", "\n🏆", "\n📈", "\n🔢", "\n💰", "\n📋", "\n📝", "\n•", "\n- **",
        "\n\n",
    ):
        i = t.find(marker)
        if 0 < i < len(t):
            t = t[:i].strip()
    for marker in ("📅", "**Дата:**", "Дата матча", "Победитель:", "Прогноз по сч"):
        i = t.find(marker)
        if i >= 0:
            t = t[:i].strip()
    # «vs соперник» как целая сводка — не аналитика
    t = re.sub(r"(?i)^vs\.?\s+\S+(?:\s+\S+)?\s*$", "", t).strip()
    t = re.sub(r"(?i)^vs\.?\s+", "", t).strip()
    if len(t) > 250:
        t = t[:247] + "..."
    return t


def format_response_contract(match_text: str, raw_analysis: str, prediction_struct: dict) -> str:

    # --- Новые поля: точный счет, тотал, рекомендации ---
    # Получаем имена команд (если возможно)
    team1, team2 = None, None
    try:
        teams = split_match_text(match_text)
        if len(teams) == 2:
            team1, team2 = teams
    except Exception:
        pass
    validate_prediction_consistency(prediction_struct, team1, team2)
    exact_score = prediction_struct.get("exact_score", "Н/Д")
    total_prediction = prediction_struct.get("total_prediction", "Н/Д")
    total_recommendation = prediction_struct.get("total_recommendation", "Н/Д")
    total_value = prediction_struct.get("total_value", "Н/Д")
    kelly_index = prediction_struct.get("stake_percent", "Н/Д")
    analysis_summary = prediction_struct.get("analysis_summary", "")

    """
    Format final response as a brief prognosis card.
    Extracts short summaries per participant + key prediction fields.
    No full analysis text — only concise output for the user.
    """
    # Strip JSON blocks from raw analysis (internal data, not for user)
    cleaned_analysis = re.sub(r'(?i)```json\s*\{.*?\}\s*```', '', raw_analysis, flags=re.DOTALL).strip()
    cleaned_analysis = re.sub(r'(?i)\{\s*"win_probability_team1".*?\}', '', cleaned_analysis, flags=re.DOTALL).strip()
    cleaned_analysis = re.sub(r'(?i)\{\s*"winner".*?\}', '', cleaned_analysis, flags=re.DOTALL).strip()

    # --- Новый блок вероятностей и победителя ---
    prob = prediction_struct.get("probability")
    stake = prediction_struct.get("stake_percent")
    # Попытка получить вероятности обеих команд
    prob1 = None
    prob2 = None
    # Если prediction_struct содержит обе вероятности (например, win_probability_team1, win_probability_team2)
    prob1 = prediction_struct.get("win_probability_team1")
    prob2 = prediction_struct.get("win_probability_team2")
    # Если только одна вероятность (старый формат)
    if prob1 is None and prob is not None:
        prob1 = prob
    if prob2 is None and prob1 is not None:
        prob2 = 100 - prob1
    # Корректируем, если обе заданы и не дают 100
    if prob1 is not None and prob2 is not None:
        s = prob1 + prob2
        if abs(s - 100) > 0.1 and s > 0:
            prob1 = round(prob1 * 100 / s, 1)
            prob2 = round(prob2 * 100 / s, 1)

    winner = _extract_contract_field(cleaned_analysis, [r"Победитель:\s*(.+)", r"Исход:\s*(.+)", r"Прогноз победителя:\s*(.+)"])
    score = _extract_contract_field(cleaned_analysis, [r"Прогноз по счету:\s*(.+)", r"Прогноз по сч[её]ту / картам / сетам:\s*(.+)", r"Сч[её]т:\s*(.+)"])
    total = _extract_contract_field(cleaned_analysis, [r"Тотал:\s*(.+)", r"Total:\s*(.+)", r"Тотал карт:\s*(.+)", r"Total maps:\s*(.+)"])

    sides = split_match_text(match_text)
    side1_summary = ""
    side2_summary = ""
    if len(sides) == 2:
        for side_idx, (side, _target) in enumerate([(sides[0], "side1_summary"), (sides[1], "side2_summary")]):
            escaped = re.escape(side)
            patterns = [
                rf"(?m)(?:^|\n)\s*[•\-]\s*\*{{0,2}}\[?{escaped}\]?\*{{0,2}}\s*[:：]\s*(.+?)(?=\n\s*[•\-📈🏆📊📋💰🔢📅]|\n\n|\Z)",
                rf"(?m)(?:^|\n)\s*\*{{0,2}}\[?{escaped}\]?\*{{0,2}}\s*[:：]\s*(.+?)(?=\n\s*[•\-📈🏆📊📋💰🔢📅]|\n\n|\Z)",
                rf"(?m)(?:^|\n)\s*📝\s*\*\*\[?{escaped}\]?\*\*\s*[:：]\s*(.+?)(?=\n\s*[•\-📈🏆📊📋💰🔢📅📝]|\n\n|\Z)",
            ]
            for pattern in patterns:
                m = re.search(pattern, cleaned_analysis, re.I | re.S)
                if m:
                    text = m.group(1).strip()
                    sentences = re.split(r"(?<=[.!?])\s+", text)
                    text = " ".join(sentences[:2]).strip()
                    text = _sanitize_side_summary(text)
                    if len(text) < 12:
                        continue
                    if side_idx == 0:
                        side1_summary = text
                    else:
                        side2_summary = text
                    break

    stake_text = str(stake) if stake is not None else "ПРОПУСТИТЬ"
    # --- HTML-структура для Telegram ---
    html = []
    html.append(f"🏆 <b>Победитель:</b> {_escape(winner) or '?'}")
    if len(sides) == 2 and prob1 is not None and prob2 is not None:
        html.append(f"📈 <b>Вероятность:</b> {_escape(sides[0])} {prob1:.1f}% | {_escape(sides[1])} {prob2:.1f}%")
    elif prob1 is not None:
        html.append(f"📈 <b>Вероятность:</b> {prob1:.1f}%")
    else:
        html.append(f"📈 <b>Вероятность:</b> не определена")
    html.append(f"🔢 <b>Прогноз счета:</b> {_escape(exact_score) if exact_score else 'Н/Д'}")
    html.append(f"📊 <b>Ожидаемый тотал:</b> {_escape(total_prediction) if total_prediction else 'Н/Д'} ({_escape(total_recommendation) if total_recommendation else 'Н/Д'})")
    simple_stake = prediction_struct.get('simple_stake', 'Н/Д')
    html.append(f"💰 <b>Ставка:</b> {_escape(prediction_struct.get('recommendation', 'Н/Д'))}")
    html.append(f"📏 <b>Размер:</b> рекомендация {_escape(simple_stake)} от банка | Келли: {_escape(kelly_index)}")
    html.append(f"💡 <b>Анализ:</b> {_escape(analysis_summary)}")
    return "\n".join(html)


def split_long_message(text: str, max_length: int = 4000) -> list[str]:
    """Разбивает большое сообщение на части (лимит Telegram - 4096)"""
    if len(text) <= max_length:
        return [text]
    
    messages = []
    current = ""
    
    # Разбиваем по абзацам
    paragraphs = text.split("\n\n")
    
    for para in paragraphs:
        # Если один абзац длиннее лимита — режем по строкам
        if len(para) > max_length:
            if current:
                messages.append(current)
                current = ""
            lines = para.split("\n")
            for line in lines:
                if len(current) + len(line) + 1 > max_length:
                    if current:
                        messages.append(current)
                    current = ""
                current += line + "\n"
            continue
        if len(current) + len(para) + 2 > max_length:
            if current:
                messages.append(current)
                current = ""
        current += para + "\n\n"
    
    if current:
        messages.append(current)
    
    return [msg.strip() for msg in messages if msg.strip()]


def format_prediction_response(analysis_match: str, raw_response: str) -> str:
    """Форматирует ответ от LLM в финальный вид для пользователя."""
    from services.betting_calculator import get_bet_recommendation
    prediction_struct = get_bet_recommendation(raw_response)
    return format_response_contract(analysis_match, raw_response, prediction_struct)
