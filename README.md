# Restos

Система оценки сотрудников: Telegram-бот, веб-приложение и API для проведения замеров, управления критериями и аналитики.

## Стек

| Компонент | Технологии |
|-----------|------------|
| Backend | Python 3.11, FastAPI, aiogram 3, SQLAlchemy, asyncpg |
| Frontend | Dioxus (Rust → WASM), `resty_form_alpha/` |
| Хранилище | PostgreSQL, Redis |
| Инфраструктура | Docker Compose, Alembic |

## Быстрый старт

```bash
cp .env.production.example .env
# Заполните обязательные переменные (см. ниже)

docker compose up -d --build
```

После запуска:
- API: `http://localhost:8000`
- Веб-приложение: `http://localhost:8080`
- Telegram-бот: сервис `bot` (long polling)

Контейнер `api` применяет миграции перед запуском. При первом старте создаётся организация и учётная запись администратора (см. `DEFAULT_ADMIN_*`).

## Переменные окружения

| Переменная | Назначение |
|------------|------------|
| `DATABASE_URL` | PostgreSQL (asyncpg) |
| `REDIS_DSN` | Redis для сессий и приглашений |
| `TGBOT_TOKEN` | Токен Telegram-бота |
| `JWT_SECRET_KEY` | Подпись JWT для веб-авторизации |
| `WEBAPP_SECRET_KEY` | Ключ шифрования токенов веб-форм (64 hex-символа) |
| `WEBAPP_BASE_URL` | URL фронтенда |
| `WEBAPP_API_URL` | URL API (если отличается от фронтенда) |
| `CORS_ORIGINS` | Разрешённые origins (через запятую) |
| `DEFAULT_ADMIN_LOGIN` / `DEFAULT_ADMIN_PASSWORD` | Первый администратор |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Путь к JSON сервисного аккаунта Google |
| `GOOGLE_SERVICE_ACCOUNT_JSON_DATA` | Альтернатива: JSON в переменной окружения |

Полный шаблон — в `.env.production.example`.

## Структура проекта

```
app/
  api/              # FastAPI: auth, web-data, webapp
    routers/web/    # Эндпоинты веб-приложения (сотрудники, замеры, критерии, AI)
  infra/database/   # Модели и репозитории (asyncpg)
  internal/services/# Бизнес-логика
  tgbot/            # Telegram-бот и диалоги
resty_form_alpha/   # Веб-интерфейс (Dioxus)
migrations/         # Alembic
docker/             # Dockerfile для api, bot, dioxus
```

## Функциональность

**Замеры (evaluations)** — создание, заполнение в боте или веб-форме, черновики, экспорт PDF/Excel.

**Наборы критериев** — ручное создание, импорт из Excel, привязка к Google Таблицам с автосинхронизацией.

**Google Sheets** — preview, создание набора из таблицы или папки Drive, ручная синхронизация.

**ИИ-ассистент** — анализ данных организации, помощь с критериями (веб и Telegram).

**Роли** — суперпользователь, администратор организации, менеджер, сотрудник. Доступ через JWT + PIN в вебе, через Telegram в боте.

## Локальная разработка

```bash
poetry install
poetry run alembic upgrade head
poetry run uvicorn fastapi_app:app --reload --port 8000
```

Фронтенд:

```bash
cd resty_form_alpha && dx serve
```

## Лицензия

См. [LICENSE](LICENSE).
