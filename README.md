# spotr_bot_tg

Telegram-бот спортивной аналитики (aiogram + LLM + поиск по источникам).

## Быстрый старт на сервере или новой машине

1. **Python 3.13+** (на сервере без GUI достаточно `python3`).

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

5. Проверка окружения перед запуском:

   ```bash
   venv\Scripts\python.exe preflight_check.py
   # или: ./venv/bin/python preflight_check.py
   ```

   Скрипт проверяет `.env`, обязательные ключи, импорты и инициализацию LLM-клиентов. Итог: `PASS / WARN / FAIL`.

6. Запуск:

   ```bash
   venv\Scripts\python.exe bot.py
   # или: ./venv/bin/python bot.py
   ```

Важно: бот всегда запускать **интерпретатором из `venv`**, иначе будет `No module named 'hltv'` и другие отсутствующие пакеты.

## Сеть и VPN

К **api.telegram.org** нужен стабильный HTTPS. VPN может давать обрывы (`ServerDisconnectedError`); на сервере в датацентре обычно VPN не нужен.

## Переменные окружения

См. `.env.example`: токен Telegram, ключи LLM (Google, Groq, DeepSeek, SambaNova), Serper, Tavily, Exa при необходимости. Полный список переменных и их описание — в `ARCHITECTURE.md`, раздел «Переменные окружения».

## База данных

По умолчанию используется PostgreSQL через **asyncpg** (асинхронный пул). Задайте `DATABASE_URL` в `.env`. Для локальной разработки/тестов можно использовать SQLite: `DB_BACKEND=sqlite` в `.env` (обращения к SQLite оборачиваются в `asyncio.to_thread`). Подробнее — в `.env.example`.

## Зависимости

- `requirements.txt` — основные зависимости (без версий).
- `requirements.lock` — зафиксированные версии (`pip freeze`). Для воспроизводимого деплоя: `pip install -r requirements.lock`.

## Тесты

```bash
python -m unittest discover -s tests -p "test_*.py"
```

159 тестов покрывают: LLM-клиенты, preflight, промпты, нормализацию имён, поиск матчей (включая работу с часовыми поясами МСК), хранилище пользователей (миграция БД, суточные лимиты, промо-коды, подписки, доступ), платёжный сервис (заглушки), внешние источники, логирование, E2E-телеметрию, все 8 спортивных сервисов, betting calculator, data router, response formatter, search engine, конфигурацию дисциплин, сбор данных (collect_discipline_data) и флоу Telegram бота (включая paywall-гейт).
