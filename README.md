# spotr_bot_tg

Telegram-бот спортивной аналитики (aiogram + LLM + поиск по источникам).

## Быстрый старт на сервере или новой машине

1. **Python 3.11+** (на сервере без GUI достаточно `python3`).

2. Клонировать репозиторий, перейти в каталог проекта.

3. Виртуальное окружение и зависимости (включая **`hltv`** для CS2 и всё из поиска):

   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\python.exe -m pip install -U pip
   venv\Scripts\python.exe -m pip install -r requirements.txt
   # Linux/macOS:
   ./venv/bin/python -m pip install -U pip
   ./venv/bin/python -m pip install -r requirements.txt
   ```

4. Скопировать `.env` с секретами (в репозиторий не коммитится). Шаблон имён переменных — `.env.example`.

5. Запуск:

   ```bash
   venv\Scripts\python.exe bot.py
   # или: ./venv/bin/python bot.py
   ```

Важно: бот всегда запускать **интерпретатором из `venv`**, иначе будет `No module named 'hltv'` и другие отсутствующие пакеты.

## Сеть и VPN

К **api.telegram.org** нужен стабильный HTTPS. VPN может давать обрывы (`ServerDisconnectedError`); на сервере в датацентре обычно VPN не нужен.

## Переменные окружения

См. `.env.example`: токен Telegram, ключи LLM (Google, Groq, DeepSeek, SambaNova), Serper, Tavily, Exa при необходимости.
