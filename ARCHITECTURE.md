# Архитектура Telegram-бота спортивной аналитики

## Общая логика работы

Бот принимает запросы пользователей в Telegram, валидирует введённые данные (дисциплина, команды/игроки, дата), собирает информацию из внешних источников, передаёт её в LLM и возвращает структурированный прогноз с вероятностями, счётом и рекомендациями.

## Используемый стек

- Python 3.13+
- aiogram (асинхронный Telegram Bot API)
- httpx (асинхронные HTTP-запросы)
- LLM-провайдеры: Groq/AsyncGroq (primary), SambaNova/AsyncOpenAI, Google Gemini (async genai), DeepSeek/AsyncOpenAI — с автоматическим fallback
- PostgreSQL через asyncpg (асинхронный пул)
- Markdown (документация и промпты)
- Внешние спортивные API и поисковые движки (DDG, Serper, Tavily, Exa) — все async
- `hltv` / `sportsipy` зарезервированы как первый контур сбора данных об участниках; интеграция в рабочий пайплайн пока не реализована

## Структура файлов и назначение модулей

### Корневые файлы

- `bot.py` — точка входа. FSM-обработчики Telegram, генерация через LLM с fallback, запуск polling. Использует `services/llm_clients.py` для инициализации LLM-клиентов.
- `data_router.py` — маршрутизация запросов по дисциплинам: определяет нужный сервис и вызывает его.
- `preflight_check.py` — offline-проверка окружения перед запуском: `.env`, API-ключи, критичные импорты, bootstrap LLM-клиентов. Итог: `PASS / WARN / FAIL`. Вызывается автоматически при старте бота и доступен как отдельная команда.
- `requirements.txt` — зависимости Python.
- `runtime.txt` — версия Python для деплоя.

### Каталог services/

- `llm_clients.py` — единый bootstrap LLM-клиентов (Google, Groq/AsyncGroq, DeepSeek/AsyncOpenAI, SambaNova/AsyncOpenAI). Groq и Google используют нативные async-клиенты. Инициализирует клиентов из env, при ошибке сохраняет причину в `init_errors` без WARNING-логов. Подробная диагностика — через `get_init_report()` и уровень `DEBUG`.
- `basketball_service.py`, `football_service.py`, `hockey_service.py`, `tennis_service.py`, `table_tennis_service.py`, `volleyball_service.py`, `mma_service.py`, `cs2_service.py` — сбор и агрегация данных по конкретной дисциплине.
- `data_fetcher.py` — маршрутизация сбора данных по дисциплинам. Fetcher-классы — маркеры дисциплин (только атрибут `_discipline`). `fetch_match_analysis_data` — единая точка входа, делегирующая в `collect_discipline_data()`. Блокирует запросы для завершённых событий (фаза FINISHED/EXPIRED).
- `event_phase.py` — определение фазы жизненного цикла события (EARLY → PRE_MATCH → LIVE → FINISHED → EXPIRED). Фазовый TTL для кэшей поиска и LLM. Длительность событий по дисциплинам (football=2ч, hockey=3ч, tennis=4ч и т.д.).
- `search_engine.py` — универсальный слой поиска (полностью async). Тонкий оркестровщик: пайплайн-функции + реэкспорт имён из `search_providers/`. `collect_discipline_data()` — основной пайплайн: Serper#1(min) → Serper#2(max) → `check_required_data()` → Tavily/Exa(если missing) → DDG(fallback если Serper недоступен). `validate_match_request()` — async DDG-валидация события. `collect_validated_sources()` — async-каскад для валидации.

### Каталог services/search_providers/

Вынесенные из `search_engine.py` модули:

