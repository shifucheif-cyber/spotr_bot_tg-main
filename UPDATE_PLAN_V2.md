# UPDATE PLAN V2 — Roadmap будущих улучшений

## 1. ✅ asyncpg для user_store.py

- ✅ Заменили `psycopg2-binary` (sync) на `asyncpg` (полный неблокирующий PostgreSQL-драйвер)
- ✅ Все функции `user_store.py` — `async def`, PostgreSQL через `asyncpg.create_pool()`, SQLite через `asyncio.to_thread()`
- ✅ `ThreadPoolExecutor` удалён из `bot.py`
- ✅ Все вызовы user_store в bot.py обёрнуты в `await`
- ✅ Тесты переведены на `IsolatedAsyncioTestCase`

## 2. Celery + Redis: очереди для тяжёлых запросов

- При пиковой нагрузке — ставить анализы в очередь
- Пользователь получает: «⏳ Вы 15-й в очереди, примерное время: 2 мин»
- Celery worker обрабатывает задачи, результат отправляется по готовности
- Redis как брокер сообщений и кэш

## 3. ✅ Разделение search_engine.py на search_providers/

- ✅ Вынесено в `services/search_providers/`:
  - `config.py` — константы, API-ключи, конфигурации дисциплин
  - `helpers.py` — утилиты нормализации/валидации
  - `providers.py` — функции провайдеров (DDG, Serper, Exa, Tavily)
- ✅ `search_engine.py` — тонкий оркестровщик + реэкспорт имён (обратная совместимость mock-путей)
- ✅ Все 159 тестов проходят без изменений

## 4. FastAPI/aiohttp для вебхуков платежей

- Поднять микросервер для приёма вебхуков от платёжных систем
- YooKassa: вебхук подтверждения оплаты → активация подписки
- CryptoPay: вебхук подтверждения USDT-платежа
- Реальная верификация платежей в `payment_service.py`

## 5. ✅ Round-robin LLM балансировка

- ✅ Поочерёдное использование провайдеров: `itertools.count()` + циклический сдвиг `LLM_FALLBACK_ORDER`
- ✅ При ошибке — fallback на следующего, но стартовый провайдер ротируется
- Будущее улучшение: мониторинг latency и автоматический выбор самого быстрого

## 6. Кэширование результатов поиска

- Redis-кэш для результатов поисковых запросов (TTL 1-4 часа)
- Дедупликация одинаковых матчей от разных пользователей
- Снижение нагрузки на платные API (Serper, Tavily, Exa)

---

## 📅 Задачи из аудита (изменить сегодня или завтра)

### 7. ✅ Telegram-Таймауты и Блокировки

- **Решение:** `asyncio.create_task()` — тяжёлая работа (fetch+LLM) вынесена в `_run_analysis()`, `start_analysis()` освобождает FSM мгновенно. Подготовка к webhook-режиму.

### 8. ✅ Кэширование LLM-ответов

- **Решение:** `services/analysis_cache.py` — in-memory TTL-кэш (2ч, 100 записей, LRU-вытеснение). Ключ: MD5(discipline + sorted teams + date). При Redis — заменить словарь на Redis-клиент.

### 9. ✅ Миграции БД (Schema Versioning)

- **Решение:** Таблица `schema_version` + нумерованные миграции в `init_user_store()`. Новые миграции — добавить SQL в список `MIGRATIONS`. Без Alembic, без внешних зависимостей.

### 10. ✅ JSON-логирование

- **Решение:** `JsonFormatter` в `logging_utils.py`. `LOG_FORMAT=json` — JSON в stdout. `LOG_ERROR_FILE=errors.log` — ERROR+ в файл (всегда JSON). Без Sentry, без внешних зависимостей.
