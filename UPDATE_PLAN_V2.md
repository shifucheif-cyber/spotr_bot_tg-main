# UPDATE PLAN V2 — Roadmap будущих улучшений

> Реализованные пункты удалены. Ниже — только нереализованные и запланированные задачи.

---

## 1. Celery + Redis: очереди для тяжёлых запросов

- При пиковой нагрузке — ставить анализы в очередь
- Пользователь получает: «⏳ Вы 15-й в очереди, примерное время: 2 мин»
- Celery worker обрабатывает задачи, результат отправляется по готовности
- Redis как брокер сообщений и бэкенд кэша (замена in-memory dict)

## 2. FastAPI/aiohttp для вебхуков платежей

- Поднять микросервер для приёма вебхуков от платёжных систем
- YooKassa: вебхук подтверждения оплаты → активация подписки
- CryptoPay: вебхук подтверждения USDT-платежа
- Реальная верификация платежей в `payment_service.py`

## 3. Рефакторинг на мультиплатформенность (VK, MAX)

- Вынести бизнес-логику из `bot.py` → `services/logic.py` (обработка FSM, анализ, форматирование)
- `bot.py` → тонкий адаптер Telegram (aiogram)
- Добавить `bot_vk.py` — адаптер VK (vkbottle)
- Добавить `bot_max.py` — адаптер MAX
- Общие сервисы остаются без изменений: `data_fetcher`, `analysis_cache`, `event_phase`, `user_store`
- Поле `platform` в БД уже готово (миграция v2)

## 4. VK Pay интеграция

- Подключить VK Pay API для оплаты подписки в VK-боте
- Вебхуки подтверждения через FastAPI (см. пункт 2)

## 5. Оплата по СБП

- Интеграция с YooKassa или Тинькофф API для оплаты по СБП
- QR-код для оплаты в Telegram и VK
- Вебхук подтверждения → активация подписки

## 6. Мониторинг LLM latency

- Замер времени отклика каждого LLM-провайдера
- Автоматический выбор самого быстрого провайдера (вместо round-robin)
- Dashboard метрик (hit rate кэша, latency, error rate)

## 7. threading.Lock → asyncio.Lock (user_store)

- Заменить threading.Lock на asyncio.Lock для корректной работы в асинхронном контексте
- Проверить все concurrent-доступы к shared state

## 8. Атомарный суточный лимит

- Перенести проверку и инкремент daily limit в одну SQL-транзакцию
- Исключить race condition при параллельных запросах

---

## ✅ Реализовано (справка)

- asyncpg для user_store.py (полностью async, PostgreSQL + SQLite dual-backend)
- Разделение search_engine.py → search_providers/ (config, helpers, providers)
- Round-robin LLM балансировка (itertools.count + циклический сдвиг)
- Telegram-таймауты (asyncio.create_task для тяжёлых запросов)
- Фазовый кэш событий: EARLY(7d)→PRE_MATCH(2h)→LIVE(fresh)→FINISHED(48h кэш)→EXPIRED(блок), единый TTL на фазу, 4 уровня (LLM, поиск, team_id, валидация)
- Периодическая очистка кэшей (каждый час, порог 48ч)
- Окно поиска матчей: ±7 дней (соответствует клавиатуре бота)
- Миграции БД (schema_version + MIGRATIONS)
- Санитизация пользовательского ввода (_sanitize_user_input: длина + control chars)
- Маскировка API-ключей в ошибках LLM (_sanitize_error)
- Per-user семафор (asyncio.Semaphore) + таймаут анализа (300с)
- Graceful shutdown (отмена cleanup_task, close_pool)
- Upper bounds в requirements.txt (aiogram<4, httpx<1, openai<2 и т.д.)
- JSON-логирование (JsonFormatter, LOG_FORMAT=json)
- Заготовки мультиплатформенности (поле platform, Telegram Stars стабы)