- `config.py` — все константы, API-ключи, конфигурации дисциплин (`DISCIPLINE_SOURCE_CONFIG`, `RUSSIAN_*` hints, `_REQUIRED_DATA_PATTERNS`).
- `helpers.py` — утилиты: нормализация, валидация, определение региона, построение запросов.
- `providers.py` — провайдерские функции (DDG, Serper, Exa, Tavily), асинхронное скачивание страниц (`_fetch_page_excerpt_async`), анализ. Serper и Exa — exponential backoff при 429 (до 3 попыток, задержка `2^attempt` сек).
- `discipline_config.py` — конфигурация 12 дисциплин: типы участников, шаблоны поисковых запросов (RU/EN), обязательные/желательные данные.
- `betting_calculator.py` — расчёт вероятностей, извлечение данных из ответа LLM, формирование рекомендаций по ставкам.
- `response_formatter.py` — форматирование финального ответа для Telegram, разбивка длинных сообщений.
- `external_source.py` — async-работа с внешними источниками данных (TheSportsDB и др.), использует `httpx.AsyncClient`.
- `logging_utils.py` — конфигурация логирования: подавление шумных внешних логгеров (httpx, groq, openai, google_genai), настройка уровней через env.
- `user_store.py` — работа с БД пользователей (PostgreSQL): учёт запросов, статистика, администрирование, промо-коды, подписки. **Полностью async** через `asyncpg.create_pool()`. Поле `platform` (дефолт `'tg'`) — заготовка для мультиплатформенности (VK, MAX). `_q()` конвертирует `?` в `$1, $2, ...` для asyncpg, корректно обрабатывает `?` внутри SQL-строковых литералов.
- `payment_service.py` — заготовка верификации платежей (RUB, USDT по 7 сетям, Telegram Stars). Функции — заглушки до интеграции с платёжными провайдерами и TG Wallet API.
- `prompts.py` — загрузка и подготовка промптов для LLM из каталога `prompts/`.
- `e2e_summary.py` — сбор и вывод итоговой E2E-статистики.
- `name_normalizer.py` — нормализация и коррекция названий команд и игроков.
- `match_finder.py` — поиск и сопоставление событий, формирование fallback-данных.

### Каталог prompts/

Markdown-файлы с промптами для разных дисциплин (`football.md`, `hockey.md`, `cs2.md`, `cybersport.md`, `tennis.md`, `basketball.md`, `volleyball.md`, `mma.md`, `boxing.md`, `dota2.md`, `lol.md`, `valorant.md`, `table_tennis.md`) и общий контракт ответа (`common_suffix.md`).

### Каталог tests/

Тесты (251 тест):

- `test_event_phase.py` — фазовая модель событий, TTL, блокировка, форматы дат, длительности дисциплин.
- `test_analysis_cache.py` — кэш LLM-анализов, фазовый TTL, cleanup.
- `test_data_fetcher_cache.py` — кэш поисковых данных, фазовый TTL, cleanup.
- `test_betting_calculator.py` — расчёт вероятностей и рекомендаций.
- `test_bot_flow.py` — FSM-переходы и обработчики бота.
- `test_data_router.py` — маршрутизация по дисциплинам.
- `test_response_formatter.py` — форматирование ответов.
- `test_search_engine.py` — поиск, валидация, `check_required_data` (all/none/partial/empty/case).
- `test_llm_clients.py` — инициализация LLM-клиентов, fallback.
- `test_preflight.py` — проверка окружения (PASS/WARN/FAIL).
- `test_prompts.py` — загрузка промптов, наличие файлов.
- `test_name_normalizer.py` — нормализация имён, транслитерация.
- `test_match_finder.py` — парсинг команд, дат (с учетом таймзоны МСК), дисциплин, кэш валидации.
- `test_user_store.py` — CRUD пользователей, событий, миграции схемы, суточные лимиты, промо-коды, подписки, доступ, поле platform. Требует PostgreSQL (pytest-postgresql); без PG эти тесты пропускаются, с настроенным PG входят в общий зелёный прогон.
- `test_payment_service.py` — заглушки платёжного сервиса (RUB, USDT, Telegram Stars, неподдерживаемые сети).
- `test_external_source.py` — TheSportsDB API (mock httpx), кэш team_id.
- `test_logging_utils.py` — конфигурация логирования.
- `test_e2e_summary.py` — E2E-телеметрия.
- `test_sport_services.py` — все спортивные сервисы (8 дисциплин).
- `test_discipline_config.py` — конфигурация дисциплин, шаблоны запросов.
- `test_collect_discipline_data.py` — пайплайн сбора данных (Serper→check_required→Tavily/Exa→DDG).

Запуск: `python -m pytest tests/`

> **Примечание:** `test_user_store.py` требует PostgreSQL (`pg_ctl` в PATH). На настроенной среде полный прогон сейчас проходит как `251 passed`, без skip.

## Процесс обработки запроса

1. Пользователь отправляет `/start` в Telegram.
2. `bot.py` (FSM) последовательно собирает: дисциплину, поддисциплину (если есть), команды/игроков, дату.
3. Введённые данные валидируются: нормализация имён (`name_normalizer`), проверка матча (`search_engine.validate_match_request`), поиск события (`external_source`).
4. `data_router.py` определяет нужный сервис по дисциплине и вызывает его.
5. Сервис дисциплины инициирует сбор данных через `data_fetcher.fetch_match_analysis_data()` → `search_engine.collect_discipline_data()`. Текущий рабочий пайплайн: Serper(query#1 min) → Serper(query#2 max) → `check_required_data()` → если missing: Tavily/Exa целевыми запросами → DDG fallback если Serper недоступен. Целевой пайплайн для следующего контура: `hltv`/`sportsipy` как первичный сбор участников → DDG для валидации и дополнения → Serper для замен, формы, карточек, новостей и характеристик → Tavily/Exa, если минимальный набор после первых этапов не собран. Данные валидации переиспользуются через `pre_validated_sources`. Язык запросов определяется автоматически (RU для российского контекста). Страницы скачиваются для извлечения выжимок (`_fetch_page_excerpt_async`). После сбора — min-data gate: предупреждение в отчёте если обязательные данные не найдены.
6. Собранные данные нормализуются и агрегируются в payload.
7. Payload + системный промпт передаются в LLM через **round-robin ротацию** с fallback: при каждом вызове стартовый провайдер смещается циклически (`groq → sambanova → google → deepseek → groq → ...`), обеспечивая равномерную нагрузку. При ошибке — следующий по кругу.
8. LLM возвращает структурированный прогноз (JSON + текстовый анализ).
9. `betting_calculator.py` извлекает вероятности и проверяет корректность. `response_formatter.py` форматирует финальный ответ.
10. Ответ отправляется пользователю в Telegram (с разбивкой на части при необходимости).

## LLM Fallback

Порядок: `groq → sambanova → google → deepseek` — **round-robin ротация**: каждый вызов начинается с нового провайдера (циклический сдвиг счётчиком `itertools.count()`). При ошибке — следующий по кругу.

Каждый провайдер пробуется с таймаутом 60 с (Groq — 15 с для быстрого failover). При неудаче — следующий. Если все упали — пользователю возвращается сообщение об ошибке. Инициализация клиентов вынесена в `services/llm_clients.py` и не генерирует WARNING-логов при старте — ошибки сохраняются тихо и проявляются только при фактическом вызове или в preflight-отчёте.

## Кэширование

4 уровня in-memory кэша с **фазовым TTL** на основе жизненного цикла события (`services/event_phase.py`):

| Фаза | Условие | TTL | Поведение |
| ------ | --------- | ----- | ----------- |
| EARLY | >12ч до начала | 7 дней | Один запрос — потом кэш до PRE_MATCH |
| PRE_MATCH | ≤12ч до начала | 2ч | Обновление каждые 2ч |
| LIVE | во время события | 0 | Всегда свежий запрос |
| FINISHED | 0..24ч после конца | 48ч | Кэш ≤48ч + ⚠️ или «уточните» |
| EXPIRED | >24ч после конца | — | Полный блок ⛔ |

**Уровни кэша:**

1. **LLM-анализ** (`analysis_cache.py`) — кэш результатов LLM, до 100 записей, LRU-вытеснение.
2. **Поисковые данные** (`data_fetcher.py`) — кэш данных из Serper/Tavily/Exa/DDG, до 200 записей, LRU.
3. **Team ID** (`external_source.py`) — кэш ID команд TheSportsDB, TTL 48ч. None не кэшируется.
4. **Валидация матча** (`match_finder.py`) — кэш `check_match_clarification()`, TTL 48ч. None кэшируется. Окно поиска: ±7 дней.

Все 4 кэша используют `asyncio.Lock` для потокобезопасности в async-контексте.

**Периодическая очистка:** `_periodic_cache_cleanup()` запускается при старте бота, каждый час удаляет записи старше 48ч из всех 4 кэшей.

**Блокировка завершённых событий:** при FINISHED — отдаётся кэш ≤48ч + предупреждение, или «данные устарели, уточните запрос». При EXPIRED — полный блок.

## Preflight и запуск

При старте `bot.py` автоматически запускает preflight-проверку из `preflight_check.py`:

- `FAIL` — бот не стартует, выводит причину.
- `WARN` — бот стартует, логирует предупреждение.
- `PASS` — чистый старт.

Сетевые ошибки Telegram (`TelegramNetworkError`, `ClientConnectorError`) обрабатываются gracefully: одна строка вместо traceback, корректное закрытие aiohttp-сессии.

## Переменные окружения

| Переменная | Обязательная | Описание |
| --- | --- | --- |
| `TELEGRAM_TOKEN` | Да | Токен Telegram-бота |
| `GROQ_API_KEY` | Одна из LLM* | Ключ Groq API |
| `SAMBANOVA_API_KEY` | Одна из LLM* | Ключ SambaNova API |
| `GOOGLE_API_KEY` | Одна из LLM* | Ключ Google Gemini API |
| `DEEPSEEK_API_KEY` | Одна из LLM* | Ключ DeepSeek API |
| `DATABASE_URL` | Да | Строка подключения PostgreSQL |
| `APP_LOG_LEVEL` | Нет | Уровень логирования приложения (`DEBUG`, `INFO`, `WARNING`) |
| `EXTERNAL_LOG_LEVEL` | Нет | Уровень логирования внешних библиотек (по умолчанию `ERROR`) |
| `QUIET_E2E_SUMMARY` | Нет | `true` — выводить E2E-телеметрию в stdout |
| `SERPER_API_KEY` | Нет | Ключ Serper для расширенного поиска |
| `TAVILY_API_KEY` | Нет | Ключ Tavily для аналитического поиска |
| `EXA_API_KEY` | Нет | Ключ Exa для аналитического поиска |
| `ENABLE_PAYWALL` | Нет | `true` — включить лимит бесплатных запросов (по умолчанию `false`) |
| `MAX_FREE_REQUESTS` | Нет | Суточный лимит бесплатных запросов (по умолчанию `3`) |
| `SUBSCRIPTION_PRICE_RUB` | Нет | Цена подписки в рублях (заготовка) |
| `SUBSCRIPTION_PRICE_USDT` | Нет | Цена подписки в USDT (заготовка) |
| `SUBSCRIPTION_DAYS` | Нет | Дней подписки при оплате (по умолчанию `30`) |

\* Минимум один LLM-ключ обязателен.

## Пример финального ответа

```text
📊 Матч: Реал Мадрид vs Барселона

📋 Факты из данных:
- (Реал не проигрывает 7 матчей → преимущество Реал)
- (Барселона без двух ключевых защитников → преимущество Реал)
- (Последние 3 очные встречи — ничьи → нейтрально)

📝 Анализ:
• Реал: стабильная форма, сильный состав
• Барселона: проблемы в обороне

📈 Вероятность победы (1-я сторона): 62%
🏆 Победитель: Реал Мадрид
🔢 Прогноз по счету: 2:1
💰 Рекомендуемый % от банка: 3%

{
"win_probability_team1": 62,
"win_probability_team2": 38,
"draw_probability": 0,
"recommended_bet_size": 3,
"confidence_score": 0.85,
"analysis_summary": "Реал в лучшей форме и без потерь в составе.",
"exact_score": "2:1",
"total_prediction": 3.0,
"total_recommendation": "ТБ 2.5",
"total_value": "3.0"
}
```

## Безопасность

- **Санитизация ввода:** `_sanitize_user_input()` — обрезка по длине (100 символов), удаление управляющих символов (U+0000–U+001F кроме пробела), strip. Защита от prompt injection.
- **Редактирование ошибок:** `_sanitize_error()` — regex-маскировка API-ключей (`sk-*`, `gsk-*`, `Bearer`, `key=`) в сообщениях об ошибках LLM-клиентов.
- **Per-user семафор:** `asyncio.Semaphore(1)` на пользователя — блокировка параллельных запросов анализа.
- **Таймаут анализа:** `asyncio.wait_for(timeout=300)` — защита от зависших LLM-вызовов.
- **Graceful shutdown:** корректное завершение — отмена фоновых задач, закрытие пула БД (`close_pool()`).
- **Upper bounds в requirements.txt:** ограничение мажорных версий критичных зависимостей.

## Принципы

- Весь код асинхронный (async/await, httpx).
- Обработка ошибок: 429, 404, таймауты, сетевые сбои.
- Все внешние запросы — через httpx.
- LLM-инициализация тихая по умолчанию, диагностика по запросу.
- Промпты и формат ответов стандартизированы (см. `prompts/common_suffix.md`).
- Fallback-порядок: `groq → sambanova → google → deepseek`.
